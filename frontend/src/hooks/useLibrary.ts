import { useQuery } from "@tanstack/react-query";
import { getLibrary } from "../api/library";
import { useMountpointStore } from "../store/mountpoint";

export const LIBRARY_QUERY_KEY = "library";

export function useLibrary() {
  const connectedMountpoint = useMountpointStore((s) => s.connectedMountpoint);

  return useQuery({
    queryKey: [LIBRARY_QUERY_KEY, connectedMountpoint],
    queryFn: () => getLibrary(connectedMountpoint as string),
    enabled: connectedMountpoint !== null,
    staleTime: 30_000,
  });
}
