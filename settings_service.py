from __future__ import annotations

import json
import os
import tempfile
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "music_directory": "",
    "auto_sync_enabled": False,
    "delete_after_sync": False,
}

AUTO_SYNC_EXTENSIONS = {".flac"}


def settings_path() -> str:
    configured = os.environ.get("CLASSICPOD_SETTINGS_PATH", "").strip()
    if configured:
        return configured
    return os.path.join(os.getcwd(), ".classicpod_settings.json")


def sync_state_path() -> str:
    configured = os.environ.get("CLASSICPOD_SYNC_STATE_PATH", "").strip()
    if configured:
        return configured
    return os.path.join(os.getcwd(), ".classicpod_sync_state.json")


def load_settings() -> dict[str, Any]:
    data = _read_json_file(settings_path())
    if not isinstance(data, dict):
        return dict(DEFAULT_SETTINGS)

    merged = dict(DEFAULT_SETTINGS)
    merged["music_directory"] = str(data.get("music_directory", "") or "")
    merged["auto_sync_enabled"] = bool(data.get("auto_sync_enabled", False))
    merged["delete_after_sync"] = bool(data.get("delete_after_sync", False))
    return merged


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    current = load_settings()
    merged = dict(current)

    if "music_directory" in updates:
        merged["music_directory"] = str(updates.get("music_directory", "") or "").strip()
    if "auto_sync_enabled" in updates:
        merged["auto_sync_enabled"] = bool(updates.get("auto_sync_enabled"))
    if "delete_after_sync" in updates:
        merged["delete_after_sync"] = bool(updates.get("delete_after_sync"))

    _write_json_file_atomic(settings_path(), merged)
    return merged


def load_sync_state() -> dict[str, dict[str, int]]:
    data = _read_json_file(sync_state_path())
    if not isinstance(data, dict):
        return {"files": {}}
    files = data.get("files")
    if not isinstance(files, dict):
        return {"files": {}}

    normalized: dict[str, dict[str, int]] = {}
    for path, meta in files.items():
        if not isinstance(path, str):
            continue
        if not isinstance(meta, dict):
            continue
        size = int(meta.get("size", -1))
        mtime_ns = int(meta.get("mtime_ns", -1))
        if size < 0 or mtime_ns < 0:
            continue
        normalized[path] = {"size": size, "mtime_ns": mtime_ns}
    return {"files": normalized}


def save_sync_state(state: dict[str, dict[str, int]]) -> None:
    files = state.get("files", {})
    if not isinstance(files, dict):
        files = {}
    _write_json_file_atomic(sync_state_path(), {"files": files})


def scan_audio_files(directory: str) -> tuple[list[str], dict[str, dict[str, int]]]:
    root = os.path.abspath(directory)
    if not os.path.isdir(root):
        return [], {}

    indexed: dict[str, dict[str, int]] = {}
    for current_root, _dirs, names in os.walk(root):
        for name in names:
            ext = os.path.splitext(name)[1].lower()
            if ext not in AUTO_SYNC_EXTENSIONS:
                continue
            path = os.path.join(current_root, name)
            try:
                stat_result = os.stat(path)
            except OSError:
                continue
            indexed[path] = {
                "size": int(stat_result.st_size),
                "mtime_ns": int(stat_result.st_mtime_ns),
            }

    changed = sorted(indexed.keys())
    return changed, indexed


def changed_audio_files(
    previous: dict[str, dict[str, int]],
    current: dict[str, dict[str, int]],
) -> list[str]:
    previous_files = previous.get("files", {}) if isinstance(previous, dict) else {}
    changed: list[str] = []
    for path, meta in current.items():
        if previous_files.get(path) != meta:
            changed.append(path)
    return changed


def _read_json_file(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _write_json_file_atomic(path: str, data: Any) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".tmp_classicpod_", dir=directory)
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
