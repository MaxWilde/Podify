import { apiFetch } from "./client";

export interface DeleteTracksResult {
  deleted_count: number;
  message: string;
}

export function deleteTracks(mountpoint: string, ipodPaths: string[]): Promise<DeleteTracksResult> {
  return apiFetch<DeleteTracksResult>("/api/delete-tracks", {
    method: "POST",
    body: JSON.stringify({ mountpoint, ipod_paths: ipodPaths }),
  });
}

export interface AddTracksResult {
  added_count: number;
  converted_count: number;
  conversion_failed_count: number;
  skipped_count: number;
  message: string;
}

export function addTracksUpload(mountpoint: string, files: File[]): Promise<AddTracksResult> {
  const formData = new FormData();
  formData.set("mountpoint", mountpoint);
  for (const file of files) {
    formData.append("files", file);
  }
  return apiFetch<AddTracksResult>("/api/add-tracks", {
    method: "POST",
    body: formData,
  });
}
