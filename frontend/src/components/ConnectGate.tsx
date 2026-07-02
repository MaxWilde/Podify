import type { ReactNode } from "react";
import { useMountpointStore } from "../store/mountpoint";
import { useLibrary } from "../hooks/useLibrary";

export function ConnectGate({ children }: { children: ReactNode }) {
  const connectedMountpoint = useMountpointStore((s) => s.connectedMountpoint);
  const { isLoading, isError, error } = useLibrary();

  if (!connectedMountpoint) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-text-secondary">
        <p className="text-lg">Not connected to an iPod.</p>
        <p className="text-sm">Enter a mountpoint in the sidebar and click Connect.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-text-secondary">
        Loading library...
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-text-secondary">
        <p className="text-lg text-red-400">Failed to load library.</p>
        <p className="text-sm">{error instanceof Error ? error.message : "Unknown error."}</p>
      </div>
    );
  }

  return <>{children}</>;
}
