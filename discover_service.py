from __future__ import annotations

import json
import math
import os
import random
import re
import shutil
import tempfile
import threading
import time
from collections import Counter
from typing import Any, Callable

from deemix_service import DEFAULT_QUALITY, QUALITY_LABELS
from deemix_service import get_job as get_deemix_job
from deemix_service import get_status as get_deemix_status
from deemix_service import load_config as load_deemix_config
from deemix_service import start_download_job
from ipod_service import GpodError, delete_tracks, load_library, resolve_ipod_root
from ipod_service import _has_itunesdb_under_root


class DiscoverError(RuntimeError):
    pass


DAY_SECONDS = 24 * 60 * 60
WEEK_SECONDS = 7 * DAY_SECONDS
# An album is a few hundred MB once FLAC is converted to ALAC; refuse to start
# one when the device is nearly full rather than failing halfway through gpod-cp.
MIN_FREE_BYTES = 1024 * 1024 * 1024

# Album record lifecycle. "pending" covers download + copy; the rest are final
# except "trial", which the scheduler moves to "expired" once its time is up.
ACTIVE_STATUSES = ("pending", "trial")

DEFAULT_PREFERENCES: dict[str, Any] = {
    "temperature": 0.5,
    "batch_size": 24,
    "trial_days": 7,
    "trial_quality": "",
    "max_active_trials": 10,
    "include_eps": False,
    "weekly_refresh": False,
}

# Deezer's genre ids are stable; its genre names are localized to the server's
# region, so library genre tags are mapped through English keywords instead.
# More specific keywords come first ("hip hop" before "pop", "metal" before "rock").
_GENRE_KEYWORDS: tuple[tuple[str, int], ...] = (
    ("hip hop", 116),
    ("hip-hop", 116),
    ("rap", 116),
    ("r&b", 165),
    ("rnb", 165),
    ("soul", 169),
    ("funk", 169),
    ("metal", 464),
    ("indie", 85),
    ("alternative", 85),
    ("punk", 152),
    ("rock", 152),
    ("electro", 106),
    ("house", 106),
    ("techno", 106),
    ("ambient", 106),
    ("dance", 113),
    ("disco", 113),
    ("folk", 466),
    ("reggae", 144),
    ("jazz", 129),
    ("classical", 98),
    ("soundtrack", 173),
    ("blues", 153),
    ("latin", 197),
    ("pop", 132),
)
_GENRE_LABELS = {
    116: "Hip Hop",
    165: "R&B",
    169: "Soul & Funk",
    464: "Metal",
    85: "Alternative",
    152: "Rock",
    106: "Electronic",
    113: "Dance",
    466: "Folk",
    144: "Reggae",
    129: "Jazz",
    98: "Classical",
    173: "Soundtracks",
    153: "Blues",
    197: "Latin",
    132: "Pop",
}

_CACHE_TTL_SECONDS = {
    "artist_ids": 30 * DAY_SECONDS,
    "related": 7 * DAY_SECONDS,
    "albums": DAY_SECONDS,
    "charts": DAY_SECONDS,
}


def state_path() -> str:
    configured = os.environ.get("DISCOVER_STATE_PATH", "").strip()
    if configured:
        return configured
    return os.path.join(os.getcwd(), ".discover_state.json")


def cache_path() -> str:
    configured = os.environ.get("DISCOVER_CACHE_PATH", "").strip()
    if configured:
        return configured
    return os.path.join(os.getcwd(), ".discover_cache.json")


# ---------------------------------------------------------------------------
# Persistent state: preferences, the current suggestion batch, feedback
# (dismissed albums, blocked artists) and every album added from Discover.
# All read-modify-write goes through _mutate_state under one lock, because the
# scheduler, add jobs and request threads all touch the same file.
# ---------------------------------------------------------------------------

_STATE_LOCK = threading.RLock()


def _default_state() -> dict[str, Any]:
    return {
        "preferences": dict(DEFAULT_PREFERENCES),
        "last_mountpoint": "",
        "suggestions": {"generated_at": 0, "temperature": None, "items": []},
        "dismissed_albums": [],
        "blocked_artists": {},
        "albums": {},
    }


def _load_state() -> dict[str, Any]:
    data = _read_json_file(state_path())
    state = _default_state()
    if not isinstance(data, dict):
        return state

    state["preferences"] = _normalize_preferences(data.get("preferences"))
    state["last_mountpoint"] = str(data.get("last_mountpoint", "") or "")

    suggestions = data.get("suggestions")
    if isinstance(suggestions, dict) and isinstance(suggestions.get("items"), list):
        state["suggestions"] = {
            "generated_at": float(suggestions.get("generated_at") or 0),
            "temperature": suggestions.get("temperature"),
            "items": [item for item in suggestions["items"] if isinstance(item, dict)],
        }

    dismissed = data.get("dismissed_albums")
    if isinstance(dismissed, list):
        state["dismissed_albums"] = [str(item) for item in dismissed]

    blocked = data.get("blocked_artists")
    if isinstance(blocked, dict):
        state["blocked_artists"] = {str(key): str(value) for key, value in blocked.items()}

    albums = data.get("albums")
    if isinstance(albums, dict):
        state["albums"] = {str(key): value for key, value in albums.items() if isinstance(value, dict)}

    return state


def _mutate_state(mutator: Callable[[dict[str, Any]], Any]) -> Any:
    with _STATE_LOCK:
        state = _load_state()
        result = mutator(state)
        _write_json_file_atomic(state_path(), state)
        return result


def _read_state() -> dict[str, Any]:
    with _STATE_LOCK:
        return _load_state()


def _normalize_preferences(raw: Any) -> dict[str, Any]:
    prefs = dict(DEFAULT_PREFERENCES)
    if not isinstance(raw, dict):
        return prefs

    def bounded_float(value: Any, default: float, low: float, high: float) -> float:
        try:
            return min(max(float(value), low), high)
        except (TypeError, ValueError):
            return default

    def bounded_int(value: Any, default: int, low: int, high: int) -> int:
        try:
            return min(max(int(value), low), high)
        except (TypeError, ValueError):
            return default

    prefs["temperature"] = round(bounded_float(raw.get("temperature"), prefs["temperature"], 0.0, 1.0), 2)
    prefs["batch_size"] = bounded_int(raw.get("batch_size"), prefs["batch_size"], 6, 60)
    prefs["trial_days"] = bounded_int(raw.get("trial_days"), prefs["trial_days"], 1, 90)
    prefs["max_active_trials"] = bounded_int(raw.get("max_active_trials"), prefs["max_active_trials"], 1, 50)
    prefs["include_eps"] = bool(raw.get("include_eps", prefs["include_eps"]))
    prefs["weekly_refresh"] = bool(raw.get("weekly_refresh", prefs["weekly_refresh"]))
    quality = str(raw.get("trial_quality", "") or "").strip().upper()
    prefs["trial_quality"] = quality if quality in QUALITY_LABELS else ""
    return prefs


def get_preferences() -> dict[str, Any]:
    return _read_state()["preferences"]


def save_preferences(updates: dict[str, Any]) -> dict[str, Any]:
    quality = updates.get("trial_quality")
    if isinstance(quality, str) and quality.strip() and quality.strip().upper() not in QUALITY_LABELS:
        raise DiscoverError(f"Unsupported quality: {quality}")

    def apply(state: dict[str, Any]) -> dict[str, Any]:
        merged = dict(state["preferences"])
        merged.update({key: value for key, value in updates.items() if key in DEFAULT_PREFERENCES})
        state["preferences"] = _normalize_preferences(merged)
        return state["preferences"]

    return _mutate_state(apply)


def remember_mountpoint(mountpoint: str) -> None:
    """The scheduler expires trials without a request to read the mountpoint
    from, so the last one the UI used is persisted and reused."""
    normalized = (mountpoint or "").strip()
    if not normalized or _read_state()["last_mountpoint"] == normalized:
        return

    def apply(state: dict[str, Any]) -> None:
        state["last_mountpoint"] = normalized

    _mutate_state(apply)


def _scheduler_mountpoint() -> str:
    return _read_state()["last_mountpoint"] or os.environ.get("DEFAULT_MOUNTPOINT", "").strip()


# ---------------------------------------------------------------------------
# Text matching. Deezer is the source of both the suggestions and the tags
# deemix writes, so normalized equality is enough; brackets and " - Remastered"
# suffixes are dropped so "OK Computer (Collector's Edition)" counts as owned.
# ---------------------------------------------------------------------------

# Deezer files best-ofs, live recordings and tribute/charity collections as
# "album"; they make poor introductions to an artist, so they're skipped.
_NOT_A_STUDIO_ALBUM = re.compile(
    r"\b(?:best of|greatest hits|the very best|collection|anthology|essentials?|"
    r"live (?:at|in|from|recordings)|in concert|unplugged|tribute|karaoke|remixes|instrumentals)\b"
    r"|[(\[-]\s*live\b|&\s*friends\b",
    re.IGNORECASE,
)
_FEATURE_SPLIT = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+|[,;]", re.IGNORECASE)


def _norm(value: str) -> str:
    lowered = (value or "").casefold()
    lowered = re.sub(r"\(.*?\)|\[.*?\]", " ", lowered)
    lowered = re.sub(r"[\W_]+", " ", lowered)
    return " ".join(lowered.split())


def _album_key(title: str) -> str:
    return _norm(re.split(r"\s-\s", title or "", maxsplit=1)[0])


def _primary_artist(name: str) -> str:
    return _FEATURE_SPLIT.split(name or "", maxsplit=1)[0].strip()


def _artists_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left == right or left.startswith(f"{right} ") or right.startswith(f"{left} ")


def _is_unknown(value: str) -> bool:
    return not value or value.startswith("Unknown ")


# ---------------------------------------------------------------------------
# Library profile: who you listen to (seeds), what you already own, and which
# genres dominate. Play counts weight the seeds, so an artist with one album
# you play constantly outranks a discography you never touch.
# ---------------------------------------------------------------------------


def _library_profile(tracks: list[dict[str, Any]]) -> dict[str, Any]:
    artists: dict[str, dict[str, Any]] = {}
    owned: dict[str, set[str]] = {}
    genres: Counter[int] = Counter()

    for track in tracks:
        plays = int(track.get("playcount") or 0)
        artist_name = str(track.get("album_artist") or track.get("artist") or "")
        album = str(track.get("album") or "")

        if not _is_unknown(artist_name):
            primary = _primary_artist(artist_name)
            key = _norm(primary)
            if key and key != "various artists":
                entry = artists.setdefault(key, {"name": primary, "plays": 0, "tracks": 0})
                entry["plays"] += plays
                entry["tracks"] += 1

        if not _is_unknown(album):
            album_artists = owned.setdefault(_album_key(album), set())
            for name in (track.get("album_artist"), track.get("artist")):
                if name and not _is_unknown(str(name)):
                    album_artists.add(_norm(_primary_artist(str(name))))

        genre_id = _genre_id_for(str(track.get("genre") or ""))
        if genre_id:
            genres[genre_id] += 1 + plays

    for entry in artists.values():
        entry["weight"] = math.log1p(entry["plays"]) + 0.6 * math.log1p(entry["tracks"])

    return {"artists": artists, "owned": owned, "genres": genres}


def _genre_id_for(genre: str) -> int | None:
    lowered = genre.casefold()
    if not lowered:
        return None
    for keyword, genre_id in _GENRE_KEYWORDS:
        if keyword in lowered:
            return genre_id
    return None


def _is_owned(title: str, artist: str, owned: dict[str, set[str]]) -> bool:
    album_artists = owned.get(_album_key(title))
    if not album_artists:
        return False
    artist_key = _norm(_primary_artist(artist))
    return any(_artists_match(artist_key, candidate) for candidate in album_artists)


# ---------------------------------------------------------------------------
# Deezer public API. Related artists, discographies and charts need no ARL.
# Lookups are cached on disk and throttled under Deezer's 50 requests / 5 s.
# ---------------------------------------------------------------------------


class _DeezerLookup:
    _MIN_INTERVAL_SECONDS = 0.12

    def __init__(self) -> None:
        from deezer import Deezer

        self.api = Deezer().api
        self.cache = _load_cache()
        self.last_call = 0.0

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        wait = self._MIN_INTERVAL_SECONDS - (time.monotonic() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        self.last_call = time.monotonic()
        try:
            return fn(*args, **kwargs)
        except Exception:
            return None

    def _cached(self, bucket: str, key: str, fetch: Callable[[], Any]) -> Any:
        entries = self.cache.setdefault(bucket, {})
        entry = entries.get(key)
        if isinstance(entry, dict) and time.time() - float(entry.get("at", 0)) < _CACHE_TTL_SECONDS[bucket]:
            return entry.get("value")
        value = fetch()
        if value is not None:
            entries[key] = {"at": time.time(), "value": value}
        return value

    def artist_id(self, name: str) -> str:
        def fetch() -> str | None:
            data = self._call(self.api.search_artist, name, limit=5)
            if data is None:
                return None
            wanted = _norm(name)
            results = data.get("data", [])
            for item in results:
                if _norm(item.get("name", "")) == wanted:
                    return str(item.get("id", ""))
            for item in results:
                if _artists_match(_norm(item.get("name", "")), wanted):
                    return str(item.get("id", ""))
            return ""

        return self._cached("artist_ids", _norm(name), fetch) or ""

    def related(self, artist_id: str) -> list[dict[str, str]]:
        def fetch() -> list[dict[str, str]] | None:
            data = self._call(self.api.get_artist_related, artist_id, limit=20)
            if data is None:
                return None
            return [
                {"id": str(item.get("id", "")), "name": str(item.get("name", ""))}
                for item in data.get("data", [])
                if item.get("id")
            ]

        return self._cached("related", artist_id, fetch) or []

    def albums(self, artist_id: str) -> list[dict[str, Any]]:
        def fetch() -> list[dict[str, Any]] | None:
            data = self._call(self.api.get_artist_albums, artist_id, limit=100)
            if data is None:
                return None
            return [
                {
                    "id": str(item.get("id", "")),
                    "title": str(item.get("title", "")),
                    "cover_url": str(item.get("cover_medium") or item.get("cover") or ""),
                    "record_type": str(item.get("record_type", "")),
                    "release_date": str(item.get("release_date", "")),
                    "fans": int(item.get("fans") or 0),
                }
                for item in data.get("data", [])
                if item.get("id")
            ]

        return self._cached("albums", artist_id, fetch) or []

    def chart_albums(self, genre_id: int) -> list[dict[str, Any]]:
        def fetch() -> list[dict[str, Any]] | None:
            data = self._call(self.api.get_chart_albums, genre_id, limit=50)
            if data is None:
                return None
            return [
                {
                    "id": str(item.get("id", "")),
                    "title": str(item.get("title", "")),
                    "cover_url": str(item.get("cover_medium") or item.get("cover") or ""),
                    "record_type": str(item.get("record_type", "")),
                    "release_date": "",
                    "artist": str((item.get("artist") or {}).get("name", "")),
                    "artist_id": str((item.get("artist") or {}).get("id", "")),
                }
                for item in data.get("data", [])
                if item.get("id")
            ]

        return self._cached("charts", str(genre_id), fetch) or []

    def save(self) -> None:
        _write_json_file_atomic(cache_path(), self.cache)


def _load_cache() -> dict[str, Any]:
    data = _read_json_file(cache_path())
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Recommendation engine.
#
# Every candidate artist sits at a distance from the library: 0 = an artist you
# own, 1 = related to one, 2 = related to a related artist, 3 = a genre chart.
# Temperature moves the preferred distance from 0 to 3 and widens the random
# jitter, so the slider is a smooth dial between "more of the same" and
# "something new", not a hard filter.
# ---------------------------------------------------------------------------


def _distance_affinity(distance: int, temperature: float) -> float:
    target = 3.0 * temperature
    return math.exp(-((distance - target) ** 2) / (2 * 0.75**2))


def _recommend(
    lookup: _DeezerLookup,
    profile: dict[str, Any],
    state: dict[str, Any],
    temperature: float,
    rng: random.Random,
    progress: Callable[[str], None],
) -> list[dict[str, Any]]:
    prefs = state["preferences"]
    batch_size = prefs["batch_size"]
    allowed_types = {"album", "ep"} if prefs["include_eps"] else {"album"}
    blocked = set(state["blocked_artists"].keys())
    # Anything already tried (kept, expired, removed) stays out of new batches;
    # only a failed add is allowed to come back.
    excluded_albums = set(state["dismissed_albums"]) | {
        album_id for album_id, record in state["albums"].items() if record.get("status") != "failed"
    }
    expired_artists = {
        str(record.get("artist_id", ""))
        for record in state["albums"].values()
        if record.get("status") == "expired"
    }
    owned = profile["owned"]
    library_artists = set(profile["artists"].keys())

    # --- Seeds: high temperature samples deeper into the artist list, so the
    # long tail of the library gets a say instead of only the top artists.
    ranked = sorted(profile["artists"].values(), key=lambda entry: entry["weight"], reverse=True)
    pool = ranked[: max(1, int(20 + 60 * temperature))]
    seed_count = min(len(pool), int(12 + 12 * temperature))
    flatten = 1.0 - 0.7 * temperature
    seeds: list[dict[str, Any]] = []
    remaining = list(pool)
    while remaining and len(seeds) < seed_count:
        weights = [max(entry["weight"], 0.01) ** flatten for entry in remaining]
        seeds.append(remaining.pop(rng.choices(range(len(remaining)), weights=weights)[0]))

    progress("Finding your artists on Deezer...")
    owned_artist_ids: set[str] = set()
    seed_ids: list[tuple[str, dict[str, Any]]] = []
    for entry in seeds:
        artist_id = lookup.artist_id(entry["name"])
        if artist_id:
            seed_ids.append((artist_id, entry))
            owned_artist_ids.add(artist_id)

    # candidate artist id -> {name, distance, score, reason}
    candidates: dict[str, dict[str, Any]] = {}

    def offer(artist_id: str, name: str, distance: int, score: float, reason: str) -> None:
        if not artist_id or artist_id in blocked:
            return
        # Library artists only appear as "more from"; one that wasn't sampled
        # as a seed this round shouldn't come back as "similar to".
        if distance > 0 and (artist_id in owned_artist_ids or _norm(name) in library_artists):
            return
        current = candidates.get(artist_id)
        if current is None or current["distance"] > distance:
            candidates[artist_id] = {"name": name, "distance": distance, "score": score, "reason": reason}
        elif current["distance"] == distance:
            current["score"] += score

    for artist_id, entry in seed_ids:
        plays = entry["plays"]
        reason = (
            f"More from {entry['name']} · {plays} play{'s' if plays != 1 else ''} on your iPod"
            if plays
            else f"More from {entry['name']}, already in your library"
        )
        offer(artist_id, entry["name"], 0, entry["weight"], reason)

    progress("Exploring similar artists...")
    for artist_id, entry in seed_ids:
        for rank, related in enumerate(lookup.related(artist_id)):
            offer(
                related["id"],
                related["name"],
                1,
                entry["weight"] / (1 + 0.15 * rank),
                f"Similar to {entry['name']}",
            )

    if temperature >= 0.25:
        hop_one = sorted(
            ((artist_id, info) for artist_id, info in candidates.items() if info["distance"] == 1),
            key=lambda pair: pair[1]["score"],
            reverse=True,
        )[: int(4 + 8 * temperature)]
        for parent_id, parent in hop_one:
            seed_name = parent["reason"].removeprefix("Similar to ")
            for rank, related in enumerate(lookup.related(parent_id)):
                offer(
                    related["id"],
                    related["name"],
                    2,
                    parent["score"] * 0.5 / (1 + 0.15 * rank),
                    f"Similar to {parent['name']}, via {seed_name}",
                )

    # Normalize within each distance so a big library's raw seed weights don't
    # drown out the related-artist scores, then apply temperature and jitter.
    max_by_distance: dict[int, float] = {}
    for info in candidates.values():
        max_by_distance[info["distance"]] = max(max_by_distance.get(info["distance"], 0.0), info["score"])

    jitter = 0.15 + 0.45 * temperature
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for artist_id, info in candidates.items():
        relative = info["score"] / (max_by_distance[info["distance"]] or 1.0)
        final = math.sqrt(relative) * _distance_affinity(info["distance"], temperature)
        final *= math.exp(rng.gauss(0, jitter))
        if artist_id in expired_artists:
            final *= 0.6
        scored.append((final, artist_id, info))
    scored.sort(key=lambda row: row[0], reverse=True)

    chart_share = _distance_affinity(3, temperature)
    chart_target = int(round(batch_size * chart_share / (chart_share + 1.0))) if temperature >= 0.5 else 0

    picks: list[dict[str, Any]] = []
    picked_artists: set[str] = set()
    now_date = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 180 * DAY_SECONDS))

    def take(album: dict[str, Any], artist_id: str, artist_name: str, distance: int, reason: str) -> None:
        picks.append(
            {
                "id": album["id"],
                "title": album["title"],
                "artist": artist_name,
                "artist_id": artist_id,
                "cover_url": album["cover_url"],
                "record_type": album["record_type"],
                "release_date": album.get("release_date", ""),
                "distance": distance,
                "reason": reason,
            }
        )
        picked_artists.add(artist_id)

    artist_target = batch_size - chart_target
    lookups_left = int(batch_size * 1.6) + 4
    for _score, artist_id, info in scored:
        if len(picks) >= artist_target or lookups_left <= 0:
            break
        lookups_left -= 1
        progress(f"Picking albums ({len(picks)}/{batch_size})...")

        options = [
            album
            for album in lookup.albums(artist_id)
            if album["record_type"] in allowed_types
            and not _NOT_A_STUDIO_ALBUM.search(album["title"])
            and album["id"] not in excluded_albums
            and not _is_owned(album["title"], info["name"], owned)
        ]
        if not options:
            continue

        # Low temperature favours the artist's best-known album; high
        # temperature flattens that so deep cuts surface too.
        weights = [(album["fans"] + 1) ** (1.5 - temperature) for album in options]
        album = options[rng.choices(range(len(options)), weights=weights)[0]]
        reason = info["reason"]
        if info["distance"] == 0 and album["release_date"] >= now_date:
            reason = f"New release from {info['name']}"
        take(album, artist_id, info["name"], info["distance"], reason)

    if chart_target or len(picks) < batch_size:
        # Charts fill the high-temperature share and also back-fill a batch
        # that ran short (a tiny library, or most albums already owned).
        progress("Checking genre charts...")
        genre_ids = [genre_id for genre_id, _count in profile["genres"].most_common(3)] or [0]
        chart_rows: list[tuple[int, dict[str, Any]]] = []
        for genre_id in genre_ids:
            chart_rows.extend((genre_id, album) for album in lookup.chart_albums(genre_id))
        rng.shuffle(chart_rows)
        for genre_id, album in chart_rows:
            if len(picks) >= batch_size:
                break
            artist_id = album["artist_id"]
            if (
                not artist_id
                or artist_id in blocked
                or artist_id in picked_artists
                or artist_id in owned_artist_ids
                or _norm(album["artist"]) in library_artists
                or album["id"] in excluded_albums
                or album["record_type"] not in allowed_types
                or _NOT_A_STUDIO_ALBUM.search(album["title"])
                or _is_owned(album["title"], album["artist"], owned)
            ):
                continue
            label = _GENRE_LABELS.get(genre_id, "")
            take(album, artist_id, album["artist"], 3, f"Popular in {label}" if label else "Popular on Deezer")

    rng.shuffle(picks)
    return picks


# Only one batch generates at a time; the UI polls the job for progress.
_GENERATION_LOCK = threading.Lock()
_GENERATION: dict[str, Any] = {"status": "idle", "message": "", "started_at": 0.0, "error": ""}


def _set_generation(**fields: Any) -> None:
    with _GENERATION_LOCK:
        _GENERATION.update(fields)


def generation_status() -> dict[str, Any]:
    with _GENERATION_LOCK:
        return dict(_GENERATION)


def start_generation(mountpoint: str, temperature: float | None = None) -> None:
    normalized = (mountpoint or "").strip()
    if not normalized:
        raise DiscoverError("Connect an iPod first — suggestions are based on its library.")

    with _GENERATION_LOCK:
        if _GENERATION["status"] == "running":
            return
        _GENERATION.update(status="running", message="Reading your iPod library...", started_at=time.time(), error="")

    if temperature is not None:
        save_preferences({"temperature": temperature})
    remember_mountpoint(normalized)
    thread = threading.Thread(target=_run_generation, args=(normalized,), daemon=True)
    thread.start()


def _run_generation(mountpoint: str) -> None:
    try:
        library = load_library(mountpoint)
        profile = _library_profile(library.get("tracks", []))
        if not profile["artists"] and not profile["genres"]:
            raise DiscoverError("Your iPod library is empty — add some music first so Discover has something to go on.")

        state = _read_state()
        temperature = state["preferences"]["temperature"]
        lookup = _DeezerLookup()
        try:
            items = _recommend(
                lookup,
                profile,
                state,
                temperature,
                random.Random(),
                lambda message: _set_generation(message=message),
            )
        finally:
            lookup.save()

        def apply(current: dict[str, Any]) -> None:
            current["suggestions"] = {"generated_at": time.time(), "temperature": temperature, "items": items}

        _mutate_state(apply)
        _set_generation(status="idle", message="", error="")
    except (DiscoverError, GpodError) as exc:
        _set_generation(status="error", message="", error=str(exc))
    except Exception as exc:
        _set_generation(status="error", message="", error=f"Could not build suggestions: {exc}")


def get_suggestions() -> dict[str, Any]:
    state = _read_state()
    hidden = set(state["dismissed_albums"]) | set(state["albums"].keys())
    blocked = set(state["blocked_artists"].keys())
    items = [
        item
        for item in state["suggestions"]["items"]
        if item.get("id") not in hidden and item.get("artist_id") not in blocked
    ]
    return {
        "generated_at": state["suggestions"]["generated_at"],
        "temperature": state["suggestions"]["temperature"],
        "items": items,
        "generation": generation_status(),
    }


def dismiss_album(album_id: str) -> None:
    def apply(state: dict[str, Any]) -> None:
        if album_id not in state["dismissed_albums"]:
            state["dismissed_albums"].append(album_id)

    _mutate_state(apply)


def block_artist(artist_id: str, name: str) -> None:
    if not artist_id:
        raise DiscoverError("Artist id is required.")

    def apply(state: dict[str, Any]) -> None:
        state["blocked_artists"][artist_id] = name or artist_id

    _mutate_state(apply)


def unblock_artist(artist_id: str) -> None:
    def apply(state: dict[str, Any]) -> None:
        state["blocked_artists"].pop(artist_id, None)

    _mutate_state(apply)


def list_blocked_artists() -> list[dict[str, str]]:
    blocked = _read_state()["blocked_artists"]
    return [{"id": artist_id, "name": name} for artist_id, name in sorted(blocked.items(), key=lambda kv: kv[1].casefold())]


# ---------------------------------------------------------------------------
# Albums added from Discover. A trial must be removable later without touching
# anything else on the device, so each add records exactly which tracks it put
# there: the library is read before and after the download, and only tracks
# that are new *and* carry this album's tags are attributed to it.
# ---------------------------------------------------------------------------

# Adds run one at a time so two albums landing together can't be attributed
# to each other by the before/after comparison.
_ADD_SERIAL_LOCK = threading.Lock()
_PROGRESS_LOCK = threading.Lock()
_PROGRESS: dict[str, dict[str, Any]] = {}


def _set_progress(album_id: str, **fields: Any) -> None:
    with _PROGRESS_LOCK:
        _PROGRESS.setdefault(album_id, {}).update(fields)


def _clear_progress(album_id: str) -> None:
    with _PROGRESS_LOCK:
        _PROGRESS.pop(album_id, None)


def list_albums() -> dict[str, Any]:
    state = _read_state()
    with _PROGRESS_LOCK:
        progress = {key: dict(value) for key, value in _PROGRESS.items()}
    albums = []
    for album_id, record in state["albums"].items():
        public = {key: value for key, value in record.items() if key != "tracks"}
        public["id"] = album_id
        public["track_count"] = len(record.get("tracks", []))
        public["progress"] = progress.get(album_id)
        albums.append(public)
    albums.sort(key=lambda record: record.get("updated_at", 0), reverse=True)
    return {"now": time.time(), "albums": albums}


def _check_can_add(mountpoint: str) -> None:
    if not get_deemix_status()["arl_configured"]:
        raise DiscoverError("Deezer ARL token is not configured. Add it in Settings.")
    if not os.path.exists(mountpoint):
        raise DiscoverError(f"Mountpoint does not exist: {mountpoint}")
    try:
        if shutil.disk_usage(mountpoint).free < MIN_FREE_BYTES:
            raise DiscoverError("The iPod has less than 1 GB free. Remove something before adding more.")
    except OSError:
        pass


def _effective_quality(mode: str, requested: str | None, prefs: dict[str, Any]) -> str:
    normalized = (requested or "").strip().upper()
    if normalized:
        if normalized not in QUALITY_LABELS:
            raise DiscoverError(f"Unsupported quality: {requested}")
        return normalized
    if mode == "trial" and prefs["trial_quality"]:
        return prefs["trial_quality"]
    try:
        return load_deemix_config()["default_quality"]
    except Exception:
        return DEFAULT_QUALITY


def _record_key(item_type: str, deezer_id: str) -> str:
    # Deezer album and track ids are separate namespaces, so tracks get a
    # prefix; albums keep the bare id that suggestions are matched against.
    return deezer_id if item_type == "album" else f"{item_type}-{deezer_id}"


def add_album(
    album: dict[str, Any],
    mode: str,
    mountpoint: str,
    quality: str | None = None,
    item_type: str = "album",
) -> dict[str, Any]:
    """Add an album — or a single track, from the Deemix page — permanently or
    on a trial. `album["id"]` is the Deezer id of that album or track."""
    deezer_id = str(album.get("id", "") or "").strip()
    normalized_mountpoint = (mountpoint or "").strip()
    if not deezer_id:
        raise DiscoverError("Album id is required.")
    if item_type not in {"album", "track"}:
        raise DiscoverError("Only albums and tracks can be added this way.")
    album_id = _record_key(item_type, deezer_id)
    if mode not in {"trial", "permanent"}:
        raise DiscoverError("Mode must be 'trial' or 'permanent'.")
    if not normalized_mountpoint:
        raise DiscoverError("Connect an iPod first — Discover adds albums straight to the device.")
    _check_can_add(normalized_mountpoint)
    remember_mountpoint(normalized_mountpoint)

    def apply(state: dict[str, Any]) -> dict[str, Any]:
        prefs = state["preferences"]
        existing = state["albums"].get(album_id)
        if existing and existing.get("status") not in {"failed", "removed", "expired"}:
            raise DiscoverError(f"That {item_type} is already on your iPod from Discover.")
        if mode == "trial":
            active = sum(
                1
                for record in state["albums"].values()
                if record.get("mode") == "trial" and record.get("status") in ACTIVE_STATUSES
            )
            if active >= prefs["max_active_trials"]:
                raise DiscoverError(
                    f"You already have {active} trial(s) running (limit {prefs['max_active_trials']}). "
                    "Keep or remove one first."
                )
        now = time.time()
        record = {
            "type": item_type,
            "deezer_id": deezer_id,
            "title": str(album.get("title", "") or ""),
            "album": str(album.get("album", "") or ""),
            "artist": str(album.get("artist", "") or ""),
            "artist_id": str(album.get("artist_id", "") or ""),
            "cover_url": str(album.get("cover_url", "") or ""),
            "reason": str(album.get("reason", "") or ""),
            "mode": mode,
            "status": "pending",
            "quality": _effective_quality(mode, quality, prefs),
            "mountpoint": normalized_mountpoint,
            "created_at": now,
            "updated_at": now,
            "added_at": 0,
            "expires_at": 0,
            "tracks": [],
            "message": "Queued",
        }
        state["albums"][album_id] = record
        return record

    record = _mutate_state(apply)
    _set_progress(album_id, status="queued", percent=0)
    thread = threading.Thread(target=_run_add, args=(album_id, []), daemon=True)
    thread.start()
    return record


def _update_album(album_id: str, **fields: Any) -> dict[str, Any] | None:
    def apply(state: dict[str, Any]) -> dict[str, Any] | None:
        record = state["albums"].get(album_id)
        if record is None:
            return None
        record.update(fields)
        record["updated_at"] = time.time()
        return dict(record)

    return _mutate_state(apply)


def _get_album(album_id: str) -> dict[str, Any]:
    record = _read_state()["albums"].get(album_id)
    if record is None:
        raise DiscoverError("Album not found.")
    return record


def _run_add(album_id: str, replaces: list[dict[str, Any]]) -> None:
    """Download an album, attribute the new tracks to it, and settle the
    record as a trial or a kept album. `replaces` holds the tracks of an
    earlier trial copy being upgraded; they are removed only once the new copy
    is safely on the device."""
    _set_progress(album_id, status="queued", percent=0)
    with _ADD_SERIAL_LOCK:
        try:
            _execute_add(album_id, replaces)
        except Exception as exc:
            _update_album(album_id, status="failed", message=f"Add failed: {exc}")
        finally:
            _clear_progress(album_id)


def _execute_add(album_id: str, replaces: list[dict[str, Any]]) -> None:
    record = _get_album(album_id)
    mountpoint = record["mountpoint"]

    _set_progress(album_id, status="downloading", percent=0)
    try:
        before = load_library(mountpoint)
    except GpodError as exc:
        _update_album(album_id, status="failed", message=f"Could not read the iPod: {exc}")
        return
    before_paths = {str(track.get("ipod_path") or "") for track in before.get("tracks", [])}
    resolved_mountpoint = str(before.get("mountpoint") or mountpoint)

    job_id = start_download_job(
        [
            {
                "id": record.get("deezer_id") or album_id,
                "type": record.get("type", "album"),
                "title": record["title"],
                "artist": record["artist"],
            }
        ],
        record["quality"],
        resolved_mountpoint,
    )
    _update_album(album_id, job_id=job_id, message="Downloading")

    job: dict[str, Any] | None = None
    while True:
        job = get_deemix_job(job_id)
        if job is None or job["status"] in {"done", "error"}:
            break
        item = job["items"][0] if job["items"] else {}
        _set_progress(
            album_id,
            status="copying" if item.get("status") == "copying" else "downloading",
            percent=int(item.get("progress") or 0),
        )
        time.sleep(1.0)

    if job is None:
        _update_album(album_id, status="failed", message="The download job disappeared before it finished.")
        return
    item = job["items"][0] if job["items"] else {}
    if job["status"] == "error" or item.get("status") == "error" or not job.get("added_to_ipod_count"):
        message = item.get("error") or job.get("ipod_message") or job.get("message") or "Download failed."
        _update_album(album_id, status="failed", message=message)
        return

    _set_progress(album_id, status="copying", percent=100)
    after = load_library(resolved_mountpoint)
    artist_key = _norm(_primary_artist(record["artist"]))
    new_tracks = [
        track
        for track in after.get("tracks", [])
        if track.get("ipod_path") and str(track.get("ipod_path")) not in before_paths
    ]
    added = _attribute_new_tracks(record, new_tracks, artist_key)

    if replaces:
        _delete_recorded_tracks(resolved_mountpoint, replaces)

    now = time.time()
    if record["mode"] == "trial" and added:
        days = _read_state()["preferences"]["trial_days"]
        _update_album(
            album_id,
            status="trial",
            tracks=added,
            mountpoint=resolved_mountpoint,
            added_at=now,
            expires_at=now + days * DAY_SECONDS,
            message=f"On trial for {days} day(s).",
        )
    elif record["mode"] == "trial":
        # Without the track list there's nothing safe to delete later, so the
        # album stays — say so rather than pretend it's on a timer.
        _update_album(
            album_id,
            status="kept",
            mode="permanent",
            tracks=[],
            mountpoint=resolved_mountpoint,
            added_at=now,
            expires_at=0,
            message="Added, but its tracks couldn't be identified on the iPod, so it was kept permanently.",
        )
    else:
        _update_album(
            album_id,
            status="kept",
            tracks=added,
            mountpoint=resolved_mountpoint,
            added_at=record.get("added_at") or now,
            expires_at=0,
            message=f"Added {len(added) or job.get('added_to_ipod_count', 0)} track(s) permanently.",
        )


def _artist_of(track: dict[str, Any]) -> str:
    return _norm(_primary_artist(str(track.get("album_artist") or track.get("artist") or "")))


def _attribute_new_tracks(
    record: dict[str, Any], new_tracks: list[dict[str, Any]], artist_key: str
) -> list[dict[str, Any]]:
    """Pick out the tracks this add put on the device from everything that is
    new since the "before" snapshot."""
    if record.get("type") == "track":
        # A single song: same title and artist (Deezer's tags on both sides).
        title_key = _norm(record["title"])
        return [
            _track_fingerprint(t)
            for t in new_tracks
            if _norm(str(t.get("title") or "")) == title_key
            and _artists_match(_norm(_primary_artist(str(t.get("artist") or ""))), artist_key)
        ][:1]

    title_key = _album_key(record["title"])
    # Album tag first. Only when nothing carries it (Deezer retitled the
    # release after the fact) fall back to the artist — never both, so an
    # unrelated upload landing at the same moment isn't swept into the trial.
    added = [_track_fingerprint(t) for t in new_tracks if _album_key(str(t.get("album") or "")) == title_key]
    if not added:
        added = [_track_fingerprint(t) for t in new_tracks if _artists_match(_artist_of(t), artist_key)]
    return added


def _track_fingerprint(track: dict[str, Any]) -> dict[str, Any]:
    return {
        "ipod_path": str(track.get("ipod_path") or ""),
        "title": str(track.get("title") or ""),
        "album": str(track.get("album") or ""),
        "artist": str(track.get("artist") or ""),
    }


def _delete_recorded_tracks(mountpoint: str, recorded: list[dict[str, Any]], library: dict[str, Any] | None = None) -> int:
    """Delete the recorded tracks that are still on the device. A path only
    counts when its title and album still match what was recorded, so a
    different iPod on the same mountpoint (whose file names can collide) is
    never touched. Returns the play count the tracks had, for history."""
    if not recorded:
        return 0
    current = library if library is not None else load_library(mountpoint)
    by_path = {str(track.get("ipod_path") or ""): track for track in current.get("tracks", [])}

    targets: list[str] = []
    plays = 0
    for fingerprint in recorded:
        track = by_path.get(fingerprint["ipod_path"])
        if track is None:
            continue
        if _norm(str(track.get("title") or "")) != _norm(fingerprint["title"]):
            continue
        if _norm(str(track.get("album") or "")) != _norm(fingerprint["album"]):
            continue
        targets.append(fingerprint["ipod_path"])
        plays += int(track.get("playcount") or 0)

    if targets:
        delete_tracks(str(current.get("mountpoint") or mountpoint), targets)
    return plays


def keep_album(album_id: str, upgrade: bool = False, quality: str | None = None) -> dict[str, Any]:
    record = _get_album(album_id)
    if record.get("status") != "trial":
        raise DiscoverError("Only an album on trial can be kept.")

    if not upgrade:
        updated = _update_album(album_id, status="kept", mode="permanent", expires_at=0, message="Kept permanently.")
        return updated or record

    # Re-download in better quality, then swap the trial copy out.
    target_quality = (quality or "").strip().upper() or _effective_quality("permanent", None, get_preferences())
    if target_quality not in QUALITY_LABELS:
        raise DiscoverError(f"Unsupported quality: {quality}")
    _check_can_add(record["mountpoint"])
    replaces = list(record.get("tracks", []))
    # While the upgrade runs, the old copy is no longer on a timer: if the
    # download fails the record ends up "failed" with the trial copy intact,
    # so it falls back to a plain keep instead.
    _update_album(
        album_id,
        status="pending",
        mode="permanent",
        quality=target_quality,
        expires_at=0,
        message=f"Upgrading to {target_quality}",
    )
    thread = threading.Thread(target=_run_upgrade, args=(album_id, replaces), daemon=True)
    thread.start()
    return _get_album(album_id)


def _run_upgrade(album_id: str, replaces: list[dict[str, Any]]) -> None:
    _run_add(album_id, replaces)
    record = _read_state()["albums"].get(album_id)
    if record and record.get("status") == "failed":
        _update_album(
            album_id,
            status="kept",
            tracks=replaces,
            message=f"Kept the trial copy — upgrading failed: {record.get('message', '')}",
        )


def extend_album(album_id: str, days: int) -> dict[str, Any]:
    try:
        days_value = min(max(int(days), 1), 90)
    except (TypeError, ValueError):
        raise DiscoverError("Days must be a number.")
    record = _get_album(album_id)
    if record.get("status") != "trial":
        raise DiscoverError("Only an album on trial can be extended.")
    base = max(float(record.get("expires_at") or 0), time.time())
    return _update_album(album_id, expires_at=base + days_value * DAY_SECONDS) or record


def remove_album(album_id: str, mountpoint: str | None = None) -> dict[str, Any]:
    record = _get_album(album_id)
    if record.get("status") == "pending":
        raise DiscoverError("This album is still being added. Wait for it to finish.")
    if record.get("status") in {"trial", "kept"}:
        target = (mountpoint or "").strip() or record.get("mountpoint", "")
        try:
            plays = _delete_recorded_tracks(target, record.get("tracks", []))
        except GpodError as exc:
            raise DiscoverError(f"Could not remove the album from the iPod: {exc}") from exc
        return _update_album(album_id, status="removed", expires_at=0, plays=plays, message="Removed from the iPod.") or record
    return record


def retry_album(album_id: str, mountpoint: str) -> dict[str, Any]:
    record = _get_album(album_id)
    if record.get("status") != "failed":
        raise DiscoverError("Only a failed add can be retried.")
    album = {key: record.get(key, "") for key in ("title", "album", "artist", "artist_id", "cover_url", "reason")}
    album["id"] = record.get("deezer_id") or album_id
    return add_album(
        album,
        record.get("mode", "trial"),
        mountpoint or record.get("mountpoint", ""),
        record.get("quality"),
        record.get("type", "album"),
    )


def forget_album(album_id: str) -> None:
    """Drop a finished record from history so the album can be suggested again."""

    def apply(state: dict[str, Any]) -> None:
        record = state["albums"].get(album_id)
        if record is None:
            return
        if record.get("status") in ACTIVE_STATUSES:
            raise DiscoverError("Remove or keep the album before clearing it from history.")
        state["albums"].pop(album_id, None)

    _mutate_state(apply)


# ---------------------------------------------------------------------------
# Expiry. Due trials are deleted silently the next time the iPod is readable:
# from the scheduler tick, or right after the UI reports a mountpoint.
# ---------------------------------------------------------------------------

_SWEEP_LOCK = threading.Lock()
_SWEEP_RETRY_SECONDS = 10 * 60
_last_failed_sweep = 0.0


def _due_trials(state: dict[str, Any], now: float) -> list[str]:
    return [
        album_id
        for album_id, record in state["albums"].items()
        if record.get("status") == "trial" and 0 < float(record.get("expires_at") or 0) <= now
    ]


def _ipod_present(mountpoint: str) -> bool:
    if not mountpoint or not os.path.exists(mountpoint):
        return False
    return _has_itunesdb_under_root(resolve_ipod_root(mountpoint))


def sweep_expired(mountpoint: str | None = None, force: bool = False) -> int:
    """Delete every trial whose time is up. Returns how many expired."""
    global _last_failed_sweep
    if not _SWEEP_LOCK.acquire(blocking=False):
        return 0
    try:
        now = time.time()
        due = _due_trials(_read_state(), now)
        if not due:
            return 0
        if not force and now - _last_failed_sweep < _SWEEP_RETRY_SECONDS:
            return 0

        target = (mountpoint or "").strip() or _scheduler_mountpoint()
        if not _ipod_present(target):
            return 0
        try:
            library = load_library(target)
        except GpodError:
            _last_failed_sweep = now
            return 0

        expired = 0
        for album_id in due:
            record = _read_state()["albums"].get(album_id)
            if not record or record.get("status") != "trial":
                continue
            try:
                plays = _delete_recorded_tracks(target, record.get("tracks", []), library)
            except GpodError:
                _last_failed_sweep = now
                continue
            _update_album(album_id, status="expired", expires_at=0, plays=plays, expired_at=now, message="Trial ended.")
            expired += 1
        return expired
    finally:
        _SWEEP_LOCK.release()


def sweep_in_background(mountpoint: str) -> None:
    if _due_trials(_read_state(), time.time()):
        threading.Thread(target=sweep_expired, args=(mountpoint, True), daemon=True).start()


_SCHEDULER_LOCK = threading.Lock()
_SCHEDULER_STARTED = False
_SCHEDULER_TICK_SECONDS = 60


def ensure_scheduler() -> None:
    global _SCHEDULER_STARTED
    with _SCHEDULER_LOCK:
        if _SCHEDULER_STARTED:
            return
        _SCHEDULER_STARTED = True
    thread = threading.Thread(target=_scheduler_loop, daemon=True)
    thread.start()


def _scheduler_loop() -> None:
    while True:
        time.sleep(_SCHEDULER_TICK_SECONDS)
        try:
            sweep_expired()
        except Exception:
            pass
        try:
            _refresh_if_due()
        except Exception:
            pass


def _refresh_if_due() -> None:
    state = _read_state()
    if not state["preferences"]["weekly_refresh"]:
        return
    if time.time() - state["suggestions"]["generated_at"] < WEEK_SECONDS:
        return
    if generation_status()["status"] == "running":
        return
    mountpoint = _scheduler_mountpoint()
    if not _ipod_present(mountpoint):
        return
    start_generation(mountpoint)


def _read_json_file(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _write_json_file_atomic(path: str, data: Any) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".tmp_discover_", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
