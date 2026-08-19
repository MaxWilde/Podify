import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getSettings, saveSettings } from "../api/settings";
import { getDeemixConfig, saveDeemixConfig } from "../api/deemix";
import { getSpotifyConfig, saveSpotifyConfig } from "../api/spotify";
import type { DeemixQuality, Settings } from "../types";
import { useToastStore, toastErrorMessage } from "../store/toast";

const QUALITY_OPTIONS: DeemixQuality[] = ["FLAC", "MP3_320", "MP3_128"];

export function SettingsPage() {
  const push = useToastStore((s) => s.push);
  const queryClient = useQueryClient();

  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: getSettings });
  const deemixConfigQuery = useQuery({ queryKey: ["deemix-config"], queryFn: getDeemixConfig });
  const spotifyConfigQuery = useQuery({ queryKey: ["spotify-config"], queryFn: getSpotifyConfig });

  const [form, setForm] = useState<Settings>({
    music_directory: "",
    auto_sync_enabled: false,
    delete_after_sync: false,
  });
  const [arl, setArl] = useState("");
  const [downloadSubdir, setDownloadSubdir] = useState("deemix");
  const [defaultQuality, setDefaultQuality] = useState<DeemixQuality>("FLAC");
  const [spotifyClientId, setSpotifyClientId] = useState("");
  const [spotifyClientSecret, setSpotifyClientSecret] = useState("");
  const [spotifyAutoSync, setSpotifyAutoSync] = useState(false);
  const [spotifyInterval, setSpotifyInterval] = useState(60);

  useEffect(() => {
    if (settingsQuery.data) setForm(settingsQuery.data);
  }, [settingsQuery.data]);

  useEffect(() => {
    if (deemixConfigQuery.data) {
      setDefaultQuality(deemixConfigQuery.data.default_quality);
    }
  }, [deemixConfigQuery.data]);

  useEffect(() => {
    if (spotifyConfigQuery.data) {
      setSpotifyAutoSync(spotifyConfigQuery.data.auto_sync_enabled);
      setSpotifyInterval(spotifyConfigQuery.data.check_interval_minutes);
    }
  }, [spotifyConfigQuery.data]);

  const saveSettingsMutation = useMutation({
    mutationFn: (settings: Settings) => saveSettings(settings),
    onSuccess: (saved) => {
      setForm(saved);
      push("Settings saved.", "success");
    },
    onError: (error) => push(toastErrorMessage(error), "error"),
  });

  const saveDeemixMutation = useMutation({
    mutationFn: () =>
      saveDeemixConfig({
        arl: arl || undefined,
        download_subdir: downloadSubdir || undefined,
        default_quality: defaultQuality,
      }),
    onSuccess: () => {
      push("Deemix settings saved.", "success");
      setArl("");
      queryClient.invalidateQueries({ queryKey: ["deemix-config"] });
    },
    onError: (error) => push(toastErrorMessage(error), "error"),
  });

  const saveSpotifyMutation = useMutation({
    mutationFn: () =>
      saveSpotifyConfig({
        client_id: spotifyClientId || undefined,
        client_secret: spotifyClientSecret || undefined,
        auto_sync_enabled: spotifyAutoSync,
        check_interval_minutes: spotifyInterval,
      }),
    onSuccess: () => {
      push("Spotify settings saved.", "success");
      setSpotifyClientId("");
      setSpotifyClientSecret("");
      queryClient.invalidateQueries({ queryKey: ["spotify-config"] });
    },
    onError: (error) => push(toastErrorMessage(error), "error"),
  });

  return (
    <div className="max-w-xl pt-4">
      <h1 className="mb-4 text-2xl font-bold">Settings</h1>

      <section className="mb-8 rounded-md bg-surface p-4">
        <h2 className="mb-3 text-lg font-semibold">Sync</h2>

        <label className="mb-3 block text-sm">
          <span className="mb-1 block text-text-secondary">Music Directory</span>
          <input
            value={form.music_directory}
            onChange={(e) => setForm({ ...form, music_directory: e.target.value })}
            placeholder="/music"
            className="w-full rounded bg-bg px-3 py-1.5 outline-none focus:ring-1 focus:ring-accent"
          />
        </label>

        <label className="mb-3 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.auto_sync_enabled}
            onChange={(e) => setForm({ ...form, auto_sync_enabled: e.target.checked })}
          />
          <span>Auto-sync FLAC files from Music Directory on connect</span>
        </label>

        <label className="mb-4 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.delete_after_sync}
            onChange={(e) => setForm({ ...form, delete_after_sync: e.target.checked })}
          />
          <span>Delete source files after successful auto-sync</span>
        </label>

        <button
          onClick={() => saveSettingsMutation.mutate(form)}
          disabled={saveSettingsMutation.isPending}
          className="rounded bg-accent px-4 py-1.5 text-sm font-semibold text-black hover:opacity-90 disabled:opacity-50"
        >
          Save Settings
        </button>
      </section>

      <section className="rounded-md bg-surface p-4">
        <h2 className="mb-3 text-lg font-semibold">Deemix</h2>
        <p className="mb-3 text-sm text-text-secondary">
          {deemixConfigQuery.data?.arl_configured ? "Deezer ARL token is configured." : "No Deezer ARL token configured."}
        </p>

        <label className="mb-3 block text-sm">
          <span className="mb-1 block text-text-secondary">Deezer ARL Token</span>
          <input
            type="password"
            value={arl}
            onChange={(e) => setArl(e.target.value)}
            placeholder={deemixConfigQuery.data?.arl_configured ? "•••••••• (unchanged)" : "Paste ARL token"}
            className="w-full rounded bg-bg px-3 py-1.5 outline-none focus:ring-1 focus:ring-accent"
          />
        </label>

        <label className="mb-3 block text-sm">
          <span className="mb-1 block text-text-secondary">Download Subfolder</span>
          <input
            value={downloadSubdir}
            onChange={(e) => setDownloadSubdir(e.target.value)}
            placeholder="deemix"
            className="w-full rounded bg-bg px-3 py-1.5 outline-none focus:ring-1 focus:ring-accent"
          />
        </label>

        <label className="mb-4 block text-sm">
          <span className="mb-1 block text-text-secondary">Default Quality</span>
          <select
            value={defaultQuality}
            onChange={(e) => setDefaultQuality(e.target.value as DeemixQuality)}
            className="w-full rounded bg-bg px-3 py-1.5 outline-none focus:ring-1 focus:ring-accent"
          >
            {QUALITY_OPTIONS.map((q) => (
              <option key={q} value={q}>
                {q}
              </option>
            ))}
          </select>
        </label>

        <button
          onClick={() => saveDeemixMutation.mutate()}
          disabled={saveDeemixMutation.isPending}
          className="rounded bg-accent px-4 py-1.5 text-sm font-semibold text-black hover:opacity-90 disabled:opacity-50"
        >
          Save Deemix Settings
        </button>
      </section>

      <section className="mt-8 rounded-md bg-surface p-4">
        <h2 className="mb-3 text-lg font-semibold">Spotify</h2>
        <p className="mb-3 text-sm text-text-secondary">
          {spotifyConfigQuery.data?.credentials_configured
            ? "Spotify API credentials are configured."
            : "No Spotify API credentials configured."}{" "}
          Create an app at developer.spotify.com to get a Client ID and Secret. Tracked playlists are
          matched on Deezer and downloaded through Deemix.
        </p>

        <label className="mb-3 block text-sm">
          <span className="mb-1 block text-text-secondary">Spotify Client ID</span>
          <input
            type="password"
            value={spotifyClientId}
            onChange={(e) => setSpotifyClientId(e.target.value)}
            placeholder={
              spotifyConfigQuery.data?.client_id_configured ? "•••••••• (unchanged)" : "Paste Client ID"
            }
            className="w-full rounded bg-bg px-3 py-1.5 outline-none focus:ring-1 focus:ring-accent"
          />
        </label>

        <label className="mb-3 block text-sm">
          <span className="mb-1 block text-text-secondary">Spotify Client Secret</span>
          <input
            type="password"
            value={spotifyClientSecret}
            onChange={(e) => setSpotifyClientSecret(e.target.value)}
            placeholder={
              spotifyConfigQuery.data?.credentials_configured
                ? "•••••••• (unchanged)"
                : "Paste Client Secret"
            }
            className="w-full rounded bg-bg px-3 py-1.5 outline-none focus:ring-1 focus:ring-accent"
          />
        </label>

        <label className="mb-3 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={spotifyAutoSync}
            onChange={(e) => setSpotifyAutoSync(e.target.checked)}
          />
          <span>Check tracked playlists for new tracks in the background</span>
        </label>

        <label className="mb-4 block text-sm">
          <span className="mb-1 block text-text-secondary">Check every (minutes)</span>
          <input
            type="number"
            min={5}
            value={spotifyInterval}
            onChange={(e) => setSpotifyInterval(Number(e.target.value))}
            className="w-full rounded bg-bg px-3 py-1.5 outline-none focus:ring-1 focus:ring-accent"
          />
        </label>

        <button
          onClick={() => saveSpotifyMutation.mutate()}
          disabled={saveSpotifyMutation.isPending}
          className="rounded bg-accent px-4 py-1.5 text-sm font-semibold text-black hover:opacity-90 disabled:opacity-50"
        >
          Save Spotify Settings
        </button>
      </section>
    </div>
  );
}
