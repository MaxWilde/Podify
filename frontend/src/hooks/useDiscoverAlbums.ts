import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { getDiscoverAlbums } from "../api/discover";
import { useMountpointStore } from "../store/mountpoint";
import { useInvalidateLibrary } from "./useLibraryMutations";
import type { DiscoverAlbums } from "../types";

export const DISCOVER_ALBUMS_QUERY_KEY = "discover-albums";

function signature(data: DiscoverAlbums | undefined): string {
  return (data?.albums ?? [])
    .filter((album) => album.status !== "pending")
    .map((album) => `${album.id}:${album.status}:${album.track_count}`)
    .sort()
    .join("|");
}

// Discover albums polled for the sidebar badge and the Discover page (shared
// cache key). Fast while something is downloading, slow otherwise; the slow
// poll is also what lets the server expire trials soon after a reconnect.
// Whenever an album lands on or leaves the iPod, the library is refetched.
export function useDiscoverAlbums() {
  const connectedMountpoint = useMountpointStore((s) => s.connectedMountpoint);
  const invalidateLibrary = useInvalidateLibrary();

  const query = useQuery({
    queryKey: [DISCOVER_ALBUMS_QUERY_KEY, connectedMountpoint],
    queryFn: () => getDiscoverAlbums(connectedMountpoint ?? undefined),
    refetchInterval: (q) =>
      (q.state.data?.albums ?? []).some((album) => album.status === "pending") ? 2000 : 30000,
  });

  const previous = useRef<string | null>(null);
  const current = signature(query.data);
  useEffect(() => {
    if (!query.data) return;
    if (previous.current !== null && previous.current !== current && connectedMountpoint) {
      invalidateLibrary();
    }
    previous.current = current;
  }, [current, query.data, connectedMountpoint, invalidateLibrary]);

  return query;
}
