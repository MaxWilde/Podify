import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addDiscoverAlbum,
  blockArtist,
  dismissDiscoverSuggestion,
  extendDiscoverAlbum,
  forgetDiscoverAlbum,
  getBlockedArtists,
  getDiscoverPreferences,
  getDiscoverSuggestions,
  keepDiscoverAlbum,
  refreshDiscoverSuggestions,
  removeDiscoverAlbum,
  retryDiscoverAlbum,
  saveDiscoverPreferences,
  unblockArtist,
} from "../api/discover";
import { getDeemixConfig } from "../api/deemix";
import { DISCOVER_ALBUMS_QUERY_KEY, useDiscoverAlbums } from "../hooks/useDiscoverAlbums";
import { useMountpointStore } from "../store/mountpoint";
import { useToastStore, toastErrorMessage } from "../store/toast";
import type {
  DeemixQuality,
  DiscoverAlbum,
  DiscoverAlbumMode,
  DiscoverAlbums,
  DiscoverItemType,
  DiscoverPreferences,
  DiscoverSuggestion,
} from "../types";

const SUGGESTIONS_QUERY_KEY = "discover-suggestions";
const PREFERENCES_QUERY_KEY = "discover-preferences";
const QUALITY_OPTIONS: DeemixQuality[] = ["FLAC", "MP3_320", "MP3_128"];
const DAY = 24 * 60 * 60;

type Tab = "suggestions" | "trials" | "history";

function temperatureLabel(value: number): string {
  if (value < 0.2) return "More of what you have";
  if (value < 0.45) return "Close neighbours";
  if (value < 0.7) return "Branching out";
  return "Wildcards";
}

function timeLeft(expiresAt: number, now: number): string {
  const seconds = expiresAt - now;
  if (seconds <= 0) return "Ending — removed next time the iPod is connected";
  const days = Math.floor(seconds / DAY);
  if (days >= 2) return `${days} days left`;
  const hours = Math.max(1, Math.round(seconds / 3600));
  return hours >= 24 ? "1 day left" : `${hours} hour${hours === 1 ? "" : "s"} left`;
}

function formatDate(seconds: number): string {
  return seconds ? new Date(seconds * 1000).toLocaleDateString() : "";
}

// Server clock in seconds, re-rendering once a minute so countdowns move.
function useServerNow(serverNow: number | undefined): number {
  const [offset, setOffset] = useState(0);
  const [, setTick] = useState(0);
  useEffect(() => {
    if (serverNow) setOffset(serverNow - Date.now() / 1000);
  }, [serverNow]);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => clearInterval(id);
  }, []);
  return Date.now() / 1000 + offset;
}

function AlbumCover({ url, alt }: { url: string; alt: string }) {
  return (
    <div className="aspect-square w-full overflow-hidden rounded bg-surface-hover">
      {url ? (
        <img src={url} alt={alt} className="h-full w-full object-cover" loading="lazy" />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-2xl text-text-secondary">♪</div>
      )}
    </div>
  );
}

function SuggestionCard({
  item,
  trialDays,
  canAdd,
  busy,
  onAdd,
  onDismiss,
  onBlock,
}: {
  item: DiscoverSuggestion;
  trialDays: number;
  canAdd: boolean;
  busy: boolean;
  onAdd: (mode: DiscoverAlbumMode) => void;
  onDismiss: () => void;
  onBlock: () => void;
}) {
  return (
    <div className="group relative flex flex-col rounded-md bg-surface p-3">
      <button
        onClick={onDismiss}
        title="Not for me"
        aria-label="Not for me"
        className="absolute right-4 top-4 z-10 rounded-full bg-black/70 px-2 py-0.5 text-sm text-text-secondary opacity-100 hover:text-text sm:opacity-0 sm:group-hover:opacity-100"
      >
        ×
      </button>
      <AlbumCover url={item.cover_url} alt={item.title} />
      <div className="mt-3 truncate text-sm font-semibold text-text" title={item.title}>
        {item.title}
      </div>
      <div className="truncate text-xs text-text-secondary">{item.artist}</div>
      <div className="mt-1 line-clamp-2 min-h-[2rem] text-[11px] text-text-secondary" title={item.reason}>
        {item.reason}
      </div>
      <div className="mt-2 flex gap-2">
        <button
          onClick={() => onAdd("trial")}
          disabled={!canAdd || busy}
          title={`Add to the iPod for ${trialDays} days, then remove it automatically unless you keep it`}
          className="flex-1 whitespace-nowrap rounded bg-accent px-2 py-1 text-xs font-semibold text-black hover:opacity-90 disabled:opacity-50"
        >
          Try {trialDays}d
        </button>
        <button
          onClick={() => onAdd("permanent")}
          disabled={!canAdd || busy}
          title="Add to the iPod permanently"
          className="flex-1 whitespace-nowrap rounded bg-surface-hover px-2 py-1 text-xs font-semibold text-text hover:bg-border disabled:opacity-50"
        >
          Add
        </button>
      </div>
      <button
        onClick={onBlock}
        title={`Never suggest ${item.artist}`}
        className="mt-2 w-full truncate text-left text-[11px] text-text-secondary hover:text-text hover:underline"
      >
        Never suggest {item.artist}
      </button>
    </div>
  );
}

function TrialCard({
  album,
  now,
  trialDays,
  busy,
  onKeep,
  onUpgrade,
  onExtend,
  onRemove,
}: {
  album: DiscoverAlbum;
  now: number;
  trialDays: number;
  busy: boolean;
  onKeep: () => void;
  onUpgrade: () => void;
  onExtend: () => void;
  onRemove: () => void;
}) {
  if (album.status === "pending") {
    const progress = album.progress;
    const label =
      progress?.status === "copying"
        ? "Copying to iPod..."
        : progress?.status === "downloading"
          ? `Downloading ${progress.percent}%`
          : album.message || "Queued";
    return (
      <div className="flex flex-col rounded-md bg-surface p-3">
        <AlbumCover url={album.cover_url} alt={album.title} />
        <div className="mt-3 truncate text-sm font-semibold text-text">{album.title}</div>
        <div className="truncate text-xs text-text-secondary">
          {album.artist}
          {album.type === "track" ? " · song" : ""}
        </div>
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-hover">
          <div
            className="h-full rounded-full bg-accent transition-all"
            style={{ width: `${progress?.percent ?? 0}%` }}
          />
        </div>
        <div className="mt-1 text-xs text-text-secondary">
          {label}
          {album.mode === "permanent" ? " · permanent" : ""}
        </div>
      </div>
    );
  }

  const total = Math.max(album.expires_at - album.added_at, 1);
  const remaining = Math.min(Math.max((album.expires_at - now) / total, 0), 1);
  return (
    <div className="flex flex-col rounded-md bg-surface p-3">
      <AlbumCover url={album.cover_url} alt={album.title} />
      <div className="mt-3 truncate text-sm font-semibold text-text" title={album.title}>
        {album.title}
      </div>
      <div className="truncate text-xs text-text-secondary">
          {album.artist}
          {album.type === "track" ? " · song" : ""}
        </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-hover">
        <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${remaining * 100}%` }} />
      </div>
      <div className="mt-1 text-xs text-text-secondary">{timeLeft(album.expires_at, now)}</div>
      <div className="mt-2 flex gap-2">
        <button
          onClick={onKeep}
          disabled={busy}
          className="flex-1 whitespace-nowrap rounded bg-accent px-2 py-1 text-xs font-semibold text-black hover:opacity-90 disabled:opacity-50"
        >
          Keep
        </button>
        <button
          onClick={onExtend}
          disabled={busy}
          title={`Add ${Math.min(trialDays, 7)} more days`}
          className="rounded bg-surface-hover px-2 py-1 text-xs font-semibold text-text hover:bg-border disabled:opacity-50"
        >
          +{Math.min(trialDays, 7)}d
        </button>
        <button
          onClick={onRemove}
          disabled={busy}
          className="rounded bg-surface-hover px-2 py-1 text-xs font-semibold text-red-400 hover:bg-border disabled:opacity-50"
        >
          Remove
        </button>
      </div>
      {album.quality !== "FLAC" && (
        <button
          onClick={onUpgrade}
          disabled={busy}
          className="mt-2 self-start text-left text-[11px] text-text-secondary hover:text-text hover:underline disabled:opacity-50"
        >
          Keep and re-download in FLAC (on trial as {album.quality})
        </button>
      )}
    </div>
  );
}

const HISTORY_BADGE: Record<string, { label: string; className: string }> = {
  kept: { label: "Kept", className: "bg-accent/20 text-accent" },
  expired: { label: "Trial ended", className: "bg-surface-hover text-text-secondary" },
  removed: { label: "Removed", className: "bg-surface-hover text-text-secondary" },
  failed: { label: "Failed", className: "bg-red-500/20 text-red-400" },
};

function HistoryRow({
  album,
  canAdd,
  busy,
  onAdd,
  onRetry,
  onRemove,
  onForget,
}: {
  album: DiscoverAlbum;
  canAdd: boolean;
  busy: boolean;
  onAdd: (mode: DiscoverAlbumMode) => void;
  onRetry: () => void;
  onRemove: () => void;
  onForget: () => void;
}) {
  const badge = HISTORY_BADGE[album.status] ?? HISTORY_BADGE.removed;
  const when = album.status === "expired" ? album.expired_at || album.updated_at : album.updated_at;
  const linkClass = "text-xs text-text-secondary hover:text-text hover:underline disabled:opacity-50";
  return (
    <div className="flex items-center gap-3 rounded-md px-3 py-2 hover:bg-surface">
      <div className="w-12 shrink-0">
        <AlbumCover url={album.cover_url} alt={album.title} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-text">{album.title}</div>
        <div className="truncate text-xs text-text-secondary">
          {album.artist}
          {album.type === "track" ? " · song" : ""}
          {album.plays ? ` · played ${album.plays}×` : ""}
          {when ? ` · ${formatDate(when)}` : ""}
        </div>
        {album.status === "failed" || (album.status === "kept" && album.track_count === 0) ? (
          <div className="truncate text-[11px] text-text-secondary" title={album.message}>
            {album.message}
          </div>
        ) : null}
      </div>
      <span className={`shrink-0 rounded px-2 py-0.5 text-[11px] font-semibold ${badge.className}`}>
        {badge.label}
      </span>
      <div className="flex shrink-0 flex-col items-end gap-1 sm:flex-row sm:gap-3">
        {album.status === "failed" && (
          <button onClick={onRetry} disabled={!canAdd || busy} className={linkClass}>
            Retry
          </button>
        )}
        {(album.status === "expired" || album.status === "removed") && (
          <>
            <button onClick={() => onAdd("trial")} disabled={!canAdd || busy} className={linkClass}>
              Try again
            </button>
            <button onClick={() => onAdd("permanent")} disabled={!canAdd || busy} className={linkClass}>
              Add
            </button>
          </>
        )}
        {album.status === "kept" && album.track_count > 0 && (
          <button onClick={onRemove} disabled={busy} className={`${linkClass} text-red-400`}>
            Remove from iPod
          </button>
        )}
        {album.status !== "kept" && (
          <button onClick={onForget} disabled={busy} className={linkClass} title="Let Discover suggest it again">
            Clear
          </button>
        )}
      </div>
    </div>
  );
}

function PreferencesPanel({ prefs }: { prefs: DiscoverPreferences }) {
  const queryClient = useQueryClient();
  const push = useToastStore((s) => s.push);
  const [form, setForm] = useState(prefs);
  useEffect(() => setForm(prefs), [prefs]);

  const blockedQuery = useQuery({ queryKey: ["discover-blocked"], queryFn: getBlockedArtists });

  const saveMutation = useMutation({
    mutationFn: () => saveDiscoverPreferences(form),
    onSuccess: (saved) => {
      queryClient.setQueryData([PREFERENCES_QUERY_KEY], saved);
      push("Discover preferences saved.", "success");
    },
    onError: (error) => push(toastErrorMessage(error), "error"),
  });
  const unblockMutation = useMutation({
    mutationFn: (id: string) => unblockArtist(id),
    onSuccess: (artists) => queryClient.setQueryData(["discover-blocked"], artists),
    onError: (error) => push(toastErrorMessage(error), "error"),
  });

  const inputClass = "w-full rounded bg-bg px-2 py-1.5 text-sm text-text outline-none focus:ring-1 focus:ring-accent";
  const blocked = blockedQuery.data ?? [];

  return (
    <div className="mb-6 rounded-md bg-surface p-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          Trial length (days)
          <input
            type="number"
            min={1}
            max={90}
            value={form.trial_days}
            onChange={(e) => setForm({ ...form, trial_days: Number(e.target.value) })}
            className={inputClass}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          Trial quality
          <select
            value={form.trial_quality}
            onChange={(e) => setForm({ ...form, trial_quality: e.target.value as DeemixQuality | "" })}
            className={inputClass}
          >
            <option value="">Same as Deemix default</option>
            {QUALITY_OPTIONS.map((q) => (
              <option key={q} value={q}>
                {q}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          Max trials at once
          <input
            type="number"
            min={1}
            max={50}
            value={form.max_active_trials}
            onChange={(e) => setForm({ ...form, max_active_trials: Number(e.target.value) })}
            className={inputClass}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          Suggestions per batch
          <input
            type="number"
            min={6}
            max={60}
            value={form.batch_size}
            onChange={(e) => setForm({ ...form, batch_size: Number(e.target.value) })}
            className={inputClass}
          />
        </label>
      </div>
      <div className="mt-4 flex flex-col gap-2 text-sm text-text-secondary sm:flex-row sm:gap-6">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={form.include_eps}
            onChange={(e) => setForm({ ...form, include_eps: e.target.checked })}
          />
          Include EPs
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={form.weekly_refresh}
            onChange={(e) => setForm({ ...form, weekly_refresh: e.target.checked })}
          />
          New suggestions every week
        </label>
        <button
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="rounded bg-accent px-4 py-1.5 text-sm font-semibold text-black hover:opacity-90 disabled:opacity-50 sm:ml-auto"
        >
          Save
        </button>
      </div>
      {blocked.length > 0 && (
        <div className="mt-4">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-secondary">
            Never suggested
          </div>
          <div className="flex flex-wrap gap-2">
            {blocked.map((artist) => (
              <button
                key={artist.id}
                onClick={() => unblockMutation.mutate(artist.id)}
                title="Allow again"
                className="rounded-full bg-surface-hover px-3 py-1 text-xs text-text hover:bg-border"
              >
                {artist.name} ×
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function DiscoverPage() {
  const connectedMountpoint = useMountpointStore((s) => s.connectedMountpoint);
  const push = useToastStore((s) => s.push);
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("suggestions");
  const [showPrefs, setShowPrefs] = useState(false);
  const [temperature, setTemperature] = useState<number | null>(null);

  const prefsQuery = useQuery({ queryKey: [PREFERENCES_QUERY_KEY], queryFn: getDiscoverPreferences });
  const deemixConfigQuery = useQuery({ queryKey: ["deemix-config"], queryFn: getDeemixConfig });
  const suggestionsQuery = useQuery({
    queryKey: [SUGGESTIONS_QUERY_KEY],
    queryFn: getDiscoverSuggestions,
    refetchInterval: (q) => (q.state.data?.generation.status === "running" ? 1000 : false),
  });
  const albumsQuery = useDiscoverAlbums();
  const now = useServerNow(albumsQuery.data?.now);

  const prefs = prefsQuery.data;
  const dial = temperature ?? prefs?.temperature ?? 0.5;
  const generation = suggestionsQuery.data?.generation;
  const generating = generation?.status === "running";
  const arlConfigured = deemixConfigQuery.data?.arl_configured ?? true;
  const canAdd = !!connectedMountpoint && arlConfigured;

  // Surface a failed background generation once, when it flips to error.
  const generationError = generation?.status === "error" ? generation.error : "";
  useEffect(() => {
    if (generationError) push(generationError, "error");
  }, [generationError, push]);

  const onError = (error: unknown) => push(toastErrorMessage(error), "error");
  const setAlbums = (data: DiscoverAlbums) => {
    queryClient.setQueryData([DISCOVER_ALBUMS_QUERY_KEY, connectedMountpoint], data);
    queryClient.invalidateQueries({ queryKey: [SUGGESTIONS_QUERY_KEY] });
  };

  const refreshMutation = useMutation({
    mutationFn: (value: number) => refreshDiscoverSuggestions(connectedMountpoint ?? "", value),
    onSuccess: (data) => {
      queryClient.setQueryData([SUGGESTIONS_QUERY_KEY], data);
      queryClient.invalidateQueries({ queryKey: [PREFERENCES_QUERY_KEY] });
      setTab("suggestions");
    },
    onError,
  });
  const dismissMutation = useMutation({
    mutationFn: (id: string) => dismissDiscoverSuggestion(id),
    onSuccess: (data) => queryClient.setQueryData([SUGGESTIONS_QUERY_KEY], data),
    onError,
  });
  const blockMutation = useMutation({
    mutationFn: (item: DiscoverSuggestion) => blockArtist(item.artist_id, item.artist),
    onSuccess: (artists, item) => {
      queryClient.setQueryData(["discover-blocked"], artists);
      queryClient.invalidateQueries({ queryKey: [SUGGESTIONS_QUERY_KEY] });
      push(`${item.artist} won't be suggested again.`, "info");
    },
    onError,
  });
  const addMutation = useMutation({
    mutationFn: ({ item, mode, type }: { item: DiscoverSuggestion; mode: DiscoverAlbumMode; type?: DiscoverItemType }) =>
      addDiscoverAlbum(item, mode, connectedMountpoint ?? "", { type }),
    onSuccess: (data, { item, mode }) => {
      setAlbums(data);
      push(
        mode === "trial"
          ? `Adding "${item.title}" on a ${prefs?.trial_days ?? 7}-day trial.`
          : `Adding "${item.title}" permanently.`,
        "success",
      );
    },
    onError,
  });
  const albumAction = useMutation({
    mutationFn: ({ album, action }: { album: DiscoverAlbum; action: string }) => {
      switch (action) {
        case "keep":
          return keepDiscoverAlbum(album.id);
        case "upgrade":
          return keepDiscoverAlbum(album.id, true, "FLAC");
        case "extend":
          return extendDiscoverAlbum(album.id, Math.min(prefs?.trial_days ?? 7, 7));
        case "remove":
          return removeDiscoverAlbum(album.id, connectedMountpoint ?? undefined);
        case "retry":
          return retryDiscoverAlbum(album.id, connectedMountpoint ?? "");
        default:
          return forgetDiscoverAlbum(album.id);
      }
    },
    onSuccess: (data) => setAlbums(data),
    onError,
  });

  const albums = albumsQuery.data?.albums ?? [];
  const active = albums
    .filter((album) => album.status === "pending" || album.status === "trial")
    .sort((a, b) => (a.status === "pending" ? -1 : b.status === "pending" ? 1 : a.expires_at - b.expires_at));
  const history = albums.filter((album) => album.status !== "pending" && album.status !== "trial");
  const suggestions = suggestionsQuery.data?.items ?? [];
  const trialDays = prefs?.trial_days ?? 7;

  const commitDial = () => {
    if (temperature === null || temperature === prefs?.temperature) return;
    if (!connectedMountpoint) {
      saveDiscoverPreferences({ temperature })
        .then((saved) => queryClient.setQueryData([PREFERENCES_QUERY_KEY], saved))
        .catch(onError);
      return;
    }
    refreshMutation.mutate(temperature);
  };

  const tabClass = (value: Tab) =>
    `rounded-full px-3 py-1 text-sm transition-colors ${
      tab === value ? "bg-text text-black" : "bg-surface text-text hover:bg-surface-hover"
    }`;

  return (
    <div className="pt-4">
      <div className="mb-4 flex items-center gap-2">
        <h1 className="min-w-0 flex-1 truncate text-2xl font-bold">Discover</h1>
        <button
          onClick={() => setShowPrefs((open) => !open)}
          className={`shrink-0 rounded px-3 py-1.5 text-sm hover:bg-surface-hover ${
            showPrefs ? "bg-surface-hover text-text" : "bg-surface text-text-secondary"
          }`}
        >
          Preferences
        </button>
        <button
          onClick={() => refreshMutation.mutate(dial)}
          disabled={!connectedMountpoint || generating || refreshMutation.isPending}
          className="shrink-0 rounded bg-accent px-4 py-1.5 text-sm font-semibold text-black hover:opacity-90 disabled:opacity-50"
        >
          {generating ? "Finding..." : "New suggestions"}
        </button>
      </div>

      {showPrefs && prefs && <PreferencesPanel prefs={prefs} />}

      <div className="mb-4 rounded-md bg-surface p-4">
        <div className="mb-2 flex items-baseline justify-between gap-2 text-sm">
          <span className="font-semibold text-text">Personalisation</span>
          <span className="text-text-secondary">{temperatureLabel(dial)}</span>
        </div>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={dial}
          onChange={(e) => setTemperature(Number(e.target.value))}
          onPointerUp={commitDial}
          onKeyUp={commitDial}
          disabled={generating}
          aria-label="Personalisation temperature"
          className="w-full accent-[var(--color-accent)]"
        />
        <div className="mt-1 flex justify-between text-[11px] text-text-secondary">
          <span>Familiar</span>
          <span>Adventurous</span>
        </div>
      </div>

      {!connectedMountpoint && (
        <div className="mb-4 rounded-md bg-surface p-3 text-sm text-text-secondary">
          Connect your iPod in the sidebar. Suggestions are based on its library, and albums go straight onto it.
        </div>
      )}
      {connectedMountpoint && !arlConfigured && (
        <div className="mb-4 rounded-md bg-surface p-3 text-sm text-text-secondary">
          Add your Deezer ARL token in Settings to download suggestions.
        </div>
      )}

      <div className="mb-4 flex gap-2">
        <button onClick={() => setTab("suggestions")} className={tabClass("suggestions")}>
          For you{suggestions.length ? ` · ${suggestions.length}` : ""}
        </button>
        <button onClick={() => setTab("trials")} className={tabClass("trials")}>
          On trial{active.length ? ` · ${active.length}` : ""}
        </button>
        <button onClick={() => setTab("history")} className={tabClass("history")}>
          History
        </button>
      </div>

      {tab === "suggestions" && (
        <>
          {generating && (
            <div className="pt-12 text-center text-text-secondary">{generation?.message || "Finding albums..."}</div>
          )}
          {!generating && suggestionsQuery.isPending && (
            <div className="pt-12 text-center text-text-secondary">Loading...</div>
          )}
          {!generating && suggestionsQuery.data && suggestions.length === 0 && (
            <div className="pt-12 text-center text-text-secondary">
              {suggestionsQuery.data.generated_at
                ? "You've been through this batch. Get new suggestions for more."
                : "No suggestions yet. Click New suggestions to build a batch from your iPod library."}
            </div>
          )}
          {!generating && suggestions.length > 0 && (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-4">
              {suggestions.map((item) => (
                <SuggestionCard
                  key={item.id}
                  item={item}
                  trialDays={trialDays}
                  canAdd={canAdd}
                  busy={addMutation.isPending}
                  onAdd={(mode) => addMutation.mutate({ item, mode })}
                  onDismiss={() => dismissMutation.mutate(item.id)}
                  onBlock={() => blockMutation.mutate(item)}
                />
              ))}
            </div>
          )}
        </>
      )}

      {tab === "trials" && (
        <>
          {active.length === 0 && (
            <div className="pt-12 text-center text-text-secondary">
              Nothing on trial. Use "Try {trialDays}d" on a suggestion to put it on the iPod for a while.
            </div>
          )}
          {active.length > 0 && (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-4">
              {active.map((album) => (
                <TrialCard
                  key={album.id}
                  album={album}
                  now={now}
                  trialDays={trialDays}
                  busy={albumAction.isPending}
                  onKeep={() => albumAction.mutate({ album, action: "keep" })}
                  onUpgrade={() => albumAction.mutate({ album, action: "upgrade" })}
                  onExtend={() => albumAction.mutate({ album, action: "extend" })}
                  onRemove={() => albumAction.mutate({ album, action: "remove" })}
                />
              ))}
            </div>
          )}
        </>
      )}

      {tab === "history" && (
        <>
          {history.length === 0 && (
            <div className="pt-12 text-center text-text-secondary">Albums you keep, remove or let expire show up here.</div>
          )}
          {history.length > 0 && (
            <div className="flex flex-col">
              {history.map((album) => (
                <HistoryRow
                  key={album.id}
                  album={album}
                  canAdd={canAdd}
                  busy={albumAction.isPending || addMutation.isPending}
                  onAdd={(mode) =>
                    addMutation.mutate({
                      type: album.type ?? "album",
                      item: {
                        id: album.deezer_id ?? album.id,
                        title: album.title,
                        artist: album.artist,
                        artist_id: album.artist_id,
                        cover_url: album.cover_url,
                        record_type: "album",
                        release_date: "",
                        distance: 0,
                        reason: album.reason,
                      },
                      mode,
                    })
                  }
                  onRetry={() => albumAction.mutate({ album, action: "retry" })}
                  onRemove={() => {
                    if (window.confirm(`Remove "${album.title}" from the iPod?`)) {
                      albumAction.mutate({ album, action: "remove" });
                    }
                  }}
                  onForget={() => albumAction.mutate({ album, action: "forget" })}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
