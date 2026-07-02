import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { getDeemixDownloads } from "../api/deemix";
import { useInvalidateLibrary } from "../hooks/useLibraryMutations";
import { useToastStore } from "../store/toast";
import { useUiStore } from "../store/ui";
import type { DeemixJob, DeemixJobItem } from "../types";

const ITEM_STATUS_LABEL: Record<DeemixJobItem["status"], string> = {
  queued: "Queued",
  downloading: "Downloading",
  copying: "Copying to iPod",
  done: "Done",
  error: "Failed",
};

const ITEM_STATUS_COLOR: Record<DeemixJobItem["status"], string> = {
  queued: "bg-neutral-500",
  downloading: "bg-accent",
  copying: "bg-sky-500",
  done: "bg-emerald-500",
  error: "bg-red-500",
};

function JobItemRow({ item }: { item: DeemixJobItem }) {
  return (
    <div className="py-2">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm text-text">{item.title || item.id}</div>
          {item.artist && <div className="truncate text-xs text-text-secondary">{item.artist}</div>}
        </div>
        <span className="shrink-0 text-xs text-text-secondary">{ITEM_STATUS_LABEL[item.status]}</span>
      </div>
      <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-hover">
        <div
          className={`h-full rounded-full transition-all ${ITEM_STATUS_COLOR[item.status]}`}
          style={{ width: `${item.status === "error" ? 100 : Math.max(item.progress, item.status === "queued" ? 4 : 0)}%` }}
        />
      </div>
      {item.status === "error" && item.error && (
        <div className="mt-1 truncate text-xs text-red-400" title={item.error}>
          {item.error}
        </div>
      )}
    </div>
  );
}

function JobCard({ job }: { job: DeemixJob }) {
  return (
    <div className="rounded-md bg-surface p-3">
      <div className="divide-y divide-border/60">
        {job.items.map((item, index) => (
          <JobItemRow key={`${job.job_id}-${index}`} item={item} />
        ))}
      </div>
      {job.status === "done" && job.ipod_message && (
        <div className="mt-2 border-t border-border/60 pt-2 text-xs text-text-secondary">{job.ipod_message}</div>
      )}
    </div>
  );
}

export function DownloadsPanel() {
  const push = useToastStore((s) => s.push);
  const invalidateLibrary = useInvalidateLibrary();
  const downloadsOpen = useUiStore((s) => s.downloadsOpen);
  const closeDrawers = useUiStore((s) => s.closeDrawers);
  const seenStatuses = useRef<Map<string, string>>(new Map());

  const jobsQuery = useQuery({
    queryKey: ["deemix-jobs"],
    queryFn: getDeemixDownloads,
    refetchInterval: 1500,
  });

  const jobs = jobsQuery.data ?? [];

  useEffect(() => {
    for (const job of jobs) {
      const previous = seenStatuses.current.get(job.job_id);
      if (previous === job.status) continue;
      seenStatuses.current.set(job.job_id, job.status);
      if (previous === undefined) continue; // don't toast on first sight of an in-flight job
      if (job.status === "done" || job.status === "error") {
        const message = job.ipod_message ? `${job.message} ${job.ipod_message}` : job.message;
        push(message, job.status === "error" ? "error" : "success");
        if (job.added_to_ipod_count > 0) {
          invalidateLibrary();
        }
      }
    }
  }, [jobs]);

  const hasActive = jobs.some(
    (job) => job.status === "queued" || job.status === "downloading" || job.status === "copying",
  );

  return (
    <aside
      className={`fixed inset-y-0 right-0 z-40 flex w-72 max-w-[85vw] shrink-0 flex-col gap-3 overflow-y-auto border-l border-border bg-sidebar p-4 transition-transform duration-200 md:static md:z-auto md:max-w-none md:translate-x-0 ${
        downloadsOpen ? "translate-x-0" : "translate-x-full"
      }`}
    >
      <div className="flex items-center gap-2 px-1">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-text-secondary">Downloads</h2>
        {hasActive && <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />}
        <button
          onClick={closeDrawers}
          className="ml-auto rounded p-1 text-2xl leading-none text-text-secondary hover:text-text md:hidden"
          aria-label="Close downloads"
        >
          ×
        </button>
      </div>
      {jobs.length === 0 ? (
        <p className="px-1 text-sm text-text-secondary">No downloads yet.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {jobs.map((job) => (
            <JobCard key={job.job_id} job={job} />
          ))}
        </div>
      )}
    </aside>
  );
}
