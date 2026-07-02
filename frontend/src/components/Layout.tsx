import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { StatusBar } from "./StatusBar";
import { ToastContainer } from "./ToastContainer";
import { DownloadsPanel } from "./DownloadsPanel";
import { useUiStore } from "../store/ui";

export function Layout() {
  const sidebarOpen = useUiStore((s) => s.sidebarOpen);
  const downloadsOpen = useUiStore((s) => s.downloadsOpen);
  const closeDrawers = useUiStore((s) => s.closeDrawers);

  const anyDrawerOpen = sidebarOpen || downloadsOpen;

  return (
    <div className="flex h-screen w-screen flex-col overflow-x-hidden bg-bg text-text">
      <div className="relative flex min-h-0 flex-1">
        {/* Mobile drawer backdrop */}
        {anyDrawerOpen && (
          <div
            onClick={closeDrawers}
            className="fixed inset-0 z-30 bg-black/60 md:hidden"
            aria-hidden="true"
          />
        )}
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <main className="min-h-0 flex-1 overflow-y-auto px-4 pb-6 sm:px-6">
            <Outlet />
          </main>
        </div>
        <DownloadsPanel />
      </div>
      <StatusBar />
      <ToastContainer />
    </div>
  );
}
