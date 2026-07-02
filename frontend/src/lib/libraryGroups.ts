import type { Track } from "../types";

export interface AlbumGroup {
  key: string;
  album: string;
  artist: string;
  tracks: Track[];
  coverTrack: Track | undefined;
}

export interface ArtistGroup {
  name: string;
  tracks: Track[];
  albumCount: number;
}

interface AlbumGroupInternal extends AlbumGroup {
  artists: Set<string>;
}

export function groupByAlbum(tracks: Track[]): AlbumGroup[] {
  const groups = new Map<string, AlbumGroupInternal>();
  for (const track of tracks) {
    const albumArtist = track.album_artist.trim();
    // Group by album title alone when there's no album-artist tag, since
    // per-track artist (feat./compilation credits) otherwise fragments a
    // single album into one entry per contributing artist.
    const key = albumArtist
      ? `${track.album.trim().toLowerCase()}::${albumArtist.toLowerCase()}`
      : track.album.trim().toLowerCase();
    let group = groups.get(key);
    if (!group) {
      group = {
        key,
        album: track.album,
        artist: albumArtist || track.artist,
        tracks: [],
        coverTrack: undefined,
        artists: new Set(),
      };
      groups.set(key, group);
    }
    group.tracks.push(track);
    group.artists.add(track.artist);
    // Prefer a track the iPod database flags as having artwork, but fall
    // back to any track so Cover can still attempt a fetch (the flag isn't
    // a perfectly reliable predictor of what mutagen can extract).
    if (!group.coverTrack) {
      group.coverTrack = track;
    } else if (!group.coverTrack.artwork && track.artwork) {
      group.coverTrack = track;
    }
  }
  for (const group of groups.values()) {
    if (group.artists.size > 1) {
      group.artist = "Various Artists";
    }
  }
  return Array.from(groups.values()).sort((a, b) => a.album.localeCompare(b.album));
}

export function groupByArtist(tracks: Track[]): ArtistGroup[] {
  const groups = new Map<string, ArtistGroup>();
  for (const track of tracks) {
    let group = groups.get(track.artist);
    if (!group) {
      group = { name: track.artist, tracks: [], albumCount: 0 };
      groups.set(track.artist, group);
    }
    group.tracks.push(track);
  }
  for (const group of groups.values()) {
    group.albumCount = new Set(group.tracks.map((t) => t.album)).size;
  }
  return Array.from(groups.values()).sort((a, b) => a.name.localeCompare(b.name));
}

export function formatDuration(totalSeconds: number): string {
  const seconds = Math.round(totalSeconds);
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}
