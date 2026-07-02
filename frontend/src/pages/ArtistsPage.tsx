import { useMemo, useState } from "react";
import { useLibrary } from "../hooks/useLibrary";
import { useMountpointStore } from "../store/mountpoint";
import { useSearchStore } from "../store/search";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { ConnectGate } from "../components/ConnectGate";
import { groupByArtist, groupByAlbum, formatDuration, type ArtistGroup } from "../lib/libraryGroups";
import { Cover } from "../components/Cover";
import { TrackTable } from "../components/TrackTable";

function ArtistDetail({ group, mountpoint, onBack }: { group: ArtistGroup; mountpoint: string; onBack: () => void }) {
  const albums = useMemo(() => groupByAlbum(group.tracks), [group]);

  return (
    <div>
      <button onClick={onBack} className="mb-4 text-sm text-text-secondary hover:text-text">
        ← Back to Artists
      </button>
      <h1 className="mb-1 text-3xl font-bold">{group.name}</h1>
      <div className="mb-6 text-text-secondary">
        {group.albumCount} albums · {group.tracks.length} tracks
      </div>

      <h2 className="mb-2 text-lg font-semibold">Albums</h2>
      <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
        {albums.map((album) => (
          <div key={album.key} className="rounded-md bg-surface p-3">
            <Cover
              mountpoint={mountpoint}
              ipodPath={album.coverTrack?.ipod_path}
              alt={album.album}
              className="mb-3 aspect-square w-full rounded"
            />
            <div className="truncate text-sm font-semibold">{album.album}</div>
            <div className="text-xs text-text-secondary">
              {album.tracks.length} tracks · {formatDuration(album.tracks.reduce((s, t) => s + t.duration_seconds, 0))}
            </div>
          </div>
        ))}
      </div>

      <h2 className="mb-2 text-lg font-semibold">All Tracks</h2>
      <TrackTable tracks={group.tracks} mountpoint={mountpoint} />
    </div>
  );
}

export function ArtistsPage() {
  const { data: library } = useLibrary();
  const mountpoint = useMountpointStore((s) => s.connectedMountpoint) ?? "";
  const query = useDebouncedValue(useSearchStore((s) => s.query), 300);
  const [selected, setSelected] = useState<ArtistGroup | null>(null);

  const groups = useMemo(() => groupByArtist(library?.tracks ?? []), [library]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return groups;
    return groups.filter((g) => g.name.toLowerCase().includes(q));
  }, [groups, query]);

  return (
    <ConnectGate>
      {selected ? (
        <ArtistDetail group={selected} mountpoint={mountpoint} onBack={() => setSelected(null)} />
      ) : filtered.length === 0 ? (
        <div className="pt-12 text-center text-text-secondary">No artists found.</div>
      ) : (
        <div className="flex flex-col gap-1 pt-4">
          {filtered.map((group) => (
            <button
              key={group.name}
              onClick={() => setSelected(group)}
              className="flex items-center justify-between rounded-md px-3 py-2 text-left hover:bg-surface"
            >
              <span className="font-medium text-text">{group.name}</span>
              <span className="text-sm text-text-secondary">
                {group.albumCount} albums · {group.tracks.length} tracks
              </span>
            </button>
          ))}
        </div>
      )}
    </ConnectGate>
  );
}
