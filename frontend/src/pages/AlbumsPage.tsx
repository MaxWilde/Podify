import { useMemo, useState } from "react";
import { useLibrary } from "../hooks/useLibrary";
import { useMountpointStore } from "../store/mountpoint";
import { useSearchStore } from "../store/search";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { ConnectGate } from "../components/ConnectGate";
import { Cover } from "../components/Cover";
import { groupByAlbum, formatDuration, type AlbumGroup } from "../lib/libraryGroups";
import { TrackTable } from "../components/TrackTable";

function AlbumDetail({ group, mountpoint, onBack }: { group: AlbumGroup; mountpoint: string; onBack: () => void }) {
  return (
    <div>
      <button onClick={onBack} className="mb-4 text-sm text-text-secondary hover:text-text">
        ← Back to Albums
      </button>
      <div className="mb-6 flex items-end gap-4">
        <Cover
          mountpoint={mountpoint}
          ipodPath={group.coverTrack?.ipod_path}
          alt={group.album}
          className="h-40 w-40 rounded shadow-lg text-5xl"
        />
        <div>
          <div className="text-xs uppercase tracking-wide text-text-secondary">Album</div>
          <h1 className="text-3xl font-bold">{group.album}</h1>
          <div className="mt-1 text-text-secondary">
            {group.artist} · {group.tracks.length} tracks
          </div>
        </div>
      </div>
      <TrackTable tracks={group.tracks} mountpoint={mountpoint} showAlbum={false} />
    </div>
  );
}

function AlbumsGrid({ groups, mountpoint, onSelect }: { groups: AlbumGroup[]; mountpoint: string; onSelect: (g: AlbumGroup) => void }) {
  if (groups.length === 0) {
    return <div className="pt-12 text-center text-text-secondary">No albums found.</div>;
  }
  return (
    <div className="grid grid-cols-2 gap-4 pt-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
      {groups.map((group) => (
        <button
          key={group.key}
          onClick={() => onSelect(group)}
          className="group rounded-md bg-surface p-3 text-left transition-colors hover:bg-surface-hover"
        >
          <Cover
            mountpoint={mountpoint}
            ipodPath={group.coverTrack?.ipod_path}
            alt={group.album}
            className="mb-3 aspect-square w-full rounded"
          />
          <div className="truncate text-sm font-semibold text-text">{group.album}</div>
          <div className="truncate text-xs text-text-secondary">{group.artist}</div>
          <div className="mt-1 text-xs text-text-secondary">
            {group.tracks.length} tracks · {formatDuration(group.tracks.reduce((s, t) => s + t.duration_seconds, 0))}
          </div>
        </button>
      ))}
    </div>
  );
}

export function AlbumsPage() {
  const { data: library } = useLibrary();
  const mountpoint = useMountpointStore((s) => s.connectedMountpoint) ?? "";
  const query = useDebouncedValue(useSearchStore((s) => s.query), 300);
  const [selected, setSelected] = useState<AlbumGroup | null>(null);

  const groups = useMemo(() => groupByAlbum(library?.tracks ?? []), [library]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return groups;
    return groups.filter((g) => g.album.toLowerCase().includes(q) || g.artist.toLowerCase().includes(q));
  }, [groups, query]);

  return (
    <ConnectGate>
      {selected ? (
        <AlbumDetail group={selected} mountpoint={mountpoint} onBack={() => setSelected(null)} />
      ) : (
        <AlbumsGrid groups={filtered} mountpoint={mountpoint} onSelect={setSelected} />
      )}
    </ConnectGate>
  );
}
