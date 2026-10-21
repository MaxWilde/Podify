export interface Device {
  generation: string;
  model_name: string;
  model_number: string;
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

export interface DiscoverPreferences {
  temperature: number;
  batch_size: number;
  trial_days: number;
  trial_quality: DeemixQuality | "";
  max_active_trials: number;
  include_eps: boolean;
  weekly_refresh: boolean;
}

export interface DiscoverSuggestion {
  id: string;
  title: string;
  artist: string;
  artist_id: string;
  cover_url: string;
  record_type: string;
  release_date: string;
  // 0 = artist you own, 1 = related, 2 = two steps out, 3 = genre chart.
  distance: number;
  reason: string;
}

export interface DiscoverGeneration {
  status: "idle" | "running" | "error";
  message: string;
  started_at: number;
  error: string;
}

export interface DiscoverSuggestions {
  generated_at: number;
  temperature: number | null;
  items: DiscoverSuggestion[];
  generation: DiscoverGeneration;
}

export type DiscoverAlbumMode = "trial" | "permanent";

export type DiscoverAlbumStatus = "pending" | "trial" | "kept" | "expired" | "removed" | "failed";

export type DiscoverItemType = "album" | "track";

export interface DiscoverAlbum {
  // Record id: the Deezer album id, or "track-<id>" for a single song.
  id: string;
  type?: DiscoverItemType;
  deezer_id?: string;
  title: string;
  album?: string;
  artist: string;
  artist_id: string;
  cover_url: string;
  reason: string;
  mode: DiscoverAlbumMode;
  status: DiscoverAlbumStatus;
  quality: DeemixQuality;
  mountpoint: string;
  created_at: number;
  updated_at: number;
  added_at: number;
  expires_at: number;
  expired_at?: number;
  plays?: number;
  track_count: number;
  message: string;
  progress: { status: "queued" | "downloading" | "copying"; percent: number } | null;
}

export interface DiscoverAlbums {
  now: number;
  albums: DiscoverAlbum[];
}

export interface BlockedArtist {
  id: string;
  name: string;
}
