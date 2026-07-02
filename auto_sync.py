from __future__ import annotations

import os
from typing import Any

from ipod_service import add_tracks
from settings_service import (
    changed_audio_files,
    load_settings,
    load_sync_state,
    save_sync_state,
    scan_audio_files,
)


def run_auto_sync_if_enabled(mountpoint: str) -> dict[str, Any]:
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
