import { apiFetch } from "./client";

export interface PlaylistMessageResult {
  message: string;
}

export function createPlaylist(mountpoint: string, playlistName: string): Promise<PlaylistMessageResult> {
  return apiFetch<PlaylistMessageResult>("/api/playlists/create", {
    method: "POST",
    body: JSON.stringify({ mountpoint, playlist_name: playlistName }),
  });
}

export function deletePlaylist(mountpoint: string, playlistName: string): Promise<PlaylistMessageResult> {
  return apiFetch<PlaylistMessageResult>("/api/playlists/delete", {
    method: "POST",
    body: JSON.stringify({ mountpoint, playlist_name: playlistName }),
  });
}

export interface AddTracksToPlaylistResult {
  added_count: number;
  message: string;
}

export function addTracksToPlaylist(
  mountpoint: string,
  playlistName: string,
  trackIds: number[],
): Promise<AddTracksToPlaylistResult> {
  return apiFetch<AddTracksToPlaylistResult>("/api/playlists/add-tracks", {
    method: "POST",
    body: JSON.stringify({ mountpoint, playlist_name: playlistName, track_ids: trackIds }),
  });
}

export interface RemoveTracksFromPlaylistResult {
  removed_count: number;
  message: string;
}

export function removeTracksFromPlaylist(
  mountpoint: string,
  playlistName: string,
  trackIds: number[],
): Promise<RemoveTracksFromPlaylistResult> {
  return apiFetch<RemoveTracksFromPlaylistResult>("/api/playlists/remove-tracks", {
    method: "POST",
    body: JSON.stringify({ mountpoint, playlist_name: playlistName, track_ids: trackIds }),
  });
}
