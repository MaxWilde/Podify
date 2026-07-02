import io
import unittest
from unittest.mock import patch

try:
    from app import app
except ModuleNotFoundError:
    app = None


@unittest.skipUnless(app is not None, "Flask is not installed in this environment")
class AddTracksApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.config["TESTING"] = True
        self.client = app.test_client()

    @patch("app.add_tracks")
    def test_add_tracks_accepts_audio_files(self, mock_add_tracks) -> None:
        mock_add_tracks.return_value = {"requested_count": 1, "converted_count": 0}
        response = self.client.post(
            "/api/add-tracks",
            data={
                "mountpoint": "/ipod",
                "convert_to_alac": "false",
                "files": (io.BytesIO(b"abc"), "song.mp3"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["added_count"], 1)
        self.assertEqual(payload["skipped_count"], 0)
        self.assertTrue(mock_add_tracks.called)

    @patch("app.add_tracks")
    def test_add_tracks_rejects_non_audio_only_upload(self, mock_add_tracks) -> None:
        response = self.client.post(
            "/api/add-tracks",
            data={
                "mountpoint": "/ipod",
                "convert_to_alac": "false",
                "files": (io.BytesIO(b"abc"), "notes.txt"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertIn("No supported audio files", payload["error"])
        self.assertFalse(mock_add_tracks.called)

    @patch("app.add_tracks")
    def test_add_tracks_skips_non_audio_in_mixed_upload(self, mock_add_tracks) -> None:
        mock_add_tracks.return_value = {"requested_count": 1, "converted_count": 0}
        response = self.client.post(
            "/api/add-tracks",
            data={
                "mountpoint": "/ipod",
                "files": [
                    (io.BytesIO(b"a"), "track.flac"),
                    (io.BytesIO(b"b"), "cover.jpg"),
                ],
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["added_count"], 1)
        self.assertEqual(payload["skipped_count"], 1)
        kwargs = mock_add_tracks.call_args.kwargs
        self.assertEqual(len(kwargs["file_paths"]), 1)
        self.assertTrue(kwargs["file_paths"][0].endswith(".flac"))

    @patch("app.create_playlist")
    def test_create_playlist_endpoint(self, mock_create_playlist) -> None:
        mock_create_playlist.return_value = {"name": "Road Trip"}
        response = self.client.post(
            "/api/playlists/create",
            json={
                "mountpoint": "/ipod",
                "playlist_name": "Road Trip",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("created", payload["message"].lower())
        mock_create_playlist.assert_called_once_with("/ipod", "Road Trip")

    @patch("app.delete_playlist")
    def test_delete_playlist_endpoint(self, mock_delete_playlist) -> None:
        mock_delete_playlist.return_value = {"name": "Road Trip"}
        response = self.client.post(
            "/api/playlists/delete",
            json={
                "mountpoint": "/ipod",
                "playlist_name": "Road Trip",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("deleted", payload["message"].lower())
        mock_delete_playlist.assert_called_once_with("/ipod", "Road Trip")

    @patch("app.add_tracks_to_playlist")
    def test_add_tracks_to_playlist_endpoint(self, mock_add_tracks_to_playlist) -> None:
        mock_add_tracks_to_playlist.return_value = {"requested_count": 2}
        response = self.client.post(
            "/api/playlists/add-tracks",
            json={
                "mountpoint": "/ipod",
                "playlist_name": "Road Trip",
                "track_ids": [10, 11],
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["added_count"], 2)
        mock_add_tracks_to_playlist.assert_called_once_with("/ipod", "Road Trip", [10, 11])

    @patch("app.remove_tracks_from_playlist")
    def test_remove_tracks_from_playlist_endpoint(self, mock_remove_tracks_from_playlist) -> None:
        mock_remove_tracks_from_playlist.return_value = {"requested_count": 1}
        response = self.client.post(
            "/api/playlists/remove-tracks",
            json={
                "mountpoint": "/ipod",
                "playlist_name": "Road Trip",
                "track_ids": [10],
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["removed_count"], 1)
        mock_remove_tracks_from_playlist.assert_called_once_with("/ipod", "Road Trip", [10])

    @patch("app.load_settings")
    def test_get_settings_endpoint(self, mock_load_settings) -> None:
        mock_load_settings.return_value = {
            "music_directory": "/music",
            "auto_sync_enabled": True,
            "delete_after_sync": False,
        }
        response = self.client.get("/api/settings")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["music_directory"], "/music")
        self.assertTrue(payload["auto_sync_enabled"])

    @patch("app.save_settings")
    def test_save_settings_endpoint(self, mock_save_settings) -> None:
        mock_save_settings.return_value = {
            "music_directory": "/music",
            "auto_sync_enabled": True,
            "delete_after_sync": True,
        }
        response = self.client.post(
            "/api/settings",
            json={
                "music_directory": "/music",
                "auto_sync_enabled": True,
                "delete_after_sync": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["music_directory"], "/music")
        self.assertTrue(payload["delete_after_sync"])

    @patch("app.run_auto_sync_if_enabled")
    @patch("app.load_library")
    def test_library_runs_auto_sync_after_resolving_mountpoint(self, mock_load_library, mock_auto_sync) -> None:
        mock_load_library.side_effect = [
            {
                "mountpoint": "/ipod/max/MAX_S IPOD",
                "track_count": 10,
                "artist_count": 2,
                "album_count": 3,
                "total_duration_seconds": 100,
                "tracks": [],
                "playlists": [],
            },
            {
                "mountpoint": "/ipod/max/MAX_S IPOD",
                "track_count": 12,
                "artist_count": 2,
                "album_count": 3,
                "total_duration_seconds": 120,
                "tracks": [],
                "playlists": [],
            },
        ]
        mock_auto_sync.return_value = {"status": "synced", "message": "Auto-sync added 2 file(s)."}

        response = self.client.get("/api/library?mountpoint=/ipod")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["mountpoint"], "/ipod/max/MAX_S IPOD")
        self.assertEqual(payload["track_count"], 12)
        mock_auto_sync.assert_called_once_with("/ipod/max/MAX_S IPOD")


if __name__ == "__main__":
    unittest.main()
