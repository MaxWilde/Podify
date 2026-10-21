from __future__ import annotations

from flask import Blueprint, jsonify, request

from spotify_service import (
    SpotifyError,
    add_playlist,
    ensure_scheduler,
    get_status,
    get_sync_jobs,
    list_playlists,
    playlist_tracks,
    remove_playlist,
    reset_playlist_sync_state,
    save_config,
    set_playlist_auto_sync,
    start_sync,
    sync_all,
)

spotify_bp = Blueprint("spotify", __name__, url_prefix="/api/spotify")

# Background auto-sync polling starts with the app (single gunicorn worker).
ensure_scheduler()


@spotify_bp.route("/config", methods=["GET"])
def get_config_route() -> object:
    return jsonify(get_status())


@spotify_bp.route("/config", methods=["POST"])
def save_config_route() -> tuple[object, int] | object:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid JSON payload."}), 400

    try:
        save_config(payload)
    except SpotifyError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Failed to save Spotify config."}), 500

    return jsonify(get_status())


@spotify_bp.route("/playlists", methods=["GET"])
def list_playlists_route() -> object:
    return jsonify({"playlists": list_playlists()})


@spotify_bp.route("/playlists", methods=["POST"])
def add_playlist_route() -> tuple[object, int] | object:
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url", "") or "").strip()
    if not url:
        return jsonify({"error": "Field 'url' is required."}), 400

    try:
        add_playlist(url)
    except SpotifyError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify({"playlists": list_playlists()}), 201


@spotify_bp.route("/playlists/<playlist_id>", methods=["DELETE"])
def remove_playlist_route(playlist_id: str) -> tuple[object, int] | object:
    try:
        remove_playlist(playlist_id.strip())
    except SpotifyError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify({"playlists": list_playlists()})


@spotify_bp.route("/playlists/<playlist_id>/tracks", methods=["GET"])
def playlist_tracks_route(playlist_id: str) -> tuple[object, int] | object:
    force = request.args.get("refresh", "").strip().lower() in {"1", "true", "yes"}
    try:
        result = playlist_tracks(playlist_id.strip(), force=force)
    except SpotifyError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify(result)


@spotify_bp.route("/playlists/<playlist_id>/auto-sync", methods=["POST"])
def set_auto_sync_route(playlist_id: str) -> tuple[object, int] | object:
    payload = request.get_json(silent=True) or {}
    if "enabled" not in payload:
        return jsonify({"error": "Field 'enabled' is required."}), 400

    try:
        set_playlist_auto_sync(playlist_id.strip(), bool(payload.get("enabled")))
    except SpotifyError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify({"playlists": list_playlists()})


@spotify_bp.route("/playlists/<playlist_id>/reset", methods=["POST"])
def reset_playlist_route(playlist_id: str) -> tuple[object, int] | object:
    try:
        reset_playlist_sync_state(playlist_id.strip())
    except SpotifyError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify({"playlists": list_playlists()})


@spotify_bp.route("/playlists/<playlist_id>/sync", methods=["POST"])
def sync_playlist_route(playlist_id: str) -> tuple[object, int] | object:
    payload = request.get_json(silent=True) or {}
    mountpoint = str(payload.get("mountpoint", "") or "").strip()
    quality = str(payload.get("quality", "") or "").strip()

    try:
        job_id = start_sync(playlist_id.strip(), mountpoint or None, quality or None)
    except SpotifyError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify({"job_id": job_id}), 202


@spotify_bp.route("/sync-all", methods=["POST"])
def sync_all_route() -> tuple[object, int] | object:
    payload = request.get_json(silent=True) or {}
    mountpoint = str(payload.get("mountpoint", "") or "").strip()
    quality = str(payload.get("quality", "") or "").strip()

    try:
        job_ids = sync_all(mountpoint or None, quality or None)
    except SpotifyError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify({"job_ids": job_ids}), 202


@spotify_bp.route("/jobs", methods=["GET"])
def list_jobs_route() -> object:
    return jsonify({"jobs": get_sync_jobs()})
