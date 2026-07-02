import { NavLink } from "react-router-dom";
import { useState } from "react";
import { useMountpointStore } from "../store/mountpoint";
import { useToastStore, toastErrorMessage } from "../store/toast";
import { useUiStore } from "../store/ui";
import { useQueryClient } from "@tanstack/react-query";
import { getLibrary } from "../api/library";
import { LIBRARY_QUERY_KEY } from "../hooks/useLibrary";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `block rounded px-3 py-1.5 text-sm transition-colors ${
    isActive ? "bg-surface-hover text-text" : "text-text-secondary hover:text-text"
  }`;

export function Sidebar() {
  const mountpoint = useMountpointStore((s) => s.mountpoint);
  const setMountpoint = useMountpointStore((s) => s.setMountpoint);
  const setConnected = useMountpointStore((s) => s.setConnected);
  const push = useToastStore((s) => s.push);
  const sidebarOpen = useUiStore((s) => s.sidebarOpen);
  const closeDrawers = useUiStore((s) => s.closeDrawers);
  const queryClient = useQueryClient();
  const [connecting, setConnecting] = useState(false);

  async function handleConnect() {
    setConnecting(true);
    try {
      const library = await getLibrary(mountpoint);
      queryClient.setQueryData([LIBRARY_QUERY_KEY, mountpoint], library);
      setConnected(mountpoint);
      push(`Connected to ${library.device.model_name || mountpoint}.`, "success");
    } catch (error) {
      push(toastErrorMessage(error), "error");
    } finally {
      setConnecting(false);
    }
  }

  return (
    <aside
      className={`fixed inset-y-0 left-0 z-40 flex w-60 shrink-0 flex-col gap-4 overflow-y-auto bg-sidebar p-4 transition-transform duration-200 md:static md:z-auto md:translate-x-0 ${
        sidebarOpen ? "translate-x-0" : "-translate-x-full"
      }`}
    >
      <div className="flex items-center justify-between px-1">
        <span className="text-xl font-bold tracking-tight text-text">Podify</span>
        <button
          onClick={closeDrawers}
          className="rounded p-1 text-2xl leading-none text-text-secondary hover:text-text md:hidden"
          aria-label="Close menu"
        >
          ×
        </button>
      </div>

      <div className="flex flex-col gap-2">
        <label className="px-1 text-xs font-semibold uppercase tracking-wide text-text-secondary">
          Mountpoint
        </label>
        <input
          value={mountpoint}
          onChange={(e) => setMountpoint(e.target.value)}
          placeholder="/ipod"
          className="rounded bg-surface px-2 py-1.5 text-sm text-text outline-none focus:ring-1 focus:ring-accent"
        />
        <button
          onClick={handleConnect}
          disabled={connecting}
          className="rounded bg-accent px-2 py-1.5 text-sm font-semibold text-black transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {connecting ? "Connecting..." : "Connect"}
        </button>
      </div>

      <nav className="flex flex-col gap-1" onClick={closeDrawers}>
        <div className="px-1 pt-2 text-xs font-semibold uppercase tracking-wide text-text-secondary">
          Library
        </div>
        <NavLink to="/library/albums" className={navLinkClass}>
          Albums
        </NavLink>
        <NavLink to="/library/artists" className={navLinkClass}>
          Artists
        </NavLink>
        <NavLink to="/library/tracks" className={navLinkClass}>
          Tracks
        </NavLink>
        <NavLink to="/library/playlists" className={navLinkClass}>
          Playlists
        </NavLink>

        <div className="px-1 pt-4 text-xs font-semibold uppercase tracking-wide text-text-secondary">
          Deemix
        </div>
        <NavLink to="/deemix" className={navLinkClass}>
          Download
        </NavLink>

        <div className="px-1 pt-4 text-xs font-semibold uppercase tracking-wide text-text-secondary">
          Manage
        </div>
        <NavLink to="/upload" className={navLinkClass}>
          Upload
        </NavLink>
        <NavLink to="/settings" className={navLinkClass}>
          Settings
        </NavLink>
      </nav>
    </aside>
  );
}
