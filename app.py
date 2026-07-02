from __future__ import annotations

from io import BytesIO
import os
import tempfile

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

from album_art import CoverArtError, load_cover
from ipod_service import (
    GpodError,
    add_tracks,
    add_tracks_to_playlist,
    create_playlist,
    delete_playlist,
    delete_tracks,
    load_library,
    remove_tracks_from_playlist,
)
from settings_service import changed_audio_files
from settings_service import load_settings
from settings_service import load_sync_state
from settings_service import save_settings
from settings_service import save_sync_state
from settings_service import scan_audio_files


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB
ALLOWED_UPLOAD_EXTENSIONS = {
    ".mp3",
    ".m4a",
    ".aac",
    ".wav",
    ".aiff",
    ".aif",
    ".flac",
    ".ogg",
    ".opus",
    ".m4b",
}


def _is_supported_upload(filename: str, mimetype: str) -> bool:
    _, ext = os.path.splitext(filename)
    if ext.lower() not in ALLOWED_UPLOAD_EXTENSIONS:
        return False
    mime = (mimetype or "").strip().lower()
    if mime.startswith("image/"):
        return False
    return True


def _run_auto_sync_if_enabled(mountpoint: str) -> dict[str, object]:
    settings = load_settings()
    if not bool(settings.get("auto_sync_enabled", False)):
        return {"status": "disabled"}

    music_directory = str(settings.get("music_directory", "") or "").strip()
    if not music_directory:
        return {"status": "skipped", "message": "Auto-sync enabled but Music Directory is empty."}
    if not os.path.isdir(music_directory):
        return {"status": "skipped", "message": f"Music Directory not found: {music_directory}"}

    previous_state = load_sync_state()
    _, current_index = scan_audio_files(music_directory)
    if not current_index:
        save_sync_state({"files": {}})
        return {"status": "noop", "message": "Auto-sync: no FLAC files found in Music Directory."}

    to_sync = changed_audio_files(previous_state, current_index)
    if not to_sync:
        save_sync_state({"files": current_index})
        return {"status": "noop", "message": "Auto-sync: no new or changed FLAC files in Music Directory."}

    result = add_tracks(
        mountpoint=mountpoint,
        file_paths=to_sync,
        convert_to_alac=True,
    )

    deleted_count = 0
    if bool(settings.get("delete_after_sync", False)):
        for path in to_sync:
            try:
                os.remove(path)
                deleted_count += 1
                current_index.pop(path, None)
            except OSError:
                continue
        _remove_empty_dirs(music_directory)

    save_sync_state({"files": current_index})

    added_count = int(result.get("requested_count", 0))
    message = f"Auto-sync added {added_count} file(s) from Music Directory."
    if deleted_count:
        message = f"{message} Deleted {deleted_count} source file(s)."
    return {
        "status": "synced",
        "added_count": added_count,
        "deleted_source_count": deleted_count,
        "scanned_count": len(current_index),
        "message": message,
    }


def _remove_empty_dirs(root: str) -> None:
    normalized_root = os.path.abspath(root)
    for current_root, dirs, _files in os.walk(normalized_root, topdown=False):
        for directory in dirs:
            path = os.path.join(current_root, directory)
            try:
                os.rmdir(path)
            except OSError:
                continue


@app.route("/")
def index() -> str:
    default_mountpoint = os.environ.get("DEFAULT_MOUNTPOINT", "/ipod")
    asset_version = os.environ.get("ASSET_VERSION", "20260227-settings")
    return render_template(
        "index.html",
        default_mountpoint=default_mountpoint,
        asset_version=asset_version,
    )


@app.route("/api/library")
def library() -> tuple[object, int] | object:
    mountpoint = request.args.get("mountpoint", "").strip()
    if not mountpoint:
        return jsonify({"error": "Query parameter 'mountpoint' is required."}), 400

    try:
        payload = load_library(mountpoint)
        resolved_mountpoint = str(payload.get("mountpoint") or mountpoint)

        sync_payload: dict[str, object] | None = None
        try:
            sync_payload = _run_auto_sync_if_enabled(resolved_mountpoint)
        except GpodError as exc:
            sync_payload = {"status": "error", "message": f"Auto-sync failed: {exc}"}
        except Exception as exc:
            sync_payload = {"status": "error", "message": f"Auto-sync failed: {exc}"}

        if sync_payload and sync_payload.get("status") == "synced":
            payload = load_library(resolved_mountpoint)

        if sync_payload and sync_payload.get("status") not in {"disabled"}:
            payload["auto_sync"] = sync_payload
    except GpodError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify(payload)


@app.route("/api/cover")
def cover() -> tuple[object, int] | object:
    mountpoint = request.args.get("mountpoint", "").strip()
    ipod_path = request.args.get("ipod_path", "").strip()
    if not mountpoint:
        return jsonify({"error": "Query parameter 'mountpoint' is required."}), 400
    if not ipod_path:
        return jsonify({"error": "Query parameter 'ipod_path' is required."}), 400

    try:
        image_bytes, mime_type = load_cover(mountpoint, ipod_path)
    except CoverArtError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return send_file(
        BytesIO(image_bytes),
        mimetype=mime_type,
        as_attachment=False,
        max_age=3600,
        conditional=True,
    )


@app.route("/api/delete-tracks", methods=["POST"])
def remove_tracks() -> tuple[object, int] | object:
    payload = request.get_json(silent=True) or {}
    mountpoint = str(payload.get("mountpoint", "")).strip()
    ipod_paths = payload.get("ipod_paths", [])
    if not mountpoint:
        return jsonify({"error": "Field 'mountpoint' is required."}), 400
    if not isinstance(ipod_paths, list):
        return jsonify({"error": "Field 'ipod_paths' must be a list."}), 400

    try:
        result = delete_tracks(mountpoint, ipod_paths)
    except GpodError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify(
        {
            "deleted_count": result["requested_count"],
            "message": f"Deleted {result['requested_count']} track(s).",
        }
    )


@app.route("/api/add-tracks", methods=["POST"])
def add_uploaded_tracks() -> tuple[object, int] | object:
    mountpoint = request.form.get("mountpoint", "").strip()
    files = request.files.getlist("files")

    if not mountpoint:
        return jsonify({"error": "Field 'mountpoint' is required."}), 400
    if not files:
        return jsonify({"error": "At least one file is required."}), 400

    uploaded_paths: list[str] = []
    skipped_count = 0
    with tempfile.TemporaryDirectory(prefix="classicpod_upload_") as upload_dir:
        for index, storage in enumerate(files):
            original_name = storage.filename or f"track_{index}"
            safe_name = secure_filename(original_name) or f"track_{index}"
            if not _is_supported_upload(safe_name, storage.mimetype or ""):
                skipped_count += 1
                continue
            path = os.path.join(upload_dir, f"{index:04d}_{safe_name}")
            storage.save(path)
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                uploaded_paths.append(path)

        if not uploaded_paths:
            return jsonify({"error": "No supported audio files were uploaded."}), 400

        try:
            result = add_tracks(
                mountpoint=mountpoint,
                file_paths=uploaded_paths,
                convert_to_alac=True,
            )
        except GpodError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:
            return jsonify({"error": "Unexpected server error."}), 500

    converted_count = int(result.get("converted_count", 0))
    conversion_failed_count = int(result.get("conversion_failed_count", 0))
    conversion_failures = result.get("conversion_failures", [])
    added_count = int(result.get("requested_count", 0))
    skipped_suffix = f" Skipped {skipped_count} non-audio file(s)." if skipped_count else ""
    if converted_count:
        phase_message = (
            f"Phase 1: converted {converted_count} FLAC file(s) to ALAC. "
            f"Phase 2: copied {added_count} file(s) to iPod."
        )
    else:
        phase_message = f"Phase 1: no FLAC conversion needed. Phase 2: copied {added_count} file(s) to iPod."
    if conversion_failed_count:
        failed_names = [
            str(item.get("source", "")).strip()
            for item in conversion_failures
            if isinstance(item, dict)
        ]
        failed_names = [name for name in failed_names if name]
        listed = ", ".join(failed_names[:3])
        if len(failed_names) > 3:
            listed = f"{listed}, ..."
        details = f" ({listed})" if listed else ""
        phase_message = (
            f"{phase_message} Conversion failed for {conversion_failed_count} FLAC file(s){details}; "
            "those files were added without conversion."
        )
    return jsonify(
        {
            "added_count": added_count,
            "converted_count": converted_count,
            "conversion_failed_count": conversion_failed_count,
            "skipped_count": skipped_count,
            "message": f"{phase_message}{skipped_suffix}",
        }
    )


@app.route("/api/playlists/create", methods=["POST"])
def create_playlist_route() -> tuple[object, int] | object:
    payload = request.get_json(silent=True) or {}
    mountpoint = str(payload.get("mountpoint", "")).strip()
    playlist_name = str(payload.get("playlist_name", "")).strip()
    if not mountpoint:
        return jsonify({"error": "Field 'mountpoint' is required."}), 400
    if not playlist_name:
        return jsonify({"error": "Field 'playlist_name' is required."}), 400

    try:
        create_playlist(mountpoint, playlist_name)
    except GpodError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify({"message": f'Playlist "{playlist_name}" created.'})


@app.route("/api/playlists/delete", methods=["POST"])
def delete_playlist_route() -> tuple[object, int] | object:
    payload = request.get_json(silent=True) or {}
    mountpoint = str(payload.get("mountpoint", "")).strip()
    playlist_name = str(payload.get("playlist_name", "")).strip()
    if not mountpoint:
        return jsonify({"error": "Field 'mountpoint' is required."}), 400
    if not playlist_name:
        return jsonify({"error": "Field 'playlist_name' is required."}), 400

    try:
        delete_playlist(mountpoint, playlist_name)
    except GpodError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify({"message": f'Playlist "{playlist_name}" deleted.'})


@app.route("/api/playlists/add-tracks", methods=["POST"])
def add_tracks_to_playlist_route() -> tuple[object, int] | object:
    payload = request.get_json(silent=True) or {}
    mountpoint = str(payload.get("mountpoint", "")).strip()
    playlist_name = str(payload.get("playlist_name", "")).strip()
    track_ids = payload.get("track_ids", [])
    if not mountpoint:
        return jsonify({"error": "Field 'mountpoint' is required."}), 400
    if not playlist_name:
        return jsonify({"error": "Field 'playlist_name' is required."}), 400
    if not isinstance(track_ids, list):
        return jsonify({"error": "Field 'track_ids' must be a list."}), 400

    try:
        result = add_tracks_to_playlist(mountpoint, playlist_name, track_ids)
    except GpodError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify(
        {
            "added_count": result["requested_count"],
            "message": f'Added {result["requested_count"]} track(s) to "{playlist_name}".',
        }
    )


@app.route("/api/playlists/remove-tracks", methods=["POST"])
def remove_tracks_from_playlist_route() -> tuple[object, int] | object:
    payload = request.get_json(silent=True) or {}
    mountpoint = str(payload.get("mountpoint", "")).strip()
    playlist_name = str(payload.get("playlist_name", "")).strip()
    track_ids = payload.get("track_ids", [])
    if not mountpoint:
        return jsonify({"error": "Field 'mountpoint' is required."}), 400
    if not playlist_name:
        return jsonify({"error": "Field 'playlist_name' is required."}), 400
    if not isinstance(track_ids, list):
        return jsonify({"error": "Field 'track_ids' must be a list."}), 400

    try:
        result = remove_tracks_from_playlist(mountpoint, playlist_name, track_ids)
    except GpodError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify(
        {
            "removed_count": result["requested_count"],
            "message": f'Removed {result["requested_count"]} track(s) from "{playlist_name}".',
        }
    )


@app.route("/api/settings", methods=["GET"])
def get_settings_route() -> object:
    return jsonify(load_settings())


@app.route("/api/settings", methods=["POST"])
def save_settings_route() -> tuple[object, int] | object:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid JSON payload."}), 400

    try:
        saved = save_settings(payload)
    except Exception:
        return jsonify({"error": "Failed to save settings."}), 500

    return jsonify(saved)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
