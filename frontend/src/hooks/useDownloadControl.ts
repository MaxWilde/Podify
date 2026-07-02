import { useMutation, useQuery } from "@tanstack/react-query";
import { downloadDeemix, getDeemixDownloads } from "../api/deemix";
import { findLatestJobItem } from "../lib/deemixJobs";
import { useToastStore, toastErrorMessage } from "../store/toast";
import type { DeemixQuality, DeemixSearchResult } from "../types";

export interface DownloadControl {
  label: string;
  disabled: boolean;
  trigger: () => void;
}

// Shared download button state for a single deemix result. Polls the job list
// (deduped by React Query across every card on the page) and derives the
// button label/disabled state from the matching job item's status.
export function useDownloadControl(
  result: DeemixSearchResult,
  quality: DeemixQuality,
  mountpoint: string,
): DownloadControl {
  const push = useToastStore((s) => s.push);

  const jobsQuery = useQuery({
    queryKey: ["deemix-jobs"],
    queryFn: getDeemixDownloads,
    refetchInterval: 1500,
  });
  const jobItem = findLatestJobItem(jobsQuery.data ?? [], result.deemix_id);

  const downloadMutation = useMutation({
    mutationFn: () =>
      downloadDeemix(
        [{ id: result.deemix_id, type: result.type, title: result.title, artist: result.artist }],
        quality,
        mountpoint || undefined,
      ),
    onError: (error) => push(toastErrorMessage(error), "error"),
  });

  const isQueuedLocally = downloadMutation.isPending;
  const status = jobItem?.status;
  const label = isQueuedLocally
    ? "Starting..."
    : status === "downloading"
      ? `Downloading ${jobItem?.progress ?? 0}%`
      : status === "copying"
        ? "Copying..."
        : status === "queued"
          ? "Queued"
          : status === "done"
            ? "Downloaded ✓"
            : status === "error"
              ? "Retry"
              : "Download";
  const disabled =
    isQueuedLocally || status === "downloading" || status === "queued" || status === "copying";

  return { label, disabled, trigger: () => downloadMutation.mutate() };
}
