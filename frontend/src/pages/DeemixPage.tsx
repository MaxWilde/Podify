import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { useSearchStore } from "../store/search";
import { useMountpointStore } from "../store/mountpoint";
import { toastErrorMessage } from "../store/toast";
import { getDeemixAlbumTracks, getDeemixArtistAlbums, getDeemixConfig, searchDeemix } from "../api/deemix";
import { useDownloadControl } from "../hooks/useDownloadControl";
import type { DeemixQuality, DeemixSearchResult } from "../types";
import { formatDuration } from "../lib/libraryGroups";

const QUALITY_OPTIONS: DeemixQuality[] = ["FLAC", "MP3_320", "MP3_128"];

const TYPE_LABEL: Record<DeemixSearchResult["type"], string> = {
  track: "Track",
  album: "Album",
  artist: "Artist",
};

type DeemixView =
  | { kind: "search" }
  | { kind: "artist"; id: string; name: string }
  | { kind: "album"; id: string; title: string; artist: string };

function ResultCard({
  result,
  quality,
  mountpoint,
  onOpen,
}: {
  result: DeemixSearchResult;
  quality: DeemixQuality;
  mountpoint: string;
  onOpen?: () => void;
}) {
  const { label, disabled, trigger } = useDownloadControl(result, quality, mountpoint);
  const isArtist = result.type === "artist";

  const cover = (
    <div className={`relative mb-3 aspect-square w-full overflow-hidden bg-surface-hover ${isArtist ? "rounded-full" : "rounded"}`}>
      {result.cover_url ? (
        <img src={result.cover_url} alt={result.title} className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-2xl text-text-secondary">♪</div>
      )}
      <span className="absolute left-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-text">
        {TYPE_LABEL[result.type]}
      </span>
    </div>
  );

  return (
    <div className="rounded-md bg-surface p-3">
      {onOpen ? (
        <button onClick={onOpen} className="block w-full text-left">
          {cover}
          <div className="truncate text-sm font-semibold text-text hover:underline">{result.title}</div>
        </button>
      ) : (
        <>
          {cover}
          <div className="truncate text-sm font-semibold text-text">{result.title}</div>
        </>
      )}
      {result.type !== "artist" && (
        <div className="truncate text-xs text-text-secondary">{result.artist}</div>
      )}
      {result.duration_seconds > 0 && (
        <div className="text-xs text-text-secondary">{formatDuration(result.duration_seconds)}</div>
      )}
      <button
        onClick={trigger}
        disabled={disabled}
        className="mt-2 w-full rounded bg-accent px-2 py-1 text-xs font-semibold text-black hover:opacity-90 disabled:opacity-50"
      >
        {label}
      </button>
    </div>
  );
}

function TrackRow({
  result,
  quality,
  mountpoint,
  index,
}: {
  result: DeemixSearchResult;
  quality: DeemixQuality;
  mountpoint: string;
  index: number;
}) {
  const { label, disabled, trigger } = useDownloadControl(result, quality, mountpoint);
  return (
    <div className="flex items-center gap-3 rounded-md px-3 py-2 hover:bg-surface">
      <span className="w-6 shrink-0 text-right text-xs text-text-secondary">{index + 1}</span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-text">{result.title}</div>
        <div className="truncate text-xs text-text-secondary">{result.artist}</div>
      </div>
      {result.duration_seconds > 0 && (
        <span className="shrink-0 text-xs text-text-secondary">{formatDuration(result.duration_seconds)}</span>
      )}
      <button
        onClick={trigger}
        disabled={disabled}
        className="shrink-0 rounded bg-accent px-3 py-1 text-xs font-semibold text-black hover:opacity-90 disabled:opacity-50"
      >
        {label}
      </button>
    </div>
  );
}

function AlbumDownloadButton({
  albumId,
  title,
  artist,
  quality,
  mountpoint,
}: {
  albumId: string;
  title: string;
  artist: string;
  quality: DeemixQuality;
  mountpoint: string;
}) {
  const albumResult: DeemixSearchResult = {
    deemix_id: albumId,
    type: "album",
    title,
    artist,
    album: title,
    duration_seconds: 0,
    cover_url: "",
  };
  const { label, disabled, trigger } = useDownloadControl(albumResult, quality, mountpoint);
  return (
    <button
      onClick={trigger}
      disabled={disabled}
      className="shrink-0 rounded bg-accent px-4 py-1.5 text-sm font-semibold text-black hover:opacity-90 disabled:opacity-50"
    >
      {label === "Download" ? "Download album" : label}
    </button>
  );
}

function ResultGrid({
  results,
  quality,
  mountpoint,
  onOpen,
}: {
  results: DeemixSearchResult[];
  quality: DeemixQuality;
  mountpoint: string;
  onOpen: (result: DeemixSearchResult) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
      {results.map((result) => (
        <ResultCard
          key={`${result.type}-${result.deemix_id}`}
          result={result}
          quality={quality}
          mountpoint={mountpoint}
          onOpen={result.type === "track" ? undefined : () => onOpen(result)}
        />
      ))}
    </div>
  );
}

export function DeemixPage() {
  const query = useDebouncedValue(useSearchStore((s) => s.query), 300);
  const mountpoint = useMountpointStore((s) => s.mountpoint);
  const [quality, setQuality] = useState<DeemixQuality>("FLAC");
  const [stack, setStack] = useState<DeemixView[]>([{ kind: "search" }]);
  const view = stack[stack.length - 1];

  // Typing a new search always returns to the search results (drops any
  // artist/album the user had drilled into).
  useEffect(() => {
    setStack([{ kind: "search" }]);
  }, [query]);

  const openResult = (result: DeemixSearchResult) => {
    if (result.type === "artist") {
      setStack((s) => [...s, { kind: "artist", id: result.deemix_id, name: result.title }]);
    } else if (result.type === "album") {
      setStack((s) => [...s, { kind: "album", id: result.deemix_id, title: result.title, artist: result.artist }]);
    }
  };
  const goBack = () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s));

  const configQuery = useQuery({ queryKey: ["deemix-config"], queryFn: getDeemixConfig });

  const searchQuery = useQuery({
    queryKey: ["deemix-search", query],
    queryFn: () => searchDeemix(query),
    enabled: query.trim().length > 0,
  });

  const artistView = view.kind === "artist" ? view : null;
  const albumView = view.kind === "album" ? view : null;

  const artistAlbumsQuery = useQuery({
    queryKey: ["deemix-artist-albums", artistView?.id],
    queryFn: () => getDeemixArtistAlbums(artistView!.id),
    enabled: !!artistView,
  });
  const albumTracksQuery = useQuery({
    queryKey: ["deemix-album-tracks", albumView?.id],
    queryFn: () => getDeemixAlbumTracks(albumView!.id),
    enabled: !!albumView,
  });

  if (configQuery.data && !configQuery.data.arl_configured) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 pt-12 text-center text-text-secondary">
        <p className="text-lg text-text">Deemix is not configured yet.</p>
        <p className="text-sm">Add your Deezer ARL token in Settings to enable downloads.</p>
      </div>
    );
  }

  return (
    <div className="pt-4">
      <div className="mb-4 flex items-center gap-2">
        {view.kind !== "search" && (
          <button onClick={goBack} className="rounded px-2 py-1 text-sm text-text-secondary hover:bg-surface hover:text-text">
            ← Back
          </button>
        )}
        <h1 className="min-w-0 flex-1 truncate text-2xl font-bold">
          {view.kind === "artist" ? view.name : view.kind === "album" ? view.title : "Deemix"}
        </h1>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <select
            value={quality}
            onChange={(e) => setQuality(e.target.value as DeemixQuality)}
            className="rounded bg-surface px-2 py-1 text-sm outline-none focus:ring-1 focus:ring-accent"
          >
            {QUALITY_OPTIONS.map((q) => (
              <option key={q} value={q}>
                {q}
              </option>
            ))}
          </select>
        </div>
      </div>

      {view.kind === "search" && (
        <>
          {query.trim().length === 0 && (
            <div className="pt-12 text-center text-text-secondary">
              Use the search bar above to find tracks, albums, and artists.
            </div>
          )}
          {searchQuery.isFetching && (
            <div className="pt-12 text-center text-text-secondary">Searching...</div>
          )}
          {searchQuery.isError && (
            <div className="pt-12 text-center text-red-400">{toastErrorMessage(searchQuery.error)}</div>
          )}
          {searchQuery.data && searchQuery.data.length === 0 && (
            <div className="pt-12 text-center text-text-secondary">No results for "{query}".</div>
          )}
          {searchQuery.data && searchQuery.data.length > 0 && (
            <ResultGrid results={searchQuery.data} quality={quality} mountpoint={mountpoint} onOpen={openResult} />
          )}
        </>
      )}

      {view.kind === "artist" && (
        <>
          {artistAlbumsQuery.isFetching && (
            <div className="pt-12 text-center text-text-secondary">Loading albums...</div>
          )}
          {artistAlbumsQuery.isError && (
            <div className="pt-12 text-center text-red-400">{toastErrorMessage(artistAlbumsQuery.error)}</div>
          )}
          {artistAlbumsQuery.data && artistAlbumsQuery.data.length === 0 && (
            <div className="pt-12 text-center text-text-secondary">No albums found for this artist.</div>
          )}
          {artistAlbumsQuery.data && artistAlbumsQuery.data.length > 0 && (
            <ResultGrid results={artistAlbumsQuery.data} quality={quality} mountpoint={mountpoint} onOpen={openResult} />
          )}
        </>
      )}

      {view.kind === "album" && (
        <>
          <div className="mb-2 flex items-center gap-3">
            <div className="text-sm text-text-secondary">{view.artist}</div>
            <div className="ml-auto">
              <AlbumDownloadButton
                albumId={view.id}
                title={view.title}
                artist={view.artist}
                quality={quality}
                mountpoint={mountpoint}
              />
            </div>
          </div>
          {albumTracksQuery.isFetching && (
            <div className="pt-12 text-center text-text-secondary">Loading tracks...</div>
          )}
          {albumTracksQuery.isError && (
            <div className="pt-12 text-center text-red-400">{toastErrorMessage(albumTracksQuery.error)}</div>
          )}
          {albumTracksQuery.data && albumTracksQuery.data.length === 0 && (
            <div className="pt-12 text-center text-text-secondary">No tracks found for this album.</div>
          )}
          {albumTracksQuery.data && albumTracksQuery.data.length > 0 && (
            <div className="flex flex-col">
              {albumTracksQuery.data.map((track, index) => (
                <TrackRow
                  key={track.deemix_id}
                  result={track}
                  quality={quality}
                  mountpoint={mountpoint}
                  index={index}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
