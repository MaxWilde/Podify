import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AlbumsPage } from "./pages/AlbumsPage";
import { ArtistsPage } from "./pages/ArtistsPage";
import { TracksPage } from "./pages/TracksPage";
import { PlaylistsPage } from "./pages/PlaylistsPage";
import { DeemixPage } from "./pages/DeemixPage";
import { SpotifyPlaylistsPage } from "./pages/SpotifyPlaylistsPage";
import { UploadPage } from "./pages/UploadPage";
import { SettingsPage } from "./pages/SettingsPage";

function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/library/albums" replace />} />
        <Route path="/library/albums" element={<AlbumsPage />} />
        <Route path="/library/artists" element={<ArtistsPage />} />
        <Route path="/library/tracks" element={<TracksPage />} />
        <Route path="/library/playlists" element={<PlaylistsPage />} />
        <Route path="/deemix" element={<DeemixPage />} />
        <Route path="/spotify" element={<Navigate to="/spotify/playlists" replace />} />
        <Route path="/spotify/playlists" element={<SpotifyPlaylistsPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/library/albums" replace />} />
      </Route>
    </Routes>
  );
}

export default App;
