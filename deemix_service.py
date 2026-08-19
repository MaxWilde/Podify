from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import uuid as uuid_lib
from collections import OrderedDict
from itertools import zip_longest
from typing import Any

from ipod_service import GpodError, add_tracks as add_tracks_to_ipod
from settings_service import load_settings


class DeemixError(RuntimeError):
    pass


DEFAULT_DOWNLOAD_SUBDIR = "deemix"
DEFAULT_QUALITY = "FLAC"
QUALITY_LABELS = ("FLAC", "MP3_320", "MP3_128")
RESULT_TYPES = ("track", "album", "artist")


def config_path() -> str:
    configured = os.environ.get("DEEMIX_CONFIG_PATH", "").strip()
    if configured:
        return configured
    return os.path.join(os.getcwd(), ".deemix_config.json")


def _default_config() -> dict[str, Any]:
    return {
        "arl": "",
        "download_subdir": os.environ.get("DEEMIX_DOWNLOAD_SUBDIR", "").strip() or DEFAULT_DOWNLOAD_SUBDIR,
        "default_quality": DEFAULT_QUALITY,
    }


def load_config() -> dict[str, Any]:
    data = _read_json_file(config_path())
    merged = _default_config()
    if not isinstance(data, dict):
        return merged

    merged["arl"] = str(data.get("arl", "") or "")

    subdir = str(data.get("download_subdir", "") or "").strip()
    if subdir:
        merged["download_subdir"] = subdir

    quality = str(data.get("default_quality", "") or "").strip().upper()
    if quality in QUALITY_LABELS:
        merged["default_quality"] = quality

    return merged


def save_config(updates: dict[str, Any]) -> dict[str, Any]:
    current = load_config()
    merged = dict(current)

    arl = updates.get("arl")
    if isinstance(arl, str) and arl.strip():
        merged["arl"] = arl.strip()

    subdir = updates.get("download_subdir")
    if isinstance(subdir, str) and subdir.strip():
        merged["download_subdir"] = subdir.strip()

    quality = updates.get("default_quality")
    if isinstance(quality, str) and quality.strip():
        normalized_quality = quality.strip().upper()
        if normalized_quality not in QUALITY_LABELS:
            raise DeemixError(f"Unsupported quality: {quality}")
        merged["default_quality"] = normalized_quality

    settings = load_settings()
    music_directory = str(settings.get("music_directory", "") or "").strip()
    if music_directory:
        if not os.path.isdir(music_directory):
            raise DeemixError(f"Music Directory not found: {music_directory}")
        os.makedirs(os.path.join(music_directory, merged["download_subdir"]), exist_ok=True)

    _write_json_file_atomic(config_path(), merged)
    return merged


def get_status() -> dict[str, Any]:
    config = load_config()
    settings = load_settings()
    music_directory = str(settings.get("music_directory", "") or "")
    download_dir = os.path.join(music_directory, config["download_subdir"]) if music_directory else ""
    return {
        "enabled": True,
        "arl_configured": bool(config["arl"]),
        "download_dir": download_dir,
        "music_directory": music_directory,
        "default_quality": config["default_quality"],
    }


def _quality_to_format(quality: str) -> int:
    from deezer import TrackFormats

    mapping = {
        "FLAC": TrackFormats.FLAC,
        "MP3_320": TrackFormats.MP3_320,
        "MP3_128": TrackFormats.MP3_128,
    }
    normalized = (quality or DEFAULT_QUALITY).strip().upper()
    if normalized not in mapping:
        raise DeemixError(f"Unsupported quality: {quality}")
    return mapping[normalized]


def _connect():
    from deezer import Deezer

    config = load_config()
    if not config["arl"]:
        raise DeemixError("Deezer ARL token is not configured. Add it in Settings.")

    dz = Deezer()
    try:
        logged_in = dz.login_via_arl(config["arl"])
    except Exception as exc:
        raise DeemixError(f"Failed to connect to Deezer: {exc}") from exc
    if not logged_in:
        raise DeemixError("Deezer login failed. The ARL token may be invalid or expired.")
    return dz


def _normalize_track_result(item: dict[str, Any]) -> dict[str, Any]:
    album = item.get("album") or {}
    artist = item.get("artist") or {}
    return {
        "deemix_id": str(item.get("id", "")),
        "type": "track",
        "title": item.get("title") or "",
        "artist": artist.get("name") or "",
        "album": album.get("title") or "",
        "duration_seconds": int(item.get("duration") or 0),
        "cover_url": album.get("cover_medium") or album.get("cover") or "",
    }


def _normalize_album_result(item: dict[str, Any]) -> dict[str, Any]:
    artist = item.get("artist") or {}
    return {
        "deemix_id": str(item.get("id", "")),
        "type": "album",
        "title": item.get("title") or "",
        "artist": artist.get("name") or "",
        "album": item.get("title") or "",
        "duration_seconds": 0,
        "cover_url": item.get("cover_medium") or item.get("cover") or "",
    }


def _normalize_artist_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "deemix_id": str(item.get("id", "")),
        "type": "artist",
        "title": item.get("name") or "",
        "artist": item.get("name") or "",
        "album": "",
        "duration_seconds": 0,
        "cover_url": item.get("picture_medium") or item.get("picture") or "",
    }


def search(query: str, limit: int = 25) -> list[dict[str, Any]]:
    """Search tracks, albums, and artists, and interleave the three ranked
    lists round-robin so the combined result reads as one relevance-ordered
    list instead of three separately-scrollable sections."""
    from deezer.errors import APIError

    normalized_query = (query or "").strip()
    if not normalized_query:
        return []

    dz = _connect()
    try:
        tracks = dz.api.search_track(normalized_query, limit=limit).get("data", [])
        albums = dz.api.search_album(normalized_query, limit=limit).get("data", [])
        artists = dz.api.search_artist(normalized_query, limit=limit).get("data", [])
    except APIError as exc:
        raise DeemixError(f"Deezer search failed: {exc}") from exc

    tracks_n = [_normalize_track_result(item) for item in tracks]
    albums_n = [_normalize_album_result(item) for item in albums]
    artists_n = [_normalize_artist_result(item) for item in artists]

    merged: list[dict[str, Any]] = []
    for group in zip_longest(tracks_n, albums_n, artists_n):
        for item in group:
            if item is not None:
                merged.append(item)
    return merged


def album_tracks(album_id: str) -> list[dict[str, Any]]:
    """Return the track list for a Deezer album, so the UI can drill into an
    album from search results and download individual songs."""
    from deezer.errors import APIError

    normalized_id = (album_id or "").strip()
    if not normalized_id:
        return []

    dz = _connect()
    try:
        album = dz.api.get_album(normalized_id)
    except APIError as exc:
        raise DeemixError(f"Deezer lookup failed: {exc}") from exc

    cover = album.get("cover_medium") or album.get("cover") or ""
    album_title = album.get("title") or ""
    tracks = (album.get("tracks") or {}).get("data", [])

    results: list[dict[str, Any]] = []
    for item in tracks:
        normalized = _normalize_track_result(item)
        # get_album embeds tracks without their own album/cover objects; fill
        # them in from the parent album so cards render consistently.
        if not normalized["album"]:
            normalized["album"] = album_title
        if not normalized["cover_url"]:
            normalized["cover_url"] = cover
        results.append(normalized)
    return results


def artist_albums(artist_id: str) -> list[dict[str, Any]]:
    """Return the album list for a Deezer artist, so the UI can drill into an
    artist from search results and then into a specific album."""
    from deezer.errors import APIError

    normalized_id = (artist_id or "").strip()
    if not normalized_id:
        return []

    dz = _connect()
    try:
        artist = dz.api.get_artist(normalized_id)
        albums = dz.api.get_artist_albums(normalized_id, limit=100).get("data", [])
    except APIError as exc:
        raise DeemixError(f"Deezer lookup failed: {exc}") from exc

    artist_name = artist.get("name") or ""
    results: list[dict[str, Any]] = []
    for item in albums:
        normalized = _normalize_album_result(item)
        if not normalized["artist"]:
            normalized["artist"] = artist_name
        results.append(normalized)
    return results


# ---------------------------------------------------------------------------
# Downloads run in background threads so the API can respond immediately and
# the frontend can poll for live per-item progress instead of blocking on a
# single request for the whole download.
# ---------------------------------------------------------------------------

_JOBS_LOCK = threading.Lock()
_JOBS: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_MAX_JOBS = 20


def _new_job(items: list[dict[str, Any]], quality: str, mountpoint: str | None) -> dict[str, Any]:
    job_items = [
        {
            "id": str(item.get("id", "")).strip(),
            "type": str(item.get("type", "track")).strip().lower(),
            "title": str(item.get("title", "") or ""),
            "artist": str(item.get("artist", "") or ""),
            "status": "queued",
            "progress": 0,
            "error": "",
        }
        for item in items
    ]
    job = {
        "job_id": uuid_lib.uuid4().hex,
        "quality": quality,
        "mountpoint": mountpoint or "",
        "status": "queued",
        "items": job_items,
        "added_to_ipod_count": 0,
        "ipod_message": "",
        "message": "",
        "created_at": time.time(),
    }
    with _JOBS_LOCK:
        _JOBS[job["job_id"]] = job
        while len(_JOBS) > _MAX_JOBS:
            _JOBS.popitem(last=False)
    return job


def _update_job(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job:
            job.update(fields)


def _update_job_item(job_id: str, index: int, **fields: Any) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job:
            job["items"][index].update(fields)


def get_jobs() -> list[dict[str, Any]]:
    with _JOBS_LOCK:
        return [dict(job, items=[dict(item) for item in job["items"]]) for job in reversed(_JOBS.values())]


def get_job(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return dict(job, items=[dict(item) for item in job["items"]]) if job else None


def connect_deezer():
    """Public accessor for the logged-in Deezer session, so other services
    (Spotify playlist sync) can reuse the configured ARL without duplicating
    the login handling."""
    return _connect()


def start_download_job(items: list[dict[str, Any]], quality: str = DEFAULT_QUALITY, mountpoint: str | None = None) -> str:
    job = _new_job(items, quality, mountpoint)
    thread = threading.Thread(target=_run_download_job, args=(job["job_id"],), daemon=True)
    thread.start()
    return job["job_id"]


def _run_download_job(job_id: str) -> None:
    from deemix.downloader import Downloader
    from deemix.errors import GenerationError
    from deemix.itemgen import generateAlbumItem, generateArtistItem, generateTrackItem
    from deemix.settings import DEFAULTS as DEEMIX_DEFAULTS

    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        items = list(job["items"])
        quality = job["quality"]
        mountpoint = job["mountpoint"]

    def fail_all(error_message: str) -> None:
        _update_job(job_id, status="error", message=error_message)
        for idx in range(len(items)):
            _update_job_item(job_id, idx, status="error", error=error_message)

    _update_job(job_id, status="downloading")

    try:
        settings = load_settings()
        music_directory = str(settings.get("music_directory", "") or "").strip()
        if not music_directory:
            fail_all("Music Directory is not configured in Settings.")
            return
        if not os.path.isdir(music_directory):
            fail_all(f"Music Directory not found: {music_directory}")
            return

        config = load_config()
        download_dir = os.path.join(music_directory, config["download_subdir"])
        os.makedirs(download_dir, exist_ok=True)

        bitrate = _quality_to_format(quality)
        dz = _connect()
    except DeemixError as exc:
        fail_all(str(exc))
        return
    except Exception as exc:
        fail_all(str(exc))
        return

    deemix_settings = dict(DEEMIX_DEFAULTS)
    deemix_settings["downloadLocation"] = download_dir
    deemix_settings["createPlaylistFolder"] = False
    deemix_settings["createAlbumFolder"] = True

    generators = {
        "track": generateTrackItem,
        "album": generateAlbumItem,
        "artist": generateArtistItem,
    }

    will_copy = bool((mountpoint or "").strip())
    downloaded_count = 0
    failed_count = 0
    downloaded_paths: list[str] = []
    success_indices: list[int] = []

    for index, item in enumerate(items):
        item_id = item["id"]
        item_type = item["type"]
        if not item_id or item_type not in generators:
            _update_job_item(job_id, index, status="error", error="Invalid item.")
            failed_count += 1
            continue

        _update_job_item(job_id, index, status="downloading")

        try:
            generated = generators[item_type](dz, item_id, bitrate)
        except GenerationError as exc:
            _update_job_item(job_id, index, status="error", error=exc.message)
            failed_count += 1
            continue
        except Exception as exc:
            _update_job_item(job_id, index, status="error", error=str(exc))
            failed_count += 1
            continue

        # generateArtistItem returns a list of per-album download objects
        # (the artist's whole discography); the other generators return one.
        download_objects = generated if item_type == "artist" else [generated]
        release_count = len(download_objects) or 1
        sub_failures: list[str] = []
        sub_success_count = 0

        for release_index, download_object in enumerate(download_objects):
            downloader = Downloader(dz, download_object, deemix_settings)
            download_thread = threading.Thread(target=downloader.start, daemon=True)
            download_thread.start()
            while download_thread.is_alive():
                release_progress = getattr(download_object, "progress", 0) or 0
                overall_progress = int((release_index + release_progress / 100) / release_count * 100)
                _update_job_item(job_id, index, progress=min(overall_progress, 99))
                download_thread.join(timeout=0.4)

            if download_object.failed:
                error_messages = [
                    str(error.get("message", error)) if isinstance(error, dict) else str(error)
                    for error in download_object.errors
                ]
                sub_failures.append("; ".join(error_messages) or "Download failed.")
                continue

            sub_success_count += 1
            for file_info in download_object.files:
                path = file_info.get("path") or file_info.get("downloadPath")
                if path:
                    downloaded_paths.append(path)

        if sub_success_count:
            downloaded_count += 1
            success_indices.append(index)
            # The file is downloaded but not yet on the device; hold it in the
            # intermediate "copying" state until gpod-cp runs below (or mark it
            # "done" straight away when there's no iPod to copy to).
            _update_job_item(
                job_id,
                index,
                status="copying" if will_copy else "done",
                progress=100,
                error="; ".join(sub_failures) if sub_failures else "",
            )
        else:
            failed_count += 1
            _update_job_item(
                job_id,
                index,
                status="error",
                progress=0,
                error="; ".join(sub_failures) or "Download failed.",
            )

    message = f"Downloaded {downloaded_count} item(s) to {download_dir}."
    if failed_count:
        message = f"{message} {failed_count} item(s) failed."

    if will_copy and downloaded_paths:
        _update_job(job_id, status="copying")
        ipod_info = _add_downloads_to_ipod(downloaded_paths, mountpoint, download_dir)
        for idx in success_indices:
            if ipod_info["copied"]:
                _update_job_item(job_id, idx, status="done", progress=100)
            else:
                _update_job_item(job_id, idx, status="error", error=ipod_info["ipod_message"])
    else:
        # No copy will run (no iPod, or nothing actually landed on disk). Resolve
        # any successful item still flagged "copying" to "done".
        ipod_info = _add_downloads_to_ipod(downloaded_paths, mountpoint, download_dir)
        for idx in success_indices:
            _update_job_item(job_id, idx, status="done", progress=100)

    _update_job(
        job_id,
        status="error" if failed_count and not downloaded_count else "done",
        message=message,
        added_to_ipod_count=ipod_info["added_to_ipod_count"],
        ipod_message=ipod_info["ipod_message"],
    )


def _add_downloads_to_ipod(
    downloaded_paths: list[str], mountpoint: str | None, download_dir: str | None = None
) -> dict[str, Any]:
    if not downloaded_paths:
        return {"added_to_ipod_count": 0, "ipod_message": "", "copied": False}

    normalized_mountpoint = (mountpoint or "").strip()
    if not normalized_mountpoint:
        return {
            "added_to_ipod_count": 0,
            "ipod_message": "No iPod connected — downloaded files were not added.",
            "copied": False,
        }

    try:
        ipod_result = add_tracks_to_ipod(
            mountpoint=normalized_mountpoint,
            file_paths=downloaded_paths,
            convert_to_alac=True,
        )
    except GpodError as exc:
        return {
            "added_to_ipod_count": 0,
            "ipod_message": f"Downloaded, but adding to iPod failed: {exc}",
            "copied": False,
        }
    except Exception as exc:
        return {
            "added_to_ipod_count": 0,
            "ipod_message": f"Downloaded, but adding to iPod failed: {exc}",
            "copied": False,
        }

    added_count = int(ipod_result.get("requested_count", 0))
    # The downloads are only staged locally in the deemix download dir; once they
    # are on the device, delete the whole album folder deemix created (audio plus
    # cover art / lyrics) so the staging area doesn't accumulate copies and
    # auto-sync can't re-add them.
    removed_count = _cleanup_downloaded_files(downloaded_paths, download_dir)
    message = f"Added {added_count} track(s) to the iPod."
    if removed_count:
        message = f"{message} Removed {removed_count} local file(s)."
    return {
        "added_to_ipod_count": added_count,
        "ipod_message": message,
        "copied": True,
    }


def _cleanup_downloaded_files(paths: list[str], download_dir: str | None) -> int:
    """Delete the staged downloads. When a file lives in its own album folder
    inside the download dir, remove that whole folder (deemix also drops cover
    art, lyrics and playlist files there, which os.remove alone would leave
    behind). Never deletes the download dir itself or anything outside it."""
    boundary = os.path.abspath(download_dir) if download_dir else None
    removed = 0
    folder_track_counts: dict[str, int] = {}
    loose_files: list[str] = []

    for path in paths:
        abs_path = os.path.abspath(path)
        parent = os.path.dirname(abs_path)
        if boundary and parent.startswith(boundary + os.sep) and parent != boundary:
            folder_track_counts[parent] = folder_track_counts.get(parent, 0) + 1
        else:
            loose_files.append(abs_path)

    for path in loose_files:
        try:
            os.remove(path)
        except OSError:
            continue
        removed += 1

    for folder, track_count in folder_track_counts.items():
        try:
            shutil.rmtree(folder)
        except OSError:
            continue
        removed += track_count
        # Prune any now-empty wrapper dirs left between the album folder and the
        # download dir, but never the download dir itself.
        current = os.path.dirname(folder)
        while boundary and current.startswith(boundary + os.sep) and current != boundary:
            try:
                os.rmdir(current)
            except OSError:
                break
            current = os.path.dirname(current)

    return removed


def _read_json_file(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _write_json_file_atomic(path: str, data: Any) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".tmp_deemix_", dir=directory)
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
