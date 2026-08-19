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


class SpotifyError(RuntimeError):
    pass


SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"

# Tracks are downloaded in batches so that a long playlist reaches the iPod
# incrementally instead of staging hundreds of files before the first copy.
DOWNLOAD_BATCH_SIZE = 20
DEFAULT_CHECK_INTERVAL_MINUTES = 60
PLAYLIST_CACHE_TTL_SECONDS = 300

_PLAYLIST_ID_PATTERN = re.compile(r"playlist[/:]([A-Za-z0-9]+)")


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
        "client_id": "",
        "client_secret": "",
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

    merged["client_id"] = str(data.get("client_id", "") or "")
    merged["client_secret"] = str(data.get("client_secret", "") or "")
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

    client_id = updates.get("client_id")
    if isinstance(client_id, str) and client_id.strip():
        merged["client_id"] = client_id.strip()

    client_secret = updates.get("client_secret")
    if isinstance(client_secret, str) and client_secret.strip():
        merged["client_secret"] = client_secret.strip()

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
    _reset_token_cache()
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
        "credentials_configured": bool(config["client_id"] and config["client_secret"]),
        "client_id_configured": bool(config["client_id"]),
        "auto_sync_enabled": config["auto_sync_enabled"],
        "check_interval_minutes": config["check_interval_minutes"],
        "quality": effective_quality(),
        "last_mountpoint": config["last_mountpoint"],
        "playlist_count": len(_load_playlists()),
    }


# ---------------------------------------------------------------------------
# Spotify Web API (client-credentials flow — public playlists only)
# ---------------------------------------------------------------------------

_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, Any] = {"access_token": "", "expires_at": 0.0}


def _reset_token_cache() -> None:
    with _TOKEN_LOCK:
        _TOKEN_CACHE["access_token"] = ""
        _TOKEN_CACHE["expires_at"] = 0.0


def _access_token() -> str:
    with _TOKEN_LOCK:
        if _TOKEN_CACHE["access_token"] and _TOKEN_CACHE["expires_at"] > time.time() + 30:
            return str(_TOKEN_CACHE["access_token"])

    config = load_config()
    client_id = config["client_id"]
    client_secret = config["client_secret"]
    if not client_id or not client_secret:
        raise SpotifyError(
            "Spotify API credentials are not configured. Add a Client ID and Client Secret in Settings."
        )

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        SPOTIFY_TOKEN_URL,
        data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8"),
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in {400, 401, 403}:
            raise SpotifyError("Spotify rejected the credentials. Check the Client ID and Secret.") from exc
        raise SpotifyError(f"Spotify authentication failed ({exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise SpotifyError(f"Could not reach Spotify: {exc.reason}") from exc
    except Exception as exc:
        raise SpotifyError(f"Spotify authentication failed: {exc}") from exc

    token = str(payload.get("access_token", "") or "")
    if not token:
        raise SpotifyError("Spotify did not return an access token.")

    try:
        expires_in = int(payload.get("expires_in", 3600))
    except (TypeError, ValueError):
        expires_in = 3600

    with _TOKEN_LOCK:
        _TOKEN_CACHE["access_token"] = token
        _TOKEN_CACHE["expires_at"] = time.time() + expires_in
    return token


def _api_get(url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    if not url.startswith("http"):
        url = f"{SPOTIFY_API_BASE}{url}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    for attempt in range(3):
        request = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {_access_token()}"}, method="GET"
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    delay = min(int(retry_after or 2), 10)
                except (TypeError, ValueError):
                    delay = 2
                time.sleep(delay)
                continue
            if exc.code == 401 and attempt < 2:
                _reset_token_cache()
                continue
            if exc.code == 404:
                raise SpotifyError("Playlist not found. It may be private or the link may be wrong.") from exc
            raise SpotifyError(f"Spotify request failed ({exc.code}).") from exc
        except urllib.error.URLError as exc:
            raise SpotifyError(f"Could not reach Spotify: {exc.reason}") from exc
        except Exception as exc:
            raise SpotifyError(f"Spotify request failed: {exc}") from exc

    raise SpotifyError("Spotify request failed after retries.")


def parse_playlist_id(url_or_id: str) -> str:
    """Accept a full playlist URL, a spotify: URI, or a bare playlist id."""
    value = (url_or_id or "").strip()
    if not value:
        raise SpotifyError("A Spotify playlist link is required.")

    match = _PLAYLIST_ID_PATTERN.search(value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{16,}", value):
        return value
    raise SpotifyError("That does not look like a Spotify playlist link.")


def fetch_playlist(playlist_id: str) -> dict[str, Any]:
    """Fetch playlist metadata plus every track (paginated 100 at a time)."""
    meta = _api_get(
        f"/playlists/{urllib.parse.quote(playlist_id)}",
        {"fields": "id,name,owner(display_name),images(url),external_urls(spotify),tracks(total)"},
    )

    images = meta.get("images") or []
    tracks: list[dict[str, Any]] = []
    next_url: str | None = f"{SPOTIFY_API_BASE}/playlists/{urllib.parse.quote(playlist_id)}/tracks"
    params: dict[str, str] | None = {
        "limit": "100",
        "fields": "next,items(track(id,name,type,duration_ms,external_ids(isrc),artists(name),album(name)))",
    }

    while next_url:
        page = _api_get(next_url, params)
        params = None
        for entry in page.get("items") or []:
            track = entry.get("track") if isinstance(entry, dict) else None
            if not isinstance(track, dict):
                continue
            if track.get("type") not in (None, "track"):
                continue  # podcast episodes and other non-track items
            artists = [
                str(artist.get("name") or "")
                for artist in (track.get("artists") or [])
                if isinstance(artist, dict)
            ]
            artists = [name for name in artists if name]
            track_id = str(track.get("id") or "")
            title = str(track.get("name") or "")
            if not title:
                continue
            tracks.append(
                {
                    # Local files have no id; fall back to a stable synthetic key
                    # so they can still be tracked as synced/unmatched.
                    "spotify_id": track_id or f"local:{artists[0] if artists else ''}:{title}",
                    "title": title,
                    "artist": artists[0] if artists else "",
                    "artists": artists,
                    "album": str((track.get("album") or {}).get("name") or ""),
                    "isrc": str((track.get("external_ids") or {}).get("isrc") or ""),
                    "duration_seconds": int((track.get("duration_ms") or 0) / 1000),
                }
            )
        next_url = page.get("next")

    return {
        "id": str(meta.get("id") or playlist_id),
        "name": str(meta.get("name") or "Untitled playlist"),
        "owner": str((meta.get("owner") or {}).get("display_name") or ""),
        "image_url": str(images[0].get("url") or "") if images else "",
        "url": str((meta.get("external_urls") or {}).get("spotify") or "")
        or f"https://open.spotify.com/playlist/{playlist_id}",
        "track_count": len(tracks),
        "tracks": tracks,
    }


_TRACK_CACHE_LOCK = threading.Lock()
_TRACK_CACHE: dict[str, dict[str, Any]] = {}


def fetch_playlist_cached(playlist_id: str, force: bool = False) -> dict[str, Any]:
    """Spotify is rate limited and playlists change slowly, so repeated views of
    the same playlist reuse a short-lived cached copy."""
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
        # synced_ids/unmatched_ids can be thousands of strings; the UI only needs
        # the counts, so they are not sent over the wire.
        item.pop("synced_ids", None)
        item.pop("unmatched_ids", None)
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


def _match_on_deezer(dz: Any, track: dict[str, Any]) -> str | None:
    """Resolve a Spotify track to a Deezer track id: ISRC first (exact), then
    Deezer's own artist/track/album matcher, then a plain text search."""
    isrc = track.get("isrc") or ""
    if isrc:
        try:
            result = dz.api.get_track_by_ISRC(isrc)
            deezer_id = str((result or {}).get("id") or "")
            if deezer_id and deezer_id != "0":
                return deezer_id
        except Exception:
            pass

    artist = track.get("artist") or ""
    title = track.get("title") or ""
    album = track.get("album") or ""
    if artist and title:
        try:
            deezer_id = str(dz.api.get_track_id_from_metadata(artist, title, album) or "0")
            if deezer_id and deezer_id != "0":
                return deezer_id
        except Exception:
            pass

        try:
            data = dz.api.search_track(f"{artist} {title}", limit=1).get("data", [])
            if data:
                deezer_id = str(data[0].get("id") or "")
                if deezer_id and deezer_id != "0":
                    return deezer_id
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
        quality = job["quality"]
        mountpoint = job["mountpoint"]

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

        synced_ids = set(tracked["synced_ids"])
        unmatched_ids = set(tracked["unmatched_ids"])
        previously_unmatched = set(unmatched_ids)
        # Tracks that failed to match before are retried on every sync — they may
        # have since appeared on Deezer.
        pending = [track for track in data["tracks"] if track["spotify_id"] not in synced_ids]

        _update_sync_job(job_id, total_count=data["track_count"], new_count=len(pending))

        if not pending:
            finish("done", "Already up to date.")
            return

        try:
            dz = connect_deezer()
        except DeemixError as exc:
            finish("error", str(exc))
            return

        matched: list[tuple[str, str]] = []  # (spotify_id, deezer_id)
        matched_meta: dict[str, dict[str, Any]] = {}
        newly_unmatched: list[str] = []

        for index, track in enumerate(pending):
            deezer_id = _match_on_deezer(dz, track)
            if deezer_id:
                matched.append((track["spotify_id"], deezer_id))
                matched_meta[track["spotify_id"]] = track
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
            if first_time_unmatched:
                finish("error", f"No Deezer match found for {len(first_time_unmatched)} new track(s).")
            else:
                finish(
                    "done",
                    f"Already up to date. {len(newly_unmatched)} track(s) are not available on Deezer.",
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
                    "id": deezer_id,
                    "type": "track",
                    "title": matched_meta[spotify_id]["title"],
                    "artist": matched_meta[spotify_id]["artist"],
                }
                for spotify_id, deezer_id in batch
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
            for (spotify_id, _deezer_id), job_item in zip(batch, job_items):
                if job_item.get("status") == "done":
                    batch_synced.append(spotify_id)
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
                    _update_playlist(playlist_id, synced_ids=merged_synced)

            _update_sync_job(
                job_id, downloaded_count=downloaded_total, failed_count=failed_total
            )

        parts = [f"Synced {downloaded_total} new track(s)."]
        if failed_total:
            parts.append(f"{failed_total} failed to download.")
        if newly_unmatched:
            parts.append(f"{len(newly_unmatched)} not found on Deezer.")
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
    if not (config["client_id"] and config["client_secret"]):
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
