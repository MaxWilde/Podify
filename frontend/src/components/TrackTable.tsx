import type { Track } from "../types";
import { formatDuration } from "../lib/libraryGroups";
import { useDeleteTracksMutation } from "../hooks/useLibraryMutations";

interface TrackTableProps {
  tracks: Track[];
  mountpoint: string;
  showAlbum?: boolean;
}

export function TrackTable({ tracks, showAlbum = true }: TrackTableProps) {
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
