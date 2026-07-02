import type { DeemixJob, DeemixJobItem } from "../types";

export function findLatestJobItem(jobs: DeemixJob[], deemixId: string): DeemixJobItem | undefined {
  for (const job of jobs) {
    const match = job.items.find((item) => item.id === deemixId);
    if (match) return match;
  }
  return undefined;
}
