import { apiFetch, apiUrl } from "./client";
import type { Library } from "../types";

export function getLibrary(mountpoint: string): Promise<Library> {
  return apiFetch<Library>(apiUrl("/api/library", { mountpoint }));
}

export function getCoverUrl(mountpoint: string, ipodPath: string): string {
  return apiUrl("/api/cover", { mountpoint, ipod_path: ipodPath });
}
