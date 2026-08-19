import { apiFetch, apiUrl } from "./client";
import type {
  DeemixQuality,
  SpotifyConfig,
  SpotifyPlaylist,
  SpotifySyncJob,
  SpotifyTrack,
} from "../types";

export function getSpotifyConfig(): Promise<SpotifyConfig> {
  return apiFetch<SpotifyConfig>("/api/spotify/config");
}

export interface SaveSpotifyConfigInput {
  auto_sync_enabled?: boolean;
  check_interval_minutes?: number;
  quality?: DeemixQuality;
}

export function saveSpotifyConfig(input: SaveSpotifyConfigInput): Promise<SpotifyConfig> {
  return apiFetch<SpotifyConfig>("/api/spotify/config", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getSpotifyPlaylists(): Promise<SpotifyPlaylist[]> {
  return apiFetch<{ playlists: SpotifyPlaylist[] }>("/api/spotify/playlists").then(
    (data) => data.playlists,
  );
}

export function addSpotifyPlaylist(url: string): Promise<SpotifyPlaylist[]> {
  return apiFetch<{ playlists: SpotifyPlaylist[] }>("/api/spotify/playlists", {
    method: "POST",
    body: JSON.stringify({ url }),
  }).then((data) => data.playlists);
}

export function removeSpotifyPlaylist(playlistId: string): Promise<SpotifyPlaylist[]> {
  return apiFetch<{ playlists: SpotifyPlaylist[] }>(
    `/api/spotify/playlists/${encodeURIComponent(playlistId)}`,
    { method: "DELETE" },
  ).then((data) => data.playlists);
}

export function setSpotifyPlaylistAutoSync(
  playlistId: string,
  enabled: boolean,
): Promise<SpotifyPlaylist[]> {
  return apiFetch<{ playlists: SpotifyPlaylist[] }>(
    `/api/spotify/playlists/${encodeURIComponent(playlistId)}/auto-sync`,
    { method: "POST", body: JSON.stringify({ enabled }) },
  ).then((data) => data.playlists);
}

export function resetSpotifyPlaylistSync(playlistId: string): Promise<SpotifyPlaylist[]> {
  return apiFetch<{ playlists: SpotifyPlaylist[] }>(
    `/api/spotify/playlists/${encodeURIComponent(playlistId)}/reset`,
    { method: "POST" },
  ).then((data) => data.playlists);
}

export function getSpotifyPlaylistTracks(
  playlistId: string,
  refresh = false,
): Promise<SpotifyTrack[]> {
  return apiFetch<{ tracks: SpotifyTrack[] }>(
    apiUrl(`/api/spotify/playlists/${encodeURIComponent(playlistId)}/tracks`, {
      refresh: refresh ? "1" : undefined,
    }),
  ).then((data) => data.tracks);
}

export function syncSpotifyPlaylist(
  playlistId: string,
  mountpoint?: string,
  quality?: DeemixQuality,
): Promise<{ job_id: string }> {
  return apiFetch<{ job_id: string }>(
    `/api/spotify/playlists/${encodeURIComponent(playlistId)}/sync`,
    { method: "POST", body: JSON.stringify({ mountpoint, quality }) },
  );
}

export function syncAllSpotifyPlaylists(
  mountpoint?: string,
  quality?: DeemixQuality,
): Promise<{ job_ids: string[] }> {
  return apiFetch<{ job_ids: string[] }>("/api/spotify/sync-all", {
    method: "POST",
    body: JSON.stringify({ mountpoint, quality }),
  });
}

export function getSpotifySyncJobs(): Promise<SpotifySyncJob[]> {
  return apiFetch<{ jobs: SpotifySyncJob[] }>("/api/spotify/jobs").then((data) => data.jobs);
}
