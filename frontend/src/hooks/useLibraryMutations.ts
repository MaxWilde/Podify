import { useMutation, useQueryClient } from "@tanstack/react-query";
import { deleteTracks } from "../api/tracks";
import { useMountpointStore } from "../store/mountpoint";
import { useToastStore, toastErrorMessage } from "../store/toast";
import { LIBRARY_QUERY_KEY } from "./useLibrary";

export function useInvalidateLibrary() {
  const queryClient = useQueryClient();
  const connectedMountpoint = useMountpointStore((s) => s.connectedMountpoint);
  return () => queryClient.invalidateQueries({ queryKey: [LIBRARY_QUERY_KEY, connectedMountpoint] });
}

export function useDeleteTracksMutation() {
  const mountpoint = useMountpointStore((s) => s.connectedMountpoint) ?? "";
  const invalidate = useInvalidateLibrary();
  const push = useToastStore((s) => s.push);

  return useMutation({
    mutationFn: (ipodPaths: string[]) => deleteTracks(mountpoint, ipodPaths),
    onSuccess: (result) => {
      push(result.message, "success");
      invalidate();
    },
    onError: (error) => push(toastErrorMessage(error), "error"),
  });
}
