from __future__ import annotations

from flask import Blueprint, jsonify, request

from discover_service import (
    DiscoverError,
    add_album,
    block_artist,
    dismiss_album,
    ensure_scheduler,
    extend_album,
    forget_album,
    get_preferences,
    get_suggestions,
    keep_album,
    list_albums,
    list_blocked_artists,
    remember_mountpoint,
    remove_album,
    retry_album,
    save_preferences,
    start_generation,
    sweep_in_background,
    unblock_artist,
)
from ipod_service import GpodError

discover_bp = Blueprint("discover", __name__, url_prefix="/api/discover")

# Trial expiry runs in the background with the app (single gunicorn worker).
ensure_scheduler()


def _json_payload() -> dict:
    payload = request.get_json(silent=True) or {}
    return payload if isinstance(payload, dict) else {}


def _error(exc: Exception) -> tuple[object, int]:
    if isinstance(exc, (DiscoverError, GpodError)):
        return jsonify({"error": str(exc)}), 400
    return jsonify({"error": "Unexpected server error."}), 500


@discover_bp.route("/preferences", methods=["GET"])
def get_preferences_route() -> object:
    return jsonify(get_preferences())


@discover_bp.route("/preferences", methods=["POST"])
def save_preferences_route() -> tuple[object, int] | object:
    try:
        return jsonify(save_preferences(_json_payload()))
    except Exception as exc:
        return _error(exc)


@discover_bp.route("/suggestions", methods=["GET"])
def get_suggestions_route() -> object:
    return jsonify(get_suggestions())


@discover_bp.route("/suggestions/refresh", methods=["POST"])
def refresh_suggestions_route() -> tuple[object, int] | object:
    payload = _json_payload()
    mountpoint = str(payload.get("mountpoint", "") or "").strip()
    temperature = payload.get("temperature")
    try:
        start_generation(mountpoint, float(temperature) if temperature is not None else None)
    except (TypeError, ValueError):
        return jsonify({"error": "Field 'temperature' must be a number between 0 and 1."}), 400
    except Exception as exc:
        return _error(exc)
    return jsonify(get_suggestions()), 202


@discover_bp.route("/suggestions/<album_id>/dismiss", methods=["POST"])
def dismiss_route(album_id: str) -> tuple[object, int] | object:
    try:
        dismiss_album(album_id.strip())
    except Exception as exc:
        return _error(exc)
    return jsonify(get_suggestions())


@discover_bp.route("/blocked-artists", methods=["GET"])
def list_blocked_route() -> object:
    return jsonify({"artists": list_blocked_artists()})


@discover_bp.route("/blocked-artists", methods=["POST"])
def block_artist_route() -> tuple[object, int] | object:
    payload = _json_payload()
    try:
        block_artist(str(payload.get("id", "") or "").strip(), str(payload.get("name", "") or "").strip())
    except Exception as exc:
        return _error(exc)
    return jsonify({"artists": list_blocked_artists()})


@discover_bp.route("/blocked-artists/<artist_id>", methods=["DELETE"])
def unblock_artist_route(artist_id: str) -> tuple[object, int] | object:
    try:
        unblock_artist(artist_id.strip())
    except Exception as exc:
        return _error(exc)
    return jsonify({"artists": list_blocked_artists()})


@discover_bp.route("/albums", methods=["GET"])
def list_albums_route() -> object:
    # The UI polls this while it's open, which doubles as the moment an iPod is
    # known to be connected: remember it for the scheduler and expire anything
    # that came due while the device was unplugged.
    mountpoint = request.args.get("mountpoint", "").strip()
    if mountpoint:
        remember_mountpoint(mountpoint)
        sweep_in_background(mountpoint)
    return jsonify(list_albums())


@discover_bp.route("/albums", methods=["POST"])
def add_album_route() -> tuple[object, int] | object:
    payload = _json_payload()
    album = payload.get("album")
    if not isinstance(album, dict):
        return jsonify({"error": "Field 'album' must be an object."}), 400
    try:
        add_album(
            album,
            str(payload.get("mode", "") or "trial").strip().lower(),
            str(payload.get("mountpoint", "") or ""),
            str(payload.get("quality", "") or "") or None,
            str(payload.get("type", "") or "album").strip().lower(),
        )
    except Exception as exc:
        return _error(exc)
    return jsonify(list_albums()), 202


@discover_bp.route("/albums/<album_id>/keep", methods=["POST"])
def keep_album_route(album_id: str) -> tuple[object, int] | object:
    payload = _json_payload()
    try:
        keep_album(album_id, bool(payload.get("upgrade", False)), str(payload.get("quality", "") or "") or None)
    except Exception as exc:
        return _error(exc)
    return jsonify(list_albums())


@discover_bp.route("/albums/<album_id>/extend", methods=["POST"])
def extend_album_route(album_id: str) -> tuple[object, int] | object:
    payload = _json_payload()
    try:
        extend_album(album_id, payload.get("days", 7))
    except Exception as exc:
        return _error(exc)
    return jsonify(list_albums())


@discover_bp.route("/albums/<album_id>/remove", methods=["POST"])
def remove_album_route(album_id: str) -> tuple[object, int] | object:
    payload = _json_payload()
    try:
        remove_album(album_id, str(payload.get("mountpoint", "") or "") or None)
    except Exception as exc:
        return _error(exc)
    return jsonify(list_albums())


@discover_bp.route("/albums/<album_id>/retry", methods=["POST"])
def retry_album_route(album_id: str) -> tuple[object, int] | object:
    payload = _json_payload()
    try:
        retry_album(album_id, str(payload.get("mountpoint", "") or ""))
    except Exception as exc:
        return _error(exc)
    return jsonify(list_albums()), 202


@discover_bp.route("/albums/<album_id>", methods=["DELETE"])
def forget_album_route(album_id: str) -> tuple[object, int] | object:
    try:
        forget_album(album_id)
    except Exception as exc:
        return _error(exc)
    return jsonify(list_albums())
