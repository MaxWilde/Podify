import { create } from "zustand";

interface UiState {
  sidebarOpen: boolean;
  downloadsOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  setDownloadsOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  toggleDownloads: () => void;
  closeDrawers: () => void;
}

// Drawer state only matters on mobile; on desktop the sidebar and downloads
// panel are static columns and ignore these flags.
export const useUiStore = create<UiState>((set) => ({
  sidebarOpen: false,
  downloadsOpen: false,
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  setDownloadsOpen: (downloadsOpen) => set({ downloadsOpen }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen, downloadsOpen: false })),
  toggleDownloads: () => set((s) => ({ downloadsOpen: !s.downloadsOpen, sidebarOpen: false })),
  closeDrawers: () => set({ sidebarOpen: false, downloadsOpen: false }),
}));
