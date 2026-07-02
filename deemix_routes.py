from __future__ import annotations

from flask import Blueprint, jsonify, request

from auto_sync import run_auto_sync_if_enabled
from deemix_service import DeemixError
from deemix_service import album_tracks, artist_albums
from deemix_service import get_jobs, get_status, save_config
from deemix_service import search as deemix_search
from deemix_service import start_download_job
from ipod_service import GpodError

deemix_bp = Blueprint("deemix", __name__, url_prefix="/api/deemix")


@deemix_bp.route("/config", methods=["GET"])
def get_config_route() -> object:
    return jsonify(get_status())


@deemix_bp.route("/config", methods=["POST"])
def save_config_route() -> tuple[object, int] | object:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid JSON payload."}), 400

    try:
        save_config(payload)
    except DeemixError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Failed to save deemix config."}), 500

    return jsonify(get_status())


@deemix_bp.route("/search", methods=["GET"])
def search_route() -> tuple[object, int] | object:
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Query parameter 'q' is required."}), 400

    try:
        results = deemix_search(query)
    except DeemixError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify({"results": results})


@deemix_bp.route("/album/<album_id>/tracks", methods=["GET"])
def album_tracks_route(album_id: str) -> tuple[object, int] | object:
    if not album_id.strip():
        return jsonify({"error": "Album id is required."}), 400

    try:
        results = album_tracks(album_id)
    except DeemixError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify({"results": results})


@deemix_bp.route("/artist/<artist_id>/albums", methods=["GET"])
def artist_albums_route(artist_id: str) -> tuple[object, int] | object:
    if not artist_id.strip():
        return jsonify({"error": "Artist id is required."}), 400

    try:
        results = artist_albums(artist_id)
    except DeemixError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify({"results": results})


@deemix_bp.route("/download", methods=["POST"])
def download_route() -> tuple[object, int] | object:
    payload = request.get_json(silent=True) or {}
    items = payload.get("items", [])
    quality = str(payload.get("quality", "") or "FLAC").strip().upper() or "FLAC"
    mountpoint = str(payload.get("mountpoint", "") or "").strip()

    if not isinstance(items, list) or not items:
        return jsonify({"error": "Field 'items' must be a non-empty list."}), 400
    if not all(isinstance(item, dict) for item in items):
        return jsonify({"error": "Each item must be an object with 'id' and 'type'."}), 400

    status = get_status()
    if not status["arl_configured"]:
        return jsonify({"error": "Deezer ARL token is not configured. Add it in Settings."}), 400

    try:
        job_id = start_download_job(items, quality, mountpoint or None)
    except DeemixError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify({"job_id": job_id}), 202


@deemix_bp.route("/downloads", methods=["GET"])
def list_downloads_route() -> object:
    return jsonify({"jobs": get_jobs()})


@deemix_bp.route("/trigger-sync", methods=["POST"])
def trigger_sync_route() -> tuple[object, int] | object:
    payload = request.get_json(silent=True) or {}
    mountpoint = str(payload.get("mountpoint", "")).strip()
    if not mountpoint:
        return jsonify({"error": "Field 'mountpoint' is required."}), 400

    try:
        result = run_auto_sync_if_enabled(mountpoint)
    except GpodError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unexpected server error."}), 500

    return jsonify(result)
