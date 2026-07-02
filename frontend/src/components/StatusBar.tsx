import { useMountpointStore } from "../store/mountpoint";
import { useLibrary } from "../hooks/useLibrary";

function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.round((totalSeconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
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
    <footer className="flex h-8 shrink-0 items-center gap-2 border-t border-border bg-sidebar px-4 text-xs text-text-secondary">
      <span className={`h-2 w-2 rounded-full ${dotClass}`} />
      <span>{statusText}</span>
      {connectedMountpoint && <span className="ml-auto">{connectedMountpoint}</span>}
    </footer>
  );
}
