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
