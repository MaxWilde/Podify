import { create } from "zustand";

interface MountpointState {
  mountpoint: string;
  connectedMountpoint: string | null;
  setMountpoint: (mountpoint: string) => void;
  setConnected: (mountpoint: string | null) => void;
}

const STORAGE_KEY = "podify.mountpoint";

export const useMountpointStore = create<MountpointState>((set) => ({
  mountpoint: localStorage.getItem(STORAGE_KEY) ?? "/ipod",
  connectedMountpoint: null,
  setMountpoint: (mountpoint) => {
    localStorage.setItem(STORAGE_KEY, mountpoint);
    set({ mountpoint });
  },
  setConnected: (connectedMountpoint) => set({ connectedMountpoint }),
}));
