import { useLocation } from "react-router-dom";
import { useSearchStore } from "../store/search";

export function TopBar() {
  const location = useLocation();
  const query = useSearchStore((s) => s.query);
  const setQuery = useSearchStore((s) => s.setQuery);

  const isDeemix = location.pathname.startsWith("/deemix");
  const isLibrary = location.pathname.startsWith("/library");
  const placeholder = isDeemix
    ? "Search Deemix for tracks, albums, playlists..."
    : isLibrary
      ? "Filter tracks, albums, artists..."
      : "Search";
  const showSearch = isDeemix || isLibrary;

  return (
    <header className="flex h-16 shrink-0 items-center gap-4 bg-bg px-6">
      {showSearch ? (
        <div className="relative w-full max-w-md">
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
    </header>
  );
}
