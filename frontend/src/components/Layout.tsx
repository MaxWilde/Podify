import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { StatusBar } from "./StatusBar";
import { ToastContainer } from "./ToastContainer";
import { DownloadsPanel } from "./DownloadsPanel";

export function Layout() {
  return (
    <div className="flex h-screen w-screen flex-col bg-bg text-text">
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <main className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
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
