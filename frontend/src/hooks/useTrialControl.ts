import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addDiscoverAlbum, getDiscoverPreferences } from "../api/discover";
import { DISCOVER_ALBUMS_QUERY_KEY, useDiscoverAlbums } from "./useDiscoverAlbums";
import { useMountpointStore } from "../store/mountpoint";
import { useToastStore, toastErrorMessage } from "../store/toast";
import type { DeemixQuality, DeemixSearchResult } from "../types";

export interface TrialControl {
  label: string;
  disabled: boolean;
  trigger: () => void;
}

// "Try Nd" button state for a Deemix result: puts the album or song on the
// iPod as a Discover trial, then mirrors that trial's progress and status.
export function useTrialControl(
  result: DeemixSearchResult,
  quality: DeemixQuality,
  mountpoint: string,
): TrialControl {
  const push = useToastStore((s) => s.push);
  const queryClient = useQueryClient();
  const connectedMountpoint = useMountpointStore((s) => s.connectedMountpoint);
  const prefsQuery = useQuery({ queryKey: ["discover-preferences"], queryFn: getDiscoverPreferences });
  const albumsQuery = useDiscoverAlbums();
  const trialDays = prefsQuery.data?.trial_days ?? 7;

  const recordId = result.type === "album" ? result.deemix_id : `${result.type}-${result.deemix_id}`;
  const record = albumsQuery.data?.albums.find((album) => album.id === recordId);

  const mutation = useMutation({
    mutationFn: () =>
      addDiscoverAlbum(
        {
          id: result.deemix_id,
          title: result.title,
          artist: result.artist,
          album: result.album,
          cover_url: result.cover_url,
          reason: "From Deemix search",
        },
        "trial",
        mountpoint,
        { type: result.type === "track" ? "track" : "album", quality },
      ),
    onSuccess: (data) => {
      queryClient.setQueryData([DISCOVER_ALBUMS_QUERY_KEY, connectedMountpoint], data);
      push(`"${result.title}" is going on a ${trialDays}-day trial. Find it under Discover → On trial.`, "success");
    },
    onError: (error) => push(toastErrorMessage(error), "error"),
  });

  if (mutation.isPending) return { label: "Starting...", disabled: true, trigger: () => {} };
  if (record?.status === "pending") {
    const percent = record.progress?.percent ?? 0;
    const label = record.progress?.status === "copying" ? "Copying..." : `Trial ${percent}%`;
    return { label, disabled: true, trigger: () => {} };
  }
  if (record?.status === "trial") return { label: "On trial ✓", disabled: true, trigger: () => {} };
  if (record?.status === "kept") return { label: "Kept ✓", disabled: true, trigger: () => {} };
  return { label: `Try ${trialDays}d`, disabled: !mountpoint, trigger: () => mutation.mutate() };
}
