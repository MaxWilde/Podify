import { apiFetch } from "./client";
import type { Settings } from "../types";

export function getSettings(): Promise<Settings> {
  return apiFetch<Settings>("/api/settings");
}

export function saveSettings(settings: Settings): Promise<Settings> {
  return apiFetch<Settings>("/api/settings", {
    method: "POST",
    body: JSON.stringify(settings),
  });
}
