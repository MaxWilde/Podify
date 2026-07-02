import { apiFetch, apiUrl } from "./client";
import type {
  DeemixConfig,
  DeemixJob,
  DeemixQuality,
  DeemixResultType,
  DeemixSearchResult,
} from "../types";

export function getDeemixConfig(): Promise<DeemixConfig> {
  return apiFetch<DeemixConfig>("/api/deemix/config");
}

export interface SaveDeemixConfigInput {
  arl?: string;
  download_subdir?: string;
  default_quality?: DeemixQuality;
}

export function saveDeemixConfig(input: SaveDeemixConfigInput): Promise<DeemixConfig> {
  return apiFetch<DeemixConfig>("/api/deemix/config", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function searchDeemix(query: string): Promise<DeemixSearchResult[]> {
  return apiFetch<{ results: DeemixSearchResult[] }>(apiUrl("/api/deemix/search", { q: query })).then(
    (data) => data.results,
  );
}

export function getDeemixAlbumTracks(albumId: string): Promise<DeemixSearchResult[]> {
  return apiFetch<{ results: DeemixSearchResult[] }>(
    `/api/deemix/album/${encodeURIComponent(albumId)}/tracks`,
  ).then((data) => data.results);
}

export function getDeemixArtistAlbums(artistId: string): Promise<DeemixSearchResult[]> {
  return apiFetch<{ results: DeemixSearchResult[] }>(
    `/api/deemix/artist/${encodeURIComponent(artistId)}/albums`,
  ).then((data) => data.results);
}

export interface DeemixDownloadItem {
  id: string;
  type: DeemixResultType;
  title?: string;
  artist?: string;
}

export function downloadDeemix(
  items: DeemixDownloadItem[],
  quality: DeemixQuality,
  mountpoint?: string,
): Promise<{ job_id: string }> {
  return apiFetch<{ job_id: string }>("/api/deemix/download", {
    method: "POST",
    body: JSON.stringify({ items, quality, mountpoint }),
  });
}

export function getDeemixDownloads(): Promise<DeemixJob[]> {
  return apiFetch<{ jobs: DeemixJob[] }>("/api/deemix/downloads").then((data) => data.jobs);
}
