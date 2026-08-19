from __future__ import annotations

from io import BytesIO
import os
import shutil
import tempfile

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from album_art import CoverArtError, load_cover
from auto_sync import run_auto_sync_if_enabled
from deemix_routes import deemix_bp
from ipod_service import (
    GpodError,
    add_tracks,
    add_tracks_to_playlist,
    create_playlist,
    delete_playlist,
    delete_tracks,
    load_library,
    remove_tracks_from_playlist,
    resolve_ipod_root,
)
from settings_service import load_settings
from settings_service import save_settings
from spotify_routes import spotify_bp


app = Flask(__name__)
app.register_blueprint(deemix_bp)
app.register_blueprint(spotify_bp)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB

if os.environ.get("DEBUG", "").strip().lower() in {"1", "true", "yes"}:
    from flask_cors import CORS

    CORS(app, resources={r"/api/*": {"origins": "*"}})
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


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path: str) -> object:
    dist = os.path.join(app.root_path, "frontend", "dist")
    if path and os.path.exists(os.path.join(dist, path)):
        return send_from_directory(dist, path)
    return send_from_directory(dist, "index.html")


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
            sync_payload = run_auto_sync_if_enabled(resolved_mountpoint)
        except GpodError as exc:
            sync_payload = {"status": "error", "message": f"Auto-sync failed: {exc}"}
        except Exception as exc:
            sync_payload = {"status": "error", "message": f"Auto-sync failed: {exc}"}

        if sync_payload and sync_payload.get("status") == "synced":
            payload = load_library(resolved_mountpoint)

        if sync_payload and sync_payload.get("status") not in {"disabled"}:
            payload["auto_sync"] = sync_payload

        # Disk usage of the device the iPod is mounted on, for the storage bar.
        try:
            usage = shutil.disk_usage(resolved_mountpoint)
            payload["storage"] = {
                "total_bytes": int(usage.total),
                "used_bytes": int(usage.used),
                "free_bytes": int(usage.free),
            }
        except Exception:
            pass
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

    # Track ipod_paths are relative to the iPod root. When the database lives in
    # a discovered sub-root of the requested mountpoint, resolve to that same
    # root so the cover file is found — otherwise every cover 404s and the UI
    # shows placeholders even though the artwork is present on disk.
    mountpoint = resolve_ipod_root(mountpoint)

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
