export interface Device {
  generation: string;
  model_name: string;
  model_number: string;
}

export interface Playlist {
  name: string;
  type: string;
  count: number;
  smartpl: boolean;
  track_ids: number[];
}

export interface Track {
  id: number;
  title: string;
  artist: string;
  album: string;
  album_artist: string;
  genre: string;
  year: number;
  playcount: number;
  bitrate: number;
  size_bytes: number;
  duration_seconds: number;
  ipod_path: string;
  artwork: boolean;
  checksum: string | null;
}

export interface AutoSyncStatus {
  status: string;
  message?: string;
  added_count?: number;
  deleted_source_count?: number;
  scanned_count?: number;
}

export interface Storage {
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
}

export interface Library {
  mountpoint: string;
  device: Device;
  track_count: number;
  artist_count: number;
  album_count: number;
  total_duration_seconds: number;
  playlists: Playlist[];
  tracks: Track[];
  auto_sync?: AutoSyncStatus;
  storage?: Storage;
}

export interface Settings {
  music_directory: string;
  auto_sync_enabled: boolean;
  delete_after_sync: boolean;
}

export interface DeemixConfig {
  enabled: boolean;
  arl_configured: boolean;
  download_dir: string;
  music_directory: string;
  default_quality: DeemixQuality;
}

export type DeemixQuality = "FLAC" | "MP3_320" | "MP3_128";

export type DeemixResultType = "track" | "album" | "artist";

export interface DeemixSearchResult {
  deemix_id: string;
  type: DeemixResultType;
  title: string;
  artist: string;
  album: string;
  duration_seconds: number;
  cover_url: string;
}

export type DeemixJobItemStatus = "queued" | "downloading" | "copying" | "done" | "error";

export interface DeemixJobItem {
  id: string;
  type: DeemixResultType;
  title: string;
  artist: string;
  status: DeemixJobItemStatus;
  progress: number;
  error: string;
}

export type DeemixJobStatus = "queued" | "downloading" | "copying" | "done" | "error";

export interface DeemixJob {
  job_id: string;
  quality: DeemixQuality;
  mountpoint: string;
  status: DeemixJobStatus;
  items: DeemixJobItem[];
  added_to_ipod_count: number;
  ipod_message: string;
  message: string;
  created_at: number;
}

export interface ApiError {
  error: string;
}

export interface SpotifyConfig {
  enabled: boolean;
  credentials_configured: boolean;
  client_id_configured: boolean;
  auto_sync_enabled: boolean;
  check_interval_minutes: number;
  quality: DeemixQuality;
  last_mountpoint: string;
  playlist_count: number;
}

export type SpotifySyncStatus = "queued" | "resolving" | "downloading" | "done" | "error";

export interface SpotifySyncJob {
  job_id: string;
  playlist_id: string;
  playlist_name: string;
  quality: DeemixQuality;
  mountpoint: string;
  status: SpotifySyncStatus;
  total_count: number;
  new_count: number;
  resolved_count: number;
  matched_count: number;
  unmatched_count: number;
  downloaded_count: number;
  failed_count: number;
  deemix_job_ids: string[];
  message: string;
  created_at: number;
}

export interface SpotifyPlaylist {
  id: string;
  name: string;
  owner: string;
  image_url: string;
  url: string;
  track_count: number;
  added_at: number;
  auto_sync: boolean;
  last_synced_at: number;
  last_sync_status: string;
  last_sync_message: string;
  synced_count: number;
  unmatched_count: number;
  pending_count: number;
  active_job: SpotifySyncJob | null;
}

export type SpotifyTrackSyncState = "synced" | "unmatched" | "pending";

export interface SpotifyTrack {
  spotify_id: string;
  title: string;
  artist: string;
  artists: string[];
  album: string;
  isrc: string;
  duration_seconds: number;
  sync_state: SpotifyTrackSyncState;
}
