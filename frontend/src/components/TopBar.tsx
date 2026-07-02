import { useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useSearchStore } from "../store/search";
import { useUiStore } from "../store/ui";
import { getDeemixDownloads } from "../api/deemix";

export function TopBar() {
  const location = useLocation();
  const query = useSearchStore((s) => s.query);
  const setQuery = useSearchStore((s) => s.setQuery);
  const toggleSidebar = useUiStore((s) => s.toggleSidebar);
  const toggleDownloads = useUiStore((s) => s.toggleDownloads);

  // Read-only view of the jobs the DownloadsPanel already polls (shared cache
  // key) so the mobile downloads button can show an activity indicator.
  const { data: jobs } = useQuery({ queryKey: ["deemix-jobs"], queryFn: getDeemixDownloads });
  const hasActiveDownload = (jobs ?? []).some(
    (job) => job.status === "queued" || job.status === "downloading" || job.status === "copying",
  );

  const isDeemix = location.pathname.startsWith("/deemix");
  const isLibrary = location.pathname.startsWith("/library");
  const placeholder = isDeemix
    ? "Search Deemix for tracks, albums, playlists..."
    : isLibrary
      ? "Filter tracks, albums, artists..."
      : "Search";
  const showSearch = isDeemix || isLibrary;

  return (
    <header className="flex h-16 shrink-0 items-center gap-3 bg-bg px-4 sm:px-6">
      <button
        onClick={toggleSidebar}
        className="shrink-0 rounded p-2 text-text-secondary hover:bg-surface hover:text-text md:hidden"
        aria-label="Open menu"
      >
        <span className="block text-lg leading-none">☰</span>
      </button>

      {showSearch ? (
        <div className="relative w-full min-w-0 max-w-md">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary">
            🔍
          </span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={placeholder}
            className="w-full rounded-full bg-surface py-2 pl-9 pr-4 text-sm text-text outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
      ) : (
        <div className="text-sm text-text-secondary">Podify</div>
      )}

      <button
        onClick={toggleDownloads}
        className="relative ml-auto shrink-0 rounded p-2 text-text-secondary hover:bg-surface hover:text-text md:hidden"
        aria-label="Open downloads"
      >
        <span className="block text-lg leading-none">⭳</span>
        {hasActiveDownload && (
          <span className="absolute right-1 top-1 h-2 w-2 animate-pulse rounded-full bg-accent" />
        )}
      </button>
    </header>
  );
}
