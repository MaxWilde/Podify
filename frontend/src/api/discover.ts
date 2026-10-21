import { apiFetch, apiUrl } from "./client";
import type {
  BlockedArtist,
  DeemixQuality,
  DiscoverAlbumMode,
  DiscoverAlbums,
  DiscoverItemType,
  DiscoverPreferences,
  DiscoverSuggestion,
  DiscoverSuggestions,
} from "../types";

export function getDiscoverPreferences(): Promise<DiscoverPreferences> {
  return apiFetch<DiscoverPreferences>("/api/discover/preferences");
}

export function saveDiscoverPreferences(input: Partial<DiscoverPreferences>): Promise<DiscoverPreferences> {
  return apiFetch<DiscoverPreferences>("/api/discover/preferences", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getDiscoverSuggestions(): Promise<DiscoverSuggestions> {
  return apiFetch<DiscoverSuggestions>("/api/discover/suggestions");
}

export function refreshDiscoverSuggestions(mountpoint: string, temperature?: number): Promise<DiscoverSuggestions> {
  return apiFetch<DiscoverSuggestions>("/api/discover/suggestions/refresh", {
    method: "POST",
    body: JSON.stringify({ mountpoint, temperature }),
  });
}

export function dismissDiscoverSuggestion(albumId: string): Promise<DiscoverSuggestions> {
  return apiFetch<DiscoverSuggestions>(`/api/discover/suggestions/${encodeURIComponent(albumId)}/dismiss`, {
    method: "POST",
  });
}

export function getBlockedArtists(): Promise<BlockedArtist[]> {
  return apiFetch<{ artists: BlockedArtist[] }>("/api/discover/blocked-artists").then((data) => data.artists);
}

export function blockArtist(id: string, name: string): Promise<BlockedArtist[]> {
  return apiFetch<{ artists: BlockedArtist[] }>("/api/discover/blocked-artists", {
    method: "POST",
    body: JSON.stringify({ id, name }),
  }).then((data) => data.artists);
}

export function unblockArtist(id: string): Promise<BlockedArtist[]> {
  return apiFetch<{ artists: BlockedArtist[] }>(`/api/discover/blocked-artists/${encodeURIComponent(id)}`, {
    method: "DELETE",
  }).then((data) => data.artists);
}

// Passing the mountpoint lets the server expire trials that came due while
// the iPod was unplugged, as soon as the UI sees it connected again.
export function getDiscoverAlbums(mountpoint?: string): Promise<DiscoverAlbums> {
  return apiFetch<DiscoverAlbums>(apiUrl("/api/discover/albums", { mountpoint }));
}

export interface DiscoverAddInput {
  // Deezer id of the album or track.
  id: string;
  title: string;
  artist: string;
  artist_id?: string;
  album?: string;
  cover_url: string;
  reason?: string;
}

export function addDiscoverAlbum(
  album: DiscoverAddInput | DiscoverSuggestion,
  mode: DiscoverAlbumMode,
  mountpoint: string,
  options: { type?: DiscoverItemType; quality?: DeemixQuality } = {},
): Promise<DiscoverAlbums> {
  return apiFetch<DiscoverAlbums>("/api/discover/albums", {
    method: "POST",
    body: JSON.stringify({ album, mode, mountpoint, type: options.type ?? "album", quality: options.quality }),
  });
}

export function keepDiscoverAlbum(
  albumId: string,
  upgrade = false,
  quality?: DeemixQuality,
): Promise<DiscoverAlbums> {
  return apiFetch<DiscoverAlbums>(`/api/discover/albums/${encodeURIComponent(albumId)}/keep`, {
    method: "POST",
    body: JSON.stringify({ upgrade, quality }),
  });
}

export function extendDiscoverAlbum(albumId: string, days: number): Promise<DiscoverAlbums> {
  return apiFetch<DiscoverAlbums>(`/api/discover/albums/${encodeURIComponent(albumId)}/extend`, {
    method: "POST",
    body: JSON.stringify({ days }),
  });
}

export function removeDiscoverAlbum(albumId: string, mountpoint?: string): Promise<DiscoverAlbums> {
  return apiFetch<DiscoverAlbums>(`/api/discover/albums/${encodeURIComponent(albumId)}/remove`, {
    method: "POST",
    body: JSON.stringify({ mountpoint }),
  });
}

export function retryDiscoverAlbum(albumId: string, mountpoint: string): Promise<DiscoverAlbums> {
  return apiFetch<DiscoverAlbums>(`/api/discover/albums/${encodeURIComponent(albumId)}/retry`, {
    method: "POST",
    body: JSON.stringify({ mountpoint }),
  });
}

export function forgetDiscoverAlbum(albumId: string): Promise<DiscoverAlbums> {
  return apiFetch<DiscoverAlbums>(`/api/discover/albums/${encodeURIComponent(albumId)}`, { method: "DELETE" });
}
