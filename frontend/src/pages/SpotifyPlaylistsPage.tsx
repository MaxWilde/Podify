import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addSpotifyPlaylist,
  getSpotifyConfig,
  getSpotifyPlaylistTracks,
  getSpotifyPlaylists,
  removeSpotifyPlaylist,
  resetSpotifyPlaylistSync,
  setSpotifyPlaylistAutoSync,
  syncAllSpotifyPlaylists,
  syncSpotifyPlaylist,
} from "../api/spotify";
import { useMountpointStore } from "../store/mountpoint";
import { useToastStore, toastErrorMessage } from "../store/toast";
import { formatDuration } from "../lib/libraryGroups";
import type { SpotifyPlaylist, SpotifySyncJob, SpotifyTrack } from "../types";

const PLAYLISTS_QUERY_KEY = "spotify-playlists";

function jobLabel(job: SpotifySyncJob): string {
  switch (job.status) {
    case "queued":
      return "Queued...";
    case "resolving":
      return `Matching ${job.resolved_count}/${job.new_count || job.total_count}`;
    case "downloading":
      return `Downloading ${job.downloaded_count}/${job.matched_count}`;
    default:
      return "Syncing...";
  }
}

function formatTimestamp(seconds: number): string {
  if (!seconds) return "never";
  return new Date(seconds * 1000).toLocaleString();
}

const STATE_BADGE: Record<SpotifyTrack["sync_state"], { label: string; className: string }> = {
  synced: { label: "On iPod", className: "bg-accent/20 text-accent" },
  unmatched: { label: "Not on Deezer", className: "bg-red-500/20 text-red-400" },
  pending: { label: "Pending", className: "bg-surface-hover text-text-secondary" },
};

function PlaylistCard({
  playlist,
  onOpen,
  onSync,
  onRemove,
  onToggleAutoSync,
  onReset,
  busy,
}: {
  playlist: SpotifyPlaylist;
  onOpen: () => void;
  onSync: () => void;
  onRemove: () => void;
  onToggleAutoSync: (enabled: boolean) => void;
  onReset: () => void;
  busy: boolean;
}) {
  const job = playlist.active_job;
  const syncing = !!job;
  const progress =
    playlist.track_count > 0
      ? Math.round((playlist.synced_count / playlist.track_count) * 100)
      : 0;

  return (
    <div className="flex flex-col rounded-md bg-surface p-3">
      <button onClick={onOpen} className="block w-full text-left">
        <div className="relative mb-3 aspect-square w-full overflow-hidden rounded bg-surface-hover">
          {playlist.image_url ? (
            <img src={playlist.image_url} alt={playlist.name} className="h-full w-full object-cover" />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-2xl text-text-secondary">
              ♫
            </div>
          )}
        </div>
        <div className="truncate text-sm font-semibold text-text hover:underline">{playlist.name}</div>
      </button>
      <div className="truncate text-xs text-text-secondary">
        {playlist.owner ? `${playlist.owner} · ` : ""}
        {playlist.track_count} track{playlist.track_count === 1 ? "" : "s"}
      </div>

      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-hover">
        <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${progress}%` }} />
      </div>
      <div className="mt-1 text-xs text-text-secondary">
        {playlist.synced_count}/{playlist.track_count} on iPod
        {playlist.unmatched_count > 0 ? ` · ${playlist.unmatched_count} unmatched` : ""}
      </div>

      <button
        onClick={onSync}
        disabled={syncing || busy}
        className="mt-2 w-full rounded bg-accent px-2 py-1 text-xs font-semibold text-black hover:opacity-90 disabled:opacity-50"
      >
        {syncing ? jobLabel(job!) : "Sync now"}
      </button>

      <label className="mt-2 flex items-center gap-2 text-xs text-text-secondary">
        <input
          type="checkbox"
          checked={playlist.auto_sync}
          onChange={(e) => onToggleAutoSync(e.target.checked)}
        />
        <span>Auto-sync new tracks</span>
      </label>

      <div className="mt-1 truncate text-[11px] text-text-secondary" title={playlist.last_sync_message}>
        Last sync: {formatTimestamp(playlist.last_synced_at)}
      </div>
      {playlist.last_sync_message && (
        <div
          className={`mt-1 line-clamp-2 text-[11px] ${
            playlist.last_sync_status === "error" ? "text-red-400" : "text-text-secondary"
          }`}
        >
          {playlist.last_sync_message}
        </div>
      )}

      <div className="mt-2 flex items-center gap-3 text-[11px]">
        <a
          href={playlist.url}
          target="_blank"
          rel="noreferrer"
          className="text-text-secondary hover:text-text hover:underline"
        >
          Open in Spotify
        </a>
        <button onClick={onReset} className="text-text-secondary hover:text-text hover:underline">
          Reset
        </button>
        <button onClick={onRemove} className="ml-auto text-red-400 hover:underline">
          Remove
        </button>
      </div>
    </div>
  );
}

function PlaylistDetail({ playlistId, name, onBack }: { playlistId: string; name: string; onBack: () => void }) {
  const queryClient = useQueryClient();
  const tracksQuery = useQuery({
    queryKey: ["spotify-playlist-tracks", playlistId],
    queryFn: () => getSpotifyPlaylistTracks(playlistId),
  });

  return (
    <div className="pt-4">
      <div className="mb-4 flex items-center gap-2">
        <button
          onClick={onBack}
          className="rounded px-2 py-1 text-sm text-text-secondary hover:bg-surface hover:text-text"
        >
          ← Back
        </button>
        <h1 className="min-w-0 flex-1 truncate text-2xl font-bold">{name}</h1>
        <button
          onClick={async () => {
            await queryClient.fetchQuery({
              queryKey: ["spotify-playlist-tracks", playlistId],
              queryFn: () => getSpotifyPlaylistTracks(playlistId, true),
            });
          }}
          className="shrink-0 rounded bg-surface px-3 py-1.5 text-sm text-text hover:bg-surface-hover"
        >
          Refresh
        </button>
      </div>

      {tracksQuery.isPending && <div className="pt-12 text-center text-text-secondary">Loading tracks...</div>}
      {tracksQuery.isError && (
        <div className="pt-12 text-center text-red-400">{toastErrorMessage(tracksQuery.error)}</div>
      )}
      {tracksQuery.data && tracksQuery.data.length === 0 && (
        <div className="pt-12 text-center text-text-secondary">This playlist is empty.</div>
      )}
      {tracksQuery.data && tracksQuery.data.length > 0 && (
        <div className="flex flex-col">
          {tracksQuery.data.map((track, index) => {
            const badge = STATE_BADGE[track.sync_state];
            return (
              <div
                key={`${track.spotify_id}-${index}`}
                className="flex items-center gap-3 rounded-md px-3 py-2 hover:bg-surface"
              >
                <span className="w-6 shrink-0 text-right text-xs text-text-secondary">{index + 1}</span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-text">{track.title}</div>
                  <div className="truncate text-xs text-text-secondary">
                    {track.artists.join(", ") || track.artist}
                    {track.album ? ` — ${track.album}` : ""}
                  </div>
                </div>
                {track.duration_seconds > 0 && (
                  <span className="hidden shrink-0 text-xs text-text-secondary sm:block">
                    {formatDuration(track.duration_seconds)}
                  </span>
                )}
                <span className={`shrink-0 rounded px-2 py-0.5 text-[11px] font-semibold ${badge.className}`}>
                  {badge.label}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function SpotifyPlaylistsPage() {
  const mountpoint = useMountpointStore((s) => s.mountpoint);
  const push = useToastStore((s) => s.push);
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [openPlaylist, setOpenPlaylist] = useState<{ id: string; name: string } | null>(null);

  const configQuery = useQuery({ queryKey: ["spotify-config"], queryFn: getSpotifyConfig });

  const playlistsQuery = useQuery({
    queryKey: [PLAYLISTS_QUERY_KEY],
    queryFn: getSpotifyPlaylists,
    // Poll fast while a sync is running so progress is live, slowly otherwise.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((playlist) => playlist.active_job) ? 2000 : 20000,
  });

  const invalidate = (playlists?: SpotifyPlaylist[]) => {
    if (playlists) queryClient.setQueryData([PLAYLISTS_QUERY_KEY], playlists);
    queryClient.invalidateQueries({ queryKey: [PLAYLISTS_QUERY_KEY] });
  };
  const onError = (error: unknown) => push(toastErrorMessage(error), "error");

  const addMutation = useMutation({
    mutationFn: () => addSpotifyPlaylist(url.trim()),
    onSuccess: (playlists) => {
      setUrl("");
      push("Playlist added.", "success");
      invalidate(playlists);
    },
    onError,
  });

  const removeMutation = useMutation({
    mutationFn: (playlistId: string) => removeSpotifyPlaylist(playlistId),
    onSuccess: (playlists) => {
      push("Playlist removed.", "success");
      invalidate(playlists);
    },
    onError,
  });

  const autoSyncMutation = useMutation({
    mutationFn: ({ playlistId, enabled }: { playlistId: string; enabled: boolean }) =>
      setSpotifyPlaylistAutoSync(playlistId, enabled),
    onSuccess: (playlists) => invalidate(playlists),
    onError,
  });

  const resetMutation = useMutation({
    mutationFn: (playlistId: string) => resetSpotifyPlaylistSync(playlistId),
    onSuccess: (playlists) => {
      push("Sync history cleared — the next sync re-downloads everything.", "success");
      invalidate(playlists);
    },
    onError,
  });

  const syncMutation = useMutation({
    mutationFn: (playlistId: string) => syncSpotifyPlaylist(playlistId, mountpoint || undefined),
    onSuccess: () => {
      push("Sync started.", "success");
      invalidate();
    },
    onError,
  });

  const syncAllMutation = useMutation({
    mutationFn: () => syncAllSpotifyPlaylists(mountpoint || undefined),
    onSuccess: (result) => {
      push(
        result.job_ids.length
          ? `Syncing ${result.job_ids.length} playlist(s).`
          : "No playlists to sync.",
        result.job_ids.length ? "success" : "info",
      );
      invalidate();
    },
    onError,
  });

  if (configQuery.data && !configQuery.data.credentials_configured) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 pt-12 text-center text-text-secondary">
        <p className="text-lg text-text">Spotify is not configured yet.</p>
        <p className="text-sm">
          Add a Spotify Client ID and Client Secret in Settings to track playlists.
        </p>
      </div>
    );
  }

  if (openPlaylist) {
    return (
      <PlaylistDetail
        playlistId={openPlaylist.id}
        name={openPlaylist.name}
        onBack={() => setOpenPlaylist(null)}
      />
    );
  }

  const playlists = playlistsQuery.data ?? [];

  return (
    <div className="pt-4">
      <div className="mb-4 flex items-center gap-2">
        <h1 className="min-w-0 flex-1 truncate text-2xl font-bold">Spotify Playlists</h1>
        <button
          onClick={() => syncAllMutation.mutate()}
          disabled={syncAllMutation.isPending || playlists.length === 0}
          className="shrink-0 rounded bg-accent px-4 py-1.5 text-sm font-semibold text-black hover:opacity-90 disabled:opacity-50"
        >
          Sync all
        </button>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (url.trim()) addMutation.mutate();
        }}
        className="mb-6 flex flex-col gap-2 rounded-md bg-surface p-4 sm:flex-row"
      >
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://open.spotify.com/playlist/..."
          className="min-w-0 flex-1 rounded bg-bg px-3 py-1.5 text-sm text-text outline-none focus:ring-1 focus:ring-accent"
        />
        <button
          type="submit"
          disabled={addMutation.isPending || !url.trim()}
          className="shrink-0 rounded bg-accent px-4 py-1.5 text-sm font-semibold text-black hover:opacity-90 disabled:opacity-50"
        >
          {addMutation.isPending ? "Adding..." : "Track playlist"}
        </button>
      </form>

      {!mountpoint && (
        <div className="mb-4 rounded-md bg-surface p-3 text-sm text-text-secondary">
          Set a mountpoint in the sidebar — synced tracks are copied to the iPod at that path.
        </div>
      )}

      {playlistsQuery.isPending && <div className="pt-12 text-center text-text-secondary">Loading...</div>}
      {playlistsQuery.isError && (
        <div className="pt-12 text-center text-red-400">{toastErrorMessage(playlistsQuery.error)}</div>
      )}
      {playlistsQuery.data && playlists.length === 0 && (
        <div className="pt-12 text-center text-text-secondary">
          No playlists tracked yet. Paste a Spotify playlist link above to start tracking it.
        </div>
      )}

      {playlists.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {playlists.map((playlist) => (
            <PlaylistCard
              key={playlist.id}
              playlist={playlist}
              busy={syncMutation.isPending || syncAllMutation.isPending}
              onOpen={() => setOpenPlaylist({ id: playlist.id, name: playlist.name })}
              onSync={() => syncMutation.mutate(playlist.id)}
              onRemove={() => removeMutation.mutate(playlist.id)}
              onReset={() => resetMutation.mutate(playlist.id)}
              onToggleAutoSync={(enabled) =>
                autoSyncMutation.mutate({ playlistId: playlist.id, enabled })
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
