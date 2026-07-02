import { useMemo, useState } from "react";
import { useLibrary } from "../hooks/useLibrary";
import { useSearchStore } from "../store/search";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { ConnectGate } from "../components/ConnectGate";
import { formatDuration } from "../lib/libraryGroups";
import type { Playlist, Track } from "../types";
import {
  useCreatePlaylistMutation,
  useDeletePlaylistMutation,
  useRemoveTracksFromPlaylistMutation,
} from "../hooks/useLibraryMutations";

function PlaylistDetail({
  playlist,
  tracks,
  onBack,
}: {
  playlist: Playlist;
  tracks: Track[];
  onBack: () => void;
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const removeMutation = useRemoveTracksFromPlaylistMutation();

  function toggleOne(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div>
      <button onClick={onBack} className="mb-4 text-sm text-text-secondary hover:text-text">
        ← Back to Playlists
      </button>
      <h1 className="mb-1 text-3xl font-bold">{playlist.name}</h1>
      <div className="mb-6 text-text-secondary">{tracks.length} tracks</div>

      {selected.size > 0 && (
        <div className="mb-2 flex items-center gap-2 rounded bg-surface px-3 py-2 text-sm">
          <span className="text-text-secondary">{selected.size} selected</span>
          <button
            onClick={() => {
              removeMutation.mutate({ playlistName: playlist.name, trackIds: Array.from(selected) });
              setSelected(new Set());
            }}
            className="ml-auto rounded bg-red-600/80 px-3 py-1 text-white hover:bg-red-600"
          >
            Remove from playlist
          </button>
        </div>
      )}

      {tracks.length === 0 ? (
        <div className="pt-12 text-center text-text-secondary">This playlist is empty.</div>
      ) : (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-secondary">
              <th className="w-8 py-2" />
              <th className="py-2 pr-4">Title</th>
              <th className="py-2 pr-4">Artist</th>
              <th className="py-2 pr-4">Album</th>
              <th className="py-2 pr-4">Duration</th>
            </tr>
          </thead>
          <tbody>
            {tracks.map((track) => (
              <tr key={track.id} className="border-b border-border/50 hover:bg-surface">
                <td className="py-2">
                  <input type="checkbox" checked={selected.has(track.id)} onChange={() => toggleOne(track.id)} />
                </td>
                <td className="py-2 pr-4 text-text">{track.title}</td>
                <td className="py-2 pr-4 text-text-secondary">{track.artist}</td>
                <td className="py-2 pr-4 text-text-secondary">{track.album}</td>
                <td className="py-2 pr-4 text-text-secondary">{formatDuration(track.duration_seconds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function PlaylistsPage() {
  const { data: library } = useLibrary();
  const query = useDebouncedValue(useSearchStore((s) => s.query), 300);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [newPlaylistName, setNewPlaylistName] = useState("");
  const createMutation = useCreatePlaylistMutation();
  const deleteMutation = useDeletePlaylistMutation();

  const tracksById = useMemo(() => {
    const map = new Map<number, Track>();
    for (const t of library?.tracks ?? []) map.set(t.id, t);
    return map;
  }, [library]);

  const playlists = useMemo(() => {
    const all = library?.playlists ?? [];
    const q = query.trim().toLowerCase();
    const withoutMaster = all.filter((p) => p.type !== "master");
    if (!q) return withoutMaster;
    return withoutMaster.filter((p) => p.name.toLowerCase().includes(q));
  }, [library, query]);

  const selectedPlaylist = playlists.find((p) => p.name === selectedName) ?? null;

  if (selectedPlaylist) {
    const tracks = selectedPlaylist.track_ids.map((id) => tracksById.get(id)).filter((t): t is Track => !!t);
    return (
      <ConnectGate>
        <PlaylistDetail playlist={selectedPlaylist} tracks={tracks} onBack={() => setSelectedName(null)} />
      </ConnectGate>
    );
  }

  return (
    <ConnectGate>
      <div className="flex items-center gap-2 py-4">
        <h1 className="text-2xl font-bold">Playlists</h1>
        <div className="ml-auto flex gap-2">
          <input
            value={newPlaylistName}
            onChange={(e) => setNewPlaylistName(e.target.value)}
            placeholder="New playlist name"
            className="rounded bg-surface px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-accent"
          />
          <button
            onClick={() => {
              if (!newPlaylistName.trim()) return;
              createMutation.mutate(newPlaylistName.trim());
              setNewPlaylistName("");
            }}
            className="rounded bg-accent px-3 py-1.5 text-sm font-semibold text-black hover:opacity-90"
          >
            Create
          </button>
        </div>
      </div>

      {playlists.length === 0 ? (
        <div className="pt-12 text-center text-text-secondary">No playlists yet.</div>
      ) : (
        <div className="flex flex-col gap-1">
          {playlists.map((playlist) => (
            <div
              key={playlist.name}
              className="flex items-center justify-between rounded-md px-3 py-2 hover:bg-surface"
            >
              <button onClick={() => setSelectedName(playlist.name)} className="flex-1 text-left">
                <span className="font-medium text-text">{playlist.name}</span>
                <span className="ml-2 text-sm text-text-secondary">
                  {playlist.count} tracks{playlist.smartpl ? " · smart" : ""}
                </span>
              </button>
              <button
                onClick={() => deleteMutation.mutate(playlist.name)}
                className="rounded px-2 py-1 text-xs text-text-secondary hover:bg-red-600/80 hover:text-white"
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      )}
    </ConnectGate>
  );
}
