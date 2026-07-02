import { useState } from "react";
import type { Track } from "../types";
import { formatDuration } from "../lib/libraryGroups";
import { useLibrary } from "../hooks/useLibrary";
import {
  useAddTracksToPlaylistMutation,
  useDeleteTracksMutation,
} from "../hooks/useLibraryMutations";

interface TrackTableProps {
  tracks: Track[];
  mountpoint: string;
  showAlbum?: boolean;
}

function AddToPlaylistMenu({ trackIds, onClose }: { trackIds: number[]; onClose: () => void }) {
  const { data: library } = useLibrary();
  const addMutation = useAddTracksToPlaylistMutation();

  const playlists = (library?.playlists ?? []).filter((p) => p.type !== "master");

  return (
    <div className="absolute right-0 top-full z-20 mt-1 w-52 rounded-md border border-border bg-surface p-1 shadow-xl">
      {playlists.length === 0 && (
        <div className="px-3 py-2 text-xs text-text-secondary">No playlists yet.</div>
      )}
      {playlists.map((playlist) => (
        <button
          key={playlist.name}
          onClick={() => {
            addMutation.mutate({ playlistName: playlist.name, trackIds });
            onClose();
          }}
          className="block w-full truncate rounded px-3 py-1.5 text-left text-sm text-text hover:bg-surface-hover"
        >
          {playlist.name}
        </button>
      ))}
    </div>
  );
}

export function TrackTable({ tracks, showAlbum = true }: TrackTableProps) {
  const [menuOpenFor, setMenuOpenFor] = useState<number | null>(null);
  const deleteMutation = useDeleteTracksMutation();

  function deleteTrack(track: Track) {
    deleteMutation.mutate([track.ipod_path]);
  }

  if (tracks.length === 0) {
    return <div className="pt-12 text-center text-text-secondary">No tracks found.</div>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-secondary">
            <th className="py-2 pr-4">Title</th>
            <th className="py-2 pr-4">Artist</th>
            {showAlbum && <th className="hidden py-2 pr-4 sm:table-cell">Album</th>}
            <th className="py-2 pr-4">Duration</th>
            <th className="hidden py-2 pr-4 md:table-cell">Bitrate</th>
            <th className="py-2 pr-4"></th>
          </tr>
        </thead>
        <tbody>
          {tracks.map((track) => (
            <tr key={track.id} className="group border-b border-border/50 hover:bg-surface">
              <td className="py-2 pr-4 text-text">{track.title}</td>
              <td className="py-2 pr-4 text-text-secondary">{track.artist}</td>
              {showAlbum && <td className="hidden py-2 pr-4 text-text-secondary sm:table-cell">{track.album}</td>}
              <td className="py-2 pr-4 text-text-secondary">{formatDuration(track.duration_seconds)}</td>
              <td className="hidden py-2 pr-4 text-text-secondary md:table-cell">{track.bitrate ? `${track.bitrate} kbps` : "—"}</td>
              <td className="relative py-2 pr-1 text-right">
                <div className="flex justify-end gap-2 opacity-100 md:opacity-0 md:group-hover:opacity-100">
                  <div className="relative">
                    <button
                      onClick={() => setMenuOpenFor(menuOpenFor === track.id ? null : track.id)}
                      className="rounded px-2 py-1 text-xs text-text-secondary hover:bg-surface-hover hover:text-text"
                    >
                      + Playlist
                    </button>
                    {menuOpenFor === track.id && (
                      <AddToPlaylistMenu trackIds={[track.id]} onClose={() => setMenuOpenFor(null)} />
                    )}
                  </div>
                  <button
                    onClick={() => deleteTrack(track)}
                    className="rounded px-2 py-1 text-xs text-text-secondary hover:bg-red-600/80 hover:text-white"
                  >
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
