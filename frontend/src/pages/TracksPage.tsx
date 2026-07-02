import { useMemo } from "react";
import { useLibrary } from "../hooks/useLibrary";
import { useMountpointStore } from "../store/mountpoint";
import { useSearchStore } from "../store/search";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { ConnectGate } from "../components/ConnectGate";
import { TrackTable } from "../components/TrackTable";

export function TracksPage() {
  const { data: library } = useLibrary();
  const mountpoint = useMountpointStore((s) => s.connectedMountpoint) ?? "";
  const query = useDebouncedValue(useSearchStore((s) => s.query), 300);

  const filtered = useMemo(() => {
    const tracks = library?.tracks ?? [];
    const q = query.trim().toLowerCase();
    if (!q) return tracks;
    return tracks.filter(
      (t) =>
        t.title.toLowerCase().includes(q) ||
        t.artist.toLowerCase().includes(q) ||
        t.album.toLowerCase().includes(q),
    );
  }, [library, query]);

  return (
    <ConnectGate>
      <h1 className="py-4 text-2xl font-bold">Tracks</h1>
      <TrackTable tracks={filtered} mountpoint={mountpoint} />
    </ConnectGate>
  );
}
