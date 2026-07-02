import { useMountpointStore } from "../store/mountpoint";
import { useLibrary } from "../hooks/useLibrary";

function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.round((totalSeconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(0)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}

function StorageBar() {
  const { data: library } = useLibrary();
  const storage = library?.storage;
  if (!storage || storage.total_bytes <= 0) return null;

  const usedPct = Math.min(100, Math.round((storage.used_bytes / storage.total_bytes) * 100));

  return (
    <div className="flex items-center gap-2" title={`${formatBytes(storage.free_bytes)} free`}>
      <span className="text-text-secondary">Storage</span>
      <div className="h-1.5 w-40 overflow-hidden rounded-full bg-surface-hover">
        <div className="h-full rounded-full bg-accent" style={{ width: `${usedPct}%` }} />
      </div>
      <span className="tabular-nums text-text-secondary">
        {formatBytes(storage.used_bytes)} / {formatBytes(storage.total_bytes)}
      </span>
    </div>
  );
}

export function StatusBar() {
  const connectedMountpoint = useMountpointStore((s) => s.connectedMountpoint);
  const { data: library, isFetching, isError } = useLibrary();

  let statusText = "Not connected";
  let dotClass = "bg-neutral-500";

  if (connectedMountpoint) {
    if (isError) {
      statusText = "Connection error";
      dotClass = "bg-red-500";
    } else if (library) {
      const device = library.device.model_name || library.device.generation || "iPod";
      statusText = `${device} — ${library.track_count} tracks — ${formatDuration(library.total_duration_seconds)}`;
      dotClass = "bg-accent";
    } else if (isFetching) {
      statusText = "Loading library...";
      dotClass = "bg-yellow-500";
    }
  }

  return (
    <footer className="flex h-8 shrink-0 items-center gap-2 border-t border-border bg-sidebar px-3 text-xs text-text-secondary sm:px-4">
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <span className={`h-2 w-2 shrink-0 rounded-full ${dotClass}`} />
        <span className="truncate">{statusText}</span>
      </div>
      <div className="hidden flex-1 justify-center md:flex">{connectedMountpoint && <StorageBar />}</div>
      <div className="hidden flex-1 justify-end sm:flex">
        {connectedMountpoint && <span className="truncate">{connectedMountpoint}</span>}
      </div>
    </footer>
  );
}
