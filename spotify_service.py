from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid as uuid_lib
from collections import OrderedDict
from typing import Any

from deemix_service import (
    DEFAULT_QUALITY,
    QUALITY_LABELS,
    DeemixError,
    connect_deezer,
    get_job as get_deemix_job,
    load_config as load_deemix_config,
    start_download_job,
)
from ipod_service import (
    GpodError,
    add_tracks_to_playlist as add_tracks_to_ipod_playlist,
    create_playlist as create_ipod_playlist,
    delete_playlist as delete_ipod_playlist,
    load_library,
    remove_tracks_from_playlist as remove_tracks_from_ipod_playlist,
)


class SpotifyError(RuntimeError):
    pass


# Tracks are downloaded in batches so that a long playlist reaches the iPod
# incrementally instead of staging hundreds of files before the first copy.
DOWNLOAD_BATCH_SIZE = 20
DEFAULT_CHECK_INTERVAL_MINUTES = 60
PLAYLIST_CACHE_TTL_SECONDS = 300

# Spotify ids are 22-character base62. Requiring a plausible length keeps a
# truncated or placeholder link (".../playlist/YOUR_ID_HERE" stops at the
# underscore) from being sent to the API as a nonsense id.
_PLAYLIST_ID_PATTERN = re.compile(r"playlist[/:]([A-Za-z0-9]{16,})")
# "Copy link" on mobile hands out a short redirect that carries no playlist id.
_SHORT_LINK_HOSTS = ("spotify.link", "spotify.app.link")


def config_path() -> str:
    configured = os.environ.get("SPOTIFY_CONFIG_PATH", "").strip()
    if configured:
        return configured
    return os.path.join(os.getcwd(), ".spotify_config.json")


def playlists_path() -> str:
    configured = os.environ.get("SPOTIFY_PLAYLISTS_PATH", "").strip()
    if configured:
        return configured
    return os.path.join(os.getcwd(), ".spotify_playlists.json")


def _default_config() -> dict[str, Any]:
    return {
        "auto_sync_enabled": False,
        "check_interval_minutes": DEFAULT_CHECK_INTERVAL_MINUTES,
        "quality": "",
        "last_mountpoint": "",
    }


def load_config() -> dict[str, Any]:
    data = _read_json_file(config_path())
    merged = _default_config()
    if not isinstance(data, dict):
        return merged

    merged["auto_sync_enabled"] = bool(data.get("auto_sync_enabled", False))

    interval = data.get("check_interval_minutes", DEFAULT_CHECK_INTERVAL_MINUTES)
    try:
        interval_value = int(interval)
    except (TypeError, ValueError):
        interval_value = DEFAULT_CHECK_INTERVAL_MINUTES
    merged["check_interval_minutes"] = max(5, interval_value)

    quality = str(data.get("quality", "") or "").strip().upper()
    if quality in QUALITY_LABELS:
        merged["quality"] = quality

    merged["last_mountpoint"] = str(data.get("last_mountpoint", "") or "")
    return merged


def save_config(updates: dict[str, Any]) -> dict[str, Any]:
    current = load_config()
    merged = dict(current)

    if "auto_sync_enabled" in updates:
        merged["auto_sync_enabled"] = bool(updates.get("auto_sync_enabled"))

    if "check_interval_minutes" in updates:
        try:
            merged["check_interval_minutes"] = max(5, int(updates.get("check_interval_minutes")))
        except (TypeError, ValueError):
            raise SpotifyError("Check interval must be a number of minutes.")

    quality = updates.get("quality")
    if isinstance(quality, str) and quality.strip():
        normalized_quality = quality.strip().upper()
        if normalized_quality not in QUALITY_LABELS:
            raise SpotifyError(f"Unsupported quality: {quality}")
        merged["quality"] = normalized_quality

    _write_json_file_atomic(config_path(), merged)
    return merged


def _remember_mountpoint(mountpoint: str) -> None:
    """Background auto-sync has no request to read the mountpoint from, so the
    last one used from the UI is persisted and reused."""
    normalized = (mountpoint or "").strip()
    if not normalized:
        return
    current = load_config()
    if current["last_mountpoint"] == normalized:
        return
    current["last_mountpoint"] = normalized
    _write_json_file_atomic(config_path(), current)


def effective_quality() -> str:
    quality = load_config()["quality"]
    if quality:
        return quality
    try:
        return load_deemix_config()["default_quality"]
    except Exception:
        return DEFAULT_QUALITY


def get_status() -> dict[str, Any]:
    config = load_config()
    return {
        "enabled": True,
        "auto_sync_enabled": config["auto_sync_enabled"],
        "check_interval_minutes": config["check_interval_minutes"],
        "quality": effective_quality(),
        "last_mountpoint": config["last_mountpoint"],
        "playlist_count": len(_load_playlists()),
    }


def _resolve_short_link(url: str) -> str:
    """Follow a spotify.link redirect to the real open.spotify.com URL. Returns
    the input unchanged if it cannot be resolved, so the caller still reports a
    parse error rather than a network one."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=15) as response:
            final_url = response.geturl()
            if _PLAYLIST_ID_PATTERN.search(final_url):
                return final_url
            body = response.read(200_000).decode("utf-8", "replace")
    except Exception:
        return url

    # These short links are served by a redirect service whose landing page
    # carries the real Spotify URL in its markup rather than in a Location
    # header, so fall back to reading it out of the page.
    match = _PLAYLIST_ID_PATTERN.search(body)
    return match.group(0) if match else url


def parse_playlist_id(url_or_id: str) -> str:
    """Accept a full playlist URL, a spotify.link share link, a spotify: URI,
    or a bare playlist id."""
    value = (url_or_id or "").strip()
    if not value:
        raise SpotifyError("A Spotify playlist link is required.")

    if any(host in value for host in _SHORT_LINK_HOSTS):
        value = _resolve_short_link(value)

    match = _PLAYLIST_ID_PATTERN.search(value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{16,}", value):
        return value
    raise SpotifyError(
        "That does not look like a Spotify playlist link. Expected a link such as "
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M, a spotify:playlist:... URI, "
        "or a playlist id. Album, artist and track links are not playlists."
    )


# ---------------------------------------------------------------------------
# Embed reader. Playlists are read from Spotify's public embed page, which
# carries the playlist and its track list for any public playlist without an
# app, a token or any credentials at all. The Web API is deliberately not used:
# it requires per-user API credentials, refuses apps that lack Web API access
# with a bare 403, and cannot read Spotify's own editorial playlists anyway.
# This is an unofficial endpoint, so the parser walks the payload looking for
# the playlist entity rather than depending on a fixed path through it.
# ---------------------------------------------------------------------------

EMBED_URL_TEMPLATE = "https://open.spotify.com/embed/playlist/{playlist_id}"
PAGE_URL_TEMPLATE = "https://open.spotify.com/playlist/{playlist_id}"
_NEXT_DATA_PATTERN = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_INITIAL_STATE_PATTERN = re.compile(r'<script id="initialState"[^>]*>(.*?)</script>', re.S)


def _find_playlist_entity(node: Any) -> dict[str, Any] | None:
    if isinstance(node, dict):
        if isinstance(node.get("trackList"), list) and (node.get("name") or node.get("title")):
            return node
        for value in node.values():
            found = _find_playlist_entity(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_playlist_entity(item)
            if found is not None:
                return found
    return None


def _normalize_embed_track(entry: dict[str, Any]) -> dict[str, Any] | None:
    uri = str(entry.get("uri") or "")
    if not uri.startswith("spotify:track:"):
        return None  # podcast episodes and other non-track entries
    title = str(entry.get("title") or "")
    if not title:
        return None

    # The embed exposes artists as one display string, so the primary artist —
    # the one worth matching on — is the first entry.
    subtitle = str(entry.get("subtitle") or "")
    artists = [name.strip() for name in subtitle.split(",") if name.strip()]
    try:
        duration_seconds = int(int(entry.get("duration") or 0) / 1000)
    except (TypeError, ValueError):
        duration_seconds = 0

    return {
        "spotify_id": uri.rsplit(":", 1)[-1],
        "title": title,
        "artist": artists[0] if artists else "",
        "artists": artists,
        # The embed page carries neither album nor ISRC, so Deezer matching goes
        # by artist and title alone.
        "album": "",
        "duration_seconds": duration_seconds,
    }


def _fetch_page(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SpotifyError("Playlist not found. It may be private or the link may be wrong.") from exc
        raise SpotifyError(f"Could not read the playlist page ({exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise SpotifyError(f"Could not reach Spotify: {exc.reason}") from exc


def _normalize_page_track(entry: dict[str, Any]) -> dict[str, Any] | None:
    data = ((entry.get("itemV2") or {}).get("data")) or {}
    uri = str(data.get("uri") or "")
    if data.get("__typename") not in (None, "Track") or not uri.startswith("spotify:track:"):
        return None  # podcast episodes and other non-track entries
    title = str(data.get("name") or "")
    if not title:
        return None

    artists = [
        str((artist.get("profile") or {}).get("name") or "")
        for artist in ((data.get("artists") or {}).get("items") or [])
        if isinstance(artist, dict)
    ]
    artists = [name for name in artists if name]
    try:
        duration_seconds = int(int((data.get("duration") or {}).get("totalMilliseconds") or 0) / 1000)
    except (TypeError, ValueError):
        duration_seconds = 0

    return {
        "spotify_id": uri.rsplit(":", 1)[-1],
        "title": title,
        "artist": artists[0] if artists else "",
        "artists": artists,
        "album": str((data.get("albumOfTrack") or {}).get("name") or ""),
        "duration_seconds": duration_seconds,
    }


def _fetch_playlist_via_page(playlist_id: str) -> dict[str, Any]:
    """Read the playlist from the main open.spotify.com page, whose initial
    state carries the current track list. The embed page lags behind edits —
    a song added to a playlist can be missing from it for a long time — so this
    is the source of truth, and it also carries album names, which sharpen the
    Deezer match."""
    html = _fetch_page(PAGE_URL_TEMPLATE.format(playlist_id=urllib.parse.quote(playlist_id)))

    match = _INITIAL_STATE_PATTERN.search(html)
    if not match:
        raise SpotifyError("Could not read the playlist page.")
    try:
        payload = json.loads(base64.b64decode(match.group(1).strip()).decode("utf-8", "replace"))
    except Exception as exc:
        raise SpotifyError("Could not read the playlist page.") from exc

    entities = ((payload.get("entities") or {}).get("items")) or {}
    entity = entities.get(f"spotify:playlist:{playlist_id}")
    if not isinstance(entity, dict):
        # Fall back to whichever entity looks like the playlist, in case the key
        # is spelled differently.
        entity = next(
            (
                value
                for value in entities.values()
                if isinstance(value, dict) and isinstance(value.get("content"), dict)
            ),
            None,
        )
    if not isinstance(entity, dict):
        raise SpotifyError("Could not find the playlist on its Spotify page. It may be private.")

    content = entity.get("content") or {}
    tracks = [
        normalized
        for normalized in (
            _normalize_page_track(item)
            for item in content.get("items") or []
            if isinstance(item, dict)
        )
        if normalized is not None
    ]
    if not tracks:
        raise SpotifyError("The playlist page carried no tracks.")

    sources = ((entity.get("images") or {}).get("items") or [{}])[0].get("sources") or []
    image_url = _pick_cover(sources)

    total = content.get("totalCount")
    try:
        total_count = int(total)
    except (TypeError, ValueError):
        total_count = len(tracks)

    return {
        "id": str(entity.get("id") or playlist_id),
        "name": str(entity.get("name") or "Untitled playlist"),
        "owner": str(((entity.get("ownerV2") or {}).get("data") or {}).get("name") or ""),
        "image_url": image_url,
        "url": PAGE_URL_TEMPLATE.format(playlist_id=playlist_id),
        "track_count": len(tracks),
        # A long playlist is served one page at a time; the rest needs a token
        # Podify does not have, so say so rather than silently truncating.
        "incomplete_count": max(total_count - len(tracks), 0),
        "tracks": tracks,
    }


def _pick_cover(sources: list[Any]) -> str:
    """Prefer a mid-size cover; the cards render small."""
    usable = [source for source in sources if isinstance(source, dict) and source.get("url")]
    if not usable:
        return ""
    usable.sort(key=lambda source: abs(int(source.get("width") or 0) - 300))
    return str(usable[0]["url"])


def _fetch_playlist_via_embed(playlist_id: str) -> dict[str, Any]:
    html = _fetch_page(EMBED_URL_TEMPLATE.format(playlist_id=urllib.parse.quote(playlist_id)))

    match = _NEXT_DATA_PATTERN.search(html)
    if not match:
        raise SpotifyError("Could not read the playlist from Spotify's embed page.")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SpotifyError("Could not read the playlist from Spotify's embed page.") from exc

    entity = _find_playlist_entity(payload)
    if entity is None:
        raise SpotifyError(
            "Could not find the playlist on Spotify's embed page. It may be private."
        )

    tracks = [
        normalized
        for normalized in (
            _normalize_embed_track(entry)
            for entry in entity.get("trackList") or []
            if isinstance(entry, dict)
        )
        if normalized is not None
    ]

    image_url = _pick_cover((entity.get("coverArt") or {}).get("sources") or [])

    return {
        "id": str(entity.get("id") or playlist_id),
        "name": str(entity.get("name") or entity.get("title") or "Untitled playlist"),
        "owner": str(entity.get("subtitle") or ""),
        "image_url": image_url,
        "url": f"https://open.spotify.com/playlist/{playlist_id}",
        "track_count": len(tracks),
        "tracks": tracks,
    }


def fetch_playlist(playlist_id: str) -> dict[str, Any]:
    """Read a public playlist and its tracks, preferring the main page (current)
    over the embed page (lags behind playlist edits)."""
    try:
        return _fetch_playlist_via_page(playlist_id)
    except SpotifyError as page_error:
        try:
            return _fetch_playlist_via_embed(playlist_id)
        except SpotifyError:
            raise page_error


_TRACK_CACHE_LOCK = threading.Lock()
_TRACK_CACHE: dict[str, dict[str, Any]] = {}


def fetch_playlist_cached(playlist_id: str, force: bool = False) -> dict[str, Any]:
    """Playlists change slowly, so repeated views of the same playlist reuse a
    short-lived cached copy instead of re-fetching the embed page."""
    now = time.time()
    if not force:
        with _TRACK_CACHE_LOCK:
            cached = _TRACK_CACHE.get(playlist_id)
            if cached and now - cached["fetched_at"] < PLAYLIST_CACHE_TTL_SECONDS:
                return cached["data"]

    data = fetch_playlist(playlist_id)
    with _TRACK_CACHE_LOCK:
        _TRACK_CACHE[playlist_id] = {"fetched_at": now, "data": data}
    return data


def _invalidate_cache(playlist_id: str) -> None:
    with _TRACK_CACHE_LOCK:
        _TRACK_CACHE.pop(playlist_id, None)


# ---------------------------------------------------------------------------
# Tracked playlists (persisted)
# ---------------------------------------------------------------------------

_PLAYLISTS_LOCK = threading.RLock()


def _load_playlists() -> list[dict[str, Any]]:
    data = _read_json_file(playlists_path())
    if not isinstance(data, dict):
        return []
    playlists = data.get("playlists")
    if not isinstance(playlists, list):
        return []

    normalized: list[dict[str, Any]] = []
    for entry in playlists:
        if not isinstance(entry, dict):
            continue
        playlist_id = str(entry.get("id", "") or "").strip()
        if not playlist_id:
            continue
        synced = entry.get("synced_ids")
        unmatched = entry.get("unmatched_ids")
        tags = entry.get("synced_tracks")
        normalized.append(
            {
                "id": playlist_id,
                "name": str(entry.get("name", "") or ""),
                "owner": str(entry.get("owner", "") or ""),
                "image_url": str(entry.get("image_url", "") or ""),
                "url": str(entry.get("url", "") or f"https://open.spotify.com/playlist/{playlist_id}"),
                "track_count": int(entry.get("track_count", 0) or 0),
                "added_at": float(entry.get("added_at", 0) or 0),
                "auto_sync": bool(entry.get("auto_sync", True)),
                "last_synced_at": float(entry.get("last_synced_at", 0) or 0),
                "last_sync_status": str(entry.get("last_sync_status", "") or ""),
                "last_sync_message": str(entry.get("last_sync_message", "") or ""),
                "synced_ids": [str(item) for item in synced] if isinstance(synced, list) else [],
                "unmatched_ids": [str(item) for item in unmatched] if isinstance(unmatched, list) else [],
                # Deezer tags per synced track, so the iPod playlist mirror can
                # find them in the library on later syncs too.
                "synced_tracks": tags if isinstance(tags, dict) else {},
                "ipod_playlist_name": str(entry.get("ipod_playlist_name", "") or ""),
                "ipod_track_count": int(entry.get("ipod_track_count", 0) or 0),
            }
        )
    return normalized


def _save_playlists(playlists: list[dict[str, Any]]) -> None:
    _write_json_file_atomic(playlists_path(), {"playlists": playlists})


def _update_playlist(playlist_id: str, **fields: Any) -> None:
    with _PLAYLISTS_LOCK:
        playlists = _load_playlists()
        for playlist in playlists:
            if playlist["id"] == playlist_id:
                playlist.update(fields)
                break
        else:
            return
        _save_playlists(playlists)


def list_playlists() -> list[dict[str, Any]]:
    playlists = _load_playlists()
    active = {job["playlist_id"]: job for job in get_sync_jobs() if job["status"] in _ACTIVE_JOB_STATUSES}
    result: list[dict[str, Any]] = []
    for playlist in playlists:
        item = dict(playlist)
        item["synced_count"] = len(playlist["synced_ids"])
        item["unmatched_count"] = len(playlist["unmatched_ids"])
        item["pending_count"] = max(
            playlist["track_count"] - item["synced_count"] - item["unmatched_count"], 0
        )
        # synced_ids/unmatched_ids/synced_tracks can be thousands of entries; the
        # UI only needs the counts, so they are not sent over the wire.
        item.pop("synced_ids", None)
        item.pop("unmatched_ids", None)
        item.pop("synced_tracks", None)
        item["active_job"] = active.get(playlist["id"])
        result.append(item)
    return result


def add_playlist(url_or_id: str) -> dict[str, Any]:
    playlist_id = parse_playlist_id(url_or_id)

    with _PLAYLISTS_LOCK:
        if any(playlist["id"] == playlist_id for playlist in _load_playlists()):
            raise SpotifyError("That playlist is already being tracked.")

    data = fetch_playlist_cached(playlist_id, force=True)

    with _PLAYLISTS_LOCK:
        playlists = _load_playlists()
        if any(playlist["id"] == playlist_id for playlist in playlists):
            raise SpotifyError("That playlist is already being tracked.")
        record = {
            "id": playlist_id,
            "name": data["name"],
            "owner": data["owner"],
            "image_url": data["image_url"],
            "url": data["url"],
            "track_count": data["track_count"],
            "added_at": time.time(),
            "auto_sync": True,
            "last_synced_at": 0.0,
            "last_sync_status": "",
            "last_sync_message": "",
            "synced_ids": [],
            "unmatched_ids": [],
            "synced_tracks": {},
            "ipod_playlist_name": "",
            "ipod_track_count": 0,
        }
        playlists.append(record)
        _save_playlists(playlists)
    return record


def remove_playlist(playlist_id: str) -> None:
    with _PLAYLISTS_LOCK:
        playlists = _load_playlists()
        remaining = [playlist for playlist in playlists if playlist["id"] != playlist_id]
        if len(remaining) == len(playlists):
            raise SpotifyError("Playlist is not tracked.")
        _save_playlists(remaining)
    _invalidate_cache(playlist_id)


def set_playlist_auto_sync(playlist_id: str, enabled: bool) -> None:
    with _PLAYLISTS_LOCK:
        playlists = _load_playlists()
        if not any(playlist["id"] == playlist_id for playlist in playlists):
            raise SpotifyError("Playlist is not tracked.")
    _update_playlist(playlist_id, auto_sync=bool(enabled))


def reset_playlist_sync_state(playlist_id: str) -> None:
    """Forget which tracks were already downloaded so the next sync re-downloads
    the whole playlist."""
    with _PLAYLISTS_LOCK:
        playlists = _load_playlists()
        if not any(playlist["id"] == playlist_id for playlist in playlists):
            raise SpotifyError("Playlist is not tracked.")
    _update_playlist(
        playlist_id,
        synced_ids=[],
        unmatched_ids=[],
        synced_tracks={},
        last_sync_status="",
        last_sync_message="Sync history cleared.",
    )


def playlist_tracks(playlist_id: str, force: bool = False) -> dict[str, Any]:
    """Playlist tracks annotated with their per-track sync state."""
    with _PLAYLISTS_LOCK:
        tracked = next((p for p in _load_playlists() if p["id"] == playlist_id), None)
    if tracked is None:
        raise SpotifyError("Playlist is not tracked.")

    data = fetch_playlist_cached(playlist_id, force=force)
    synced = set(tracked["synced_ids"])
    unmatched = set(tracked["unmatched_ids"])

    tracks = []
    for track in data["tracks"]:
        state = "synced" if track["spotify_id"] in synced else (
            "unmatched" if track["spotify_id"] in unmatched else "pending"
        )
        tracks.append(dict(track, sync_state=state))

    # The playlist may have grown or shrunk since it was added.
    if data["track_count"] != tracked["track_count"] or data["name"] != tracked["name"]:
        _update_playlist(
            playlist_id,
            track_count=data["track_count"],
            name=data["name"],
            image_url=data["image_url"],
        )

    return {"playlist_id": playlist_id, "name": data["name"], "tracks": tracks}


# ---------------------------------------------------------------------------
# Sync jobs. Resolution (Spotify track -> Deezer track) runs in a background
# thread, then the existing deemix download pipeline does the downloading,
# FLAC->ALAC conversion and copy to the iPod.
# ---------------------------------------------------------------------------

_SYNC_LOCK = threading.Lock()
_SYNC_JOBS: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_MAX_SYNC_JOBS = 20
_ACTIVE_JOB_STATUSES = {"queued", "resolving", "downloading"}
_SYNC_SERIAL_LOCK = threading.Lock()
_RUNNING_PLAYLISTS: set[str] = set()


def _new_sync_job(playlist_id: str, playlist_name: str, quality: str, mountpoint: str) -> dict[str, Any]:
    job = {
        "job_id": uuid_lib.uuid4().hex,
        "playlist_id": playlist_id,
        "playlist_name": playlist_name,
        "quality": quality,
        "mountpoint": mountpoint,
        "status": "queued",
        "total_count": 0,
        "new_count": 0,
        "resolved_count": 0,
        "matched_count": 0,
        "unmatched_count": 0,
        "downloaded_count": 0,
        "failed_count": 0,
        "deemix_job_ids": [],
        "message": "",
        "created_at": time.time(),
    }
    with _SYNC_LOCK:
        _SYNC_JOBS[job["job_id"]] = job
        while len(_SYNC_JOBS) > _MAX_SYNC_JOBS:
            _SYNC_JOBS.popitem(last=False)
    return job


def _update_sync_job(job_id: str, **fields: Any) -> None:
    with _SYNC_LOCK:
        job = _SYNC_JOBS.get(job_id)
        if job:
            job.update(fields)


def get_sync_jobs() -> list[dict[str, Any]]:
    with _SYNC_LOCK:
        return [dict(job) for job in reversed(_SYNC_JOBS.values())]


def start_sync(playlist_id: str, mountpoint: str | None = None, quality: str | None = None) -> str:
    with _PLAYLISTS_LOCK:
        playlist = next((p for p in _load_playlists() if p["id"] == playlist_id), None)
    if playlist is None:
        raise SpotifyError("Playlist is not tracked.")

    with _SYNC_LOCK:
        if playlist_id in _RUNNING_PLAYLISTS:
            raise SpotifyError("A sync is already running for this playlist.")
        _RUNNING_PLAYLISTS.add(playlist_id)

    try:
        normalized_mountpoint = (mountpoint or "").strip() or load_config()["last_mountpoint"]
        if normalized_mountpoint:
            _remember_mountpoint(normalized_mountpoint)
        job = _new_sync_job(
            playlist_id,
            playlist["name"],
            (quality or "").strip().upper() or effective_quality(),
            normalized_mountpoint,
        )
    except Exception:
        with _SYNC_LOCK:
            _RUNNING_PLAYLISTS.discard(playlist_id)
        raise

    thread = threading.Thread(target=_run_sync_job, args=(job["job_id"],), daemon=True)
    thread.start()
    return job["job_id"]


def sync_all(mountpoint: str | None = None, quality: str | None = None) -> list[str]:
    job_ids: list[str] = []
    for playlist in _load_playlists():
        try:
            job_ids.append(start_sync(playlist["id"], mountpoint, quality))
        except SpotifyError:
            continue  # already running for that playlist
    return job_ids


# ---------------------------------------------------------------------------
# iPod playlist mirror. A tracked Spotify playlist is reproduced as a real
# playlist on the device holding the same songs, so the iPod shows the playlist
# and not just a pile of loose tracks.
# ---------------------------------------------------------------------------


def _normalize_match_text(value: str) -> str:
    lowered = (value or "").casefold()
    lowered = re.sub(r"\(.*?\)|\[.*?\]", " ", lowered)
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(lowered.split())


def _base_title(value: str) -> str:
    """Drop a version suffix (" - Remastered 2011", " - Bonus Track") so the
    same song spelled differently by Deezer and Spotify collapses to one key."""
    return _normalize_match_text(re.split(r"\s-\s", value or "", maxsplit=1)[0])


class _LibraryIndex:
    """Library lookup by title and artist. Tags on the device come from Deezer
    and are reshaped again by the FLAC->ALAC step, so an exact string match on
    both fields misses a fair number of real matches: featured artists appear on
    one side only, and titles pick up version suffixes."""

    def __init__(self, tracks: list[dict[str, Any]]) -> None:
        self.exact: dict[tuple[str, str], int] = {}
        self.by_title: dict[str, list[tuple[int, str]]] = {}
        for track in tracks:
            try:
                track_id = int(track.get("id"))
            except (TypeError, ValueError):
                continue
            title = str(track.get("title") or "")
            artist = str(track.get("artist") or "")
            artist_key = _normalize_match_text(artist)
            self.exact.setdefault((_normalize_match_text(title), artist_key), track_id)
            self.by_title.setdefault(_base_title(title), []).append((track_id, artist_key))

    def find(self, title: str, artist: str) -> int | None:
        if not title:
            return None
        artist_key = _normalize_match_text(artist)

        found = self.exact.get((_normalize_match_text(title), artist_key))
        if found is not None:
            return found

        candidates = self.by_title.get(_base_title(title), [])
        if not candidates:
            return None

        for track_id, candidate_artist in candidates:
            if candidate_artist == artist_key:
                return track_id

        # "Kendrick Lamar" vs "Kendrick Lamar, Mary J. Blige" / "... feat. X":
        # the primary artist leads and features are appended, so compare on the
        # leading name. A bare substring test would also match "Band" against an
        # unrelated "Some Band".
        if artist_key:
            for track_id, candidate_artist in candidates:
                if candidate_artist and (
                    candidate_artist.startswith(f"{artist_key} ")
                    or artist_key.startswith(f"{candidate_artist} ")
                ):
                    return track_id

        # One song with that title in the whole library: it is that one.
        if len(candidates) == 1:
            return candidates[0][0]
        return None


def _backfill_deezer_tags(playlist_id: str, spotify_tracks: list[dict[str, Any]]) -> None:
    """Fill in the Deezer tags of tracks that were synced before Podify started
    recording them. Without tags the mirror has only Spotify's spelling to match
    the library on, which misses the songs Deezer titles differently. This costs
    one search per track, once — no downloads."""
    with _PLAYLISTS_LOCK:
        record = next((p for p in _load_playlists() if p["id"] == playlist_id), None)
    if record is None:
        return

    synced = set(record["synced_ids"])
    known = dict(record["synced_tracks"])
    missing = [
        track
        for track in spotify_tracks
        if track["spotify_id"] in synced and track["spotify_id"] not in known
    ]
    if not missing:
        return

    try:
        dz = connect_deezer()
    except DeemixError:
        return  # no Deezer session; the mirror falls back to Spotify's tags

    for track in missing:
        found = _match_on_deezer(dz, track)
        if found:
            known[track["spotify_id"]] = {"title": found["title"], "artist": found["artist"]}

    if known != record["synced_tracks"]:
        _update_playlist(playlist_id, synced_tracks=known)


def _mirror_playlist_to_ipod(
    playlist_id: str, playlist_name: str, mountpoint: str, spotify_tracks: list[dict[str, Any]]
) -> str:
    """Make an iPod playlist hold exactly the playlist's songs that are on the
    device, in Spotify's order. Tracks are matched to the library by the Deezer
    tags they were downloaded with, falling back to Spotify's spelling."""
    if not mountpoint:
        return ""

    with _PLAYLISTS_LOCK:
        record = next((p for p in _load_playlists() if p["id"] == playlist_id), None)
    if record is None:
        return ""

    synced = set(record["synced_ids"])
    known_tags = record["synced_tracks"]

    library = load_library(mountpoint)
    index = _LibraryIndex(library.get("tracks", []))

    desired: list[int] = []
    seen: set[int] = set()
    unlocated: list[str] = []
    for track in spotify_tracks:
        spotify_id = track["spotify_id"]
        if spotify_id not in synced:
            continue
        tags = known_tags.get(spotify_id) or {}
        # Deezer's tags first (they are what is on the device), then Spotify's.
        track_id = index.find(
            tags.get("title") or track["title"], tags.get("artist") or track["artist"]
        )
        if track_id is None and tags:
            track_id = index.find(track["title"], track["artist"])
        if track_id is None:
            unlocated.append(f'{track["title"]} — {track["artist"]}')
            continue
        if track_id not in seen:
            seen.add(track_id)
            desired.append(track_id)

    if not desired:
        return ""

    # A renamed Spotify playlist would otherwise leave the old mirror behind.
    previous_name = record["ipod_playlist_name"]
    if previous_name and previous_name != playlist_name:
        try:
            delete_ipod_playlist(mountpoint, previous_name)
        except GpodError:
            pass

    # create is a no-op when the playlist already exists.
    create_ipod_playlist(mountpoint, playlist_name)

    current: list[int] = []
    for playlist in library.get("playlists", []):
        if playlist.get("name") == playlist_name:
            current = [int(track_id) for track_id in playlist.get("track_ids", [])]
            break

    current_set = set(current)
    desired_set = set(desired)
    to_add = [track_id for track_id in desired if track_id not in current_set]
    to_remove = [track_id for track_id in current if track_id not in desired_set]

    if to_remove:
        remove_tracks_from_ipod_playlist(mountpoint, playlist_name, to_remove)
    if to_add:
        add_tracks_to_ipod_playlist(mountpoint, playlist_name, to_add)

    _update_playlist(
        playlist_id, ipod_playlist_name=playlist_name, ipod_track_count=len(desired)
    )

    message = f'iPod playlist "{playlist_name}": {len(desired)} track(s).'
    if unlocated:
        listed = "; ".join(unlocated[:3])
        if len(unlocated) > 3:
            listed = f"{listed}; ..."
        message = (
            f"{message} {len(unlocated)} synced track(s) not found in the iPod library "
            f"({listed})."
        )
    return message


def _match_on_deezer(dz: Any, track: dict[str, Any]) -> dict[str, str] | None:
    """Resolve a Spotify track to a Deezer track: Deezer's own artist/track/album
    matcher first, then a plain text search.

    Returns the matched track's id plus its Deezer title and artist. Those tags
    are what deemix writes into the file and therefore what the iPod library
    reports, so the iPod playlist mirror keys on them rather than on Spotify's
    spelling of the same song."""
    artist = track.get("artist") or ""
    title = track.get("title") or ""
    album = track.get("album") or ""
    if not (artist and title):
        return None

    def described(item: dict[str, Any]) -> dict[str, str]:
        return {
            "id": str(item.get("id") or ""),
            "title": str(item.get("title") or title),
            "artist": str((item.get("artist") or {}).get("name") or artist),
        }

    deezer_id = ""
    try:
        candidate = str(dz.api.get_track_id_from_metadata(artist, title, album) or "0")
        if candidate and candidate != "0":
            deezer_id = candidate
    except Exception:
        pass

    if deezer_id:
        try:
            return described(dz.api.get_track(deezer_id))
        except Exception:
            # The id is good even if the follow-up lookup failed; fall back to
            # Spotify's tags for the mirror key.
            return {"id": deezer_id, "title": title, "artist": artist}

    try:
        data = dz.api.search_track(f"{artist} {title}", limit=1).get("data", [])
        if data:
            matched = described(data[0])
            if matched["id"] and matched["id"] != "0":
                return matched
    except Exception:
        pass

    return None


def _run_sync_job(job_id: str) -> None:
    # Playlist syncs run one at a time. Concurrent syncs download into the same
    # deemix staging directory, where one job's cleanup can remove an album
    # folder another job is still writing into. A waiting job stays "queued".
    with _SYNC_SERIAL_LOCK:
        _execute_sync_job(job_id)


def _execute_sync_job(job_id: str) -> None:
    with _SYNC_LOCK:
        job = _SYNC_JOBS.get(job_id)
        if job is None:
            return
        playlist_id = job["playlist_id"]
        playlist_name = job["playlist_name"]
        quality = job["quality"]
        mountpoint = job["mountpoint"]

    def mirror(spotify_tracks: list[dict[str, Any]]) -> str:
        """Reproduce the playlist on the device. A mirror failure must not fail
        the sync — the music is already on the iPod either way."""
        if not mountpoint:
            return ""
        try:
            _backfill_deezer_tags(playlist_id, spotify_tracks)
        except Exception:
            pass  # best effort; the mirror still runs on Spotify's tags
        try:
            return _mirror_playlist_to_ipod(playlist_id, playlist_name, mountpoint, spotify_tracks)
        except GpodError as exc:
            return f"iPod playlist not updated: {exc}"
        except Exception as exc:
            return f"iPod playlist not updated: {exc}"

    def finish(status: str, message: str) -> None:
        _update_sync_job(job_id, status=status, message=message)
        _update_playlist(
            playlist_id,
            last_synced_at=time.time(),
            last_sync_status=status,
            last_sync_message=message,
        )
        with _SYNC_LOCK:
            _RUNNING_PLAYLISTS.discard(playlist_id)

    try:
        _update_sync_job(job_id, status="resolving")
        _update_playlist(playlist_id, last_sync_status="resolving", last_sync_message="Reading playlist...")

        data = fetch_playlist_cached(playlist_id, force=True)
        with _PLAYLISTS_LOCK:
            tracked = next((p for p in _load_playlists() if p["id"] == playlist_id), None)
        if tracked is None:
            finish("error", "Playlist is no longer tracked.")
            return

        _update_playlist(
            playlist_id,
            name=data["name"],
            image_url=data["image_url"],
            track_count=data["track_count"],
        )
        playlist_name = data["name"]
        _update_sync_job(job_id, playlist_name=playlist_name)

        synced_ids = set(tracked["synced_ids"])
        unmatched_ids = set(tracked["unmatched_ids"])
        previously_unmatched = set(unmatched_ids)
        # Tracks that failed to match before are retried on every sync — they may
        # have since appeared on Deezer.
        pending = [track for track in data["tracks"] if track["spotify_id"] not in synced_ids]

        _update_sync_job(job_id, total_count=data["track_count"], new_count=len(pending))

        if not pending:
            finish("done", " ".join(filter(None, ["Already up to date.", mirror(data["tracks"])])))
            return

        try:
            dz = connect_deezer()
        except DeemixError as exc:
            finish("error", str(exc))
            return

        matched: list[tuple[str, dict[str, str]]] = []  # (spotify_id, deezer track)
        newly_unmatched: list[str] = []

        for index, track in enumerate(pending):
            deezer_track = _match_on_deezer(dz, track)
            if deezer_track:
                matched.append((track["spotify_id"], deezer_track))
                unmatched_ids.discard(track["spotify_id"])
            else:
                newly_unmatched.append(track["spotify_id"])
                unmatched_ids.add(track["spotify_id"])
            _update_sync_job(
                job_id,
                resolved_count=index + 1,
                matched_count=len(matched),
                unmatched_count=len(newly_unmatched),
            )

        _update_playlist(playlist_id, unmatched_ids=sorted(unmatched_ids))

        if not matched:
            first_time_unmatched = [
                track_id for track_id in newly_unmatched if track_id not in previously_unmatched
            ]
            mirror_message = mirror(data["tracks"])
            if first_time_unmatched:
                finish(
                    "error",
                    " ".join(
                        filter(
                            None,
                            [
                                f"No Deezer match found for {len(first_time_unmatched)} new track(s).",
                                mirror_message,
                            ],
                        )
                    ),
                )
            else:
                finish(
                    "done",
                    " ".join(
                        filter(
                            None,
                            [
                                f"Already up to date. {len(newly_unmatched)} track(s) are not "
                                "available on Deezer.",
                                mirror_message,
                            ],
                        )
                    ),
                )
            return

        _update_sync_job(job_id, status="downloading")
        _update_playlist(
            playlist_id,
            last_sync_status="downloading",
            last_sync_message=f"Downloading {len(matched)} track(s)...",
        )

        downloaded_total = 0
        failed_total = 0

        for start in range(0, len(matched), DOWNLOAD_BATCH_SIZE):
            batch = matched[start : start + DOWNLOAD_BATCH_SIZE]
            items = [
                {
                    "id": deezer_track["id"],
                    "type": "track",
                    "title": deezer_track["title"],
                    "artist": deezer_track["artist"],
                }
                for _spotify_id, deezer_track in batch
            ]

            try:
                deemix_job_id = start_download_job(items, quality, mountpoint or None)
            except DeemixError as exc:
                finish("error", str(exc))
                return

            with _SYNC_LOCK:
                current = _SYNC_JOBS.get(job_id)
                if current is not None:
                    current["deemix_job_ids"].append(deemix_job_id)

            deemix_job = _wait_for_deemix_job(deemix_job_id)
            job_items = (deemix_job or {}).get("items", [])

            batch_synced: list[str] = []
            batch_tags: dict[str, dict[str, str]] = {}
            for (spotify_id, deezer_track), job_item in zip(batch, job_items):
                if job_item.get("status") == "done":
                    batch_synced.append(spotify_id)
                    batch_tags[spotify_id] = {
                        "title": deezer_track["title"],
                        "artist": deezer_track["artist"],
                    }
                else:
                    failed_total += 1

            if batch_synced:
                downloaded_total += len(batch_synced)
                with _PLAYLISTS_LOCK:
                    current_playlist = next(
                        (p for p in _load_playlists() if p["id"] == playlist_id), None
                    )
                    if current_playlist is None:
                        finish("error", "Playlist is no longer tracked.")
                        return
                    merged_synced = sorted(set(current_playlist["synced_ids"]) | set(batch_synced))
                    merged_tags = dict(current_playlist["synced_tracks"])
                    merged_tags.update(batch_tags)
                    _update_playlist(
                        playlist_id, synced_ids=merged_synced, synced_tracks=merged_tags
                    )

            _update_sync_job(
                job_id, downloaded_count=downloaded_total, failed_count=failed_total
            )

        parts = [f"Synced {downloaded_total} new track(s)."]
        incomplete = int(data.get("incomplete_count", 0) or 0)
        if incomplete:
            parts.append(f"{incomplete} track(s) of this playlist are not readable without a login.")
        if failed_total:
            parts.append(f"{failed_total} failed to download.")
        if newly_unmatched:
            parts.append(f"{len(newly_unmatched)} not found on Deezer.")
        mirror_message = mirror(data["tracks"])
        if mirror_message:
            parts.append(mirror_message)
        finish("done" if downloaded_total else "error", " ".join(parts))
    except SpotifyError as exc:
        finish("error", str(exc))
    except Exception as exc:
        finish("error", f"Sync failed: {exc}")


def _wait_for_deemix_job(deemix_job_id: str, poll_seconds: float = 1.0) -> dict[str, Any] | None:
    while True:
        job = get_deemix_job(deemix_job_id)
        if job is None:
            return None
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(poll_seconds)


# ---------------------------------------------------------------------------
# Background auto-sync. The app runs as a single gunicorn worker (deemix job
# state is in-process), so one scheduler thread per process is correct.
# ---------------------------------------------------------------------------

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
            _run_due_playlists()
        except Exception:
            continue


def _run_due_playlists() -> None:
    config = load_config()
    if not config["auto_sync_enabled"]:
        return

    mountpoint = config["last_mountpoint"]
    if not mountpoint:
        return

    interval_seconds = config["check_interval_minutes"] * 60
    now = time.time()
    for playlist in _load_playlists():
        if not playlist["auto_sync"]:
            continue
        if now - playlist["last_synced_at"] < interval_seconds:
            continue
        try:
            start_sync(playlist["id"], mountpoint, config["quality"] or None)
        except SpotifyError:
            continue


def _read_json_file(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _write_json_file_atomic(path: str, data: Any) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".tmp_spotify_", dir=directory)
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
