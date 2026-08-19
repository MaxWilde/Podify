import os
import tempfile
import time
import unittest
from unittest.mock import patch

import spotify_service


PLAYLIST_META = {
    "id": "PL1",
    "name": "Road Trip",
    "owner": {"display_name": "Max"},
    "images": [{"url": "http://img/cover.jpg"}],
    "external_urls": {"spotify": "https://open.spotify.com/playlist/PL1"},
    "tracks": {"total": 2},
}

PLAYLIST_TRACKS_PAGE = {
    "next": None,
    "items": [
        {
            "track": {
                "id": "t1",
                "name": "Song A",
                "type": "track",
                "duration_ms": 210_000,
                "external_ids": {"isrc": "ISRC1"},
                "artists": [{"name": "Band"}],
                "album": {"name": "Alb"},
            }
        },
        {
            "track": {
                "id": "t2",
                "name": "Song B",
                "type": "track",
                "duration_ms": 180_000,
                "external_ids": {},
                "artists": [{"name": "Band"}, {"name": "Guest"}],
                "album": {"name": "Alb"},
            }
        },
        # Podcast episodes and removed tracks must be ignored.
        {"track": {"id": "e1", "name": "Episode", "type": "episode", "artists": []}},
        {"track": None},
    ],
}


def fake_api_get(url, params=None):
    return PLAYLIST_TRACKS_PAGE if "/tracks" in url else PLAYLIST_META


class FakeDeezerAPI:
    """Matches only the track carrying ISRC1; everything else is unmatched."""

    def get_track_by_ISRC(self, isrc):
        return {"id": 111} if isrc == "ISRC1" else {}

    def get_track_id_from_metadata(self, artist, track, album):
        return "0"

    def search_track(self, query, limit=1):
        return {"data": []}


class FakeDeezer:
    api = FakeDeezerAPI()


class SpotifyServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self._env = patch.dict(
            os.environ,
            {
                "SPOTIFY_CONFIG_PATH": os.path.join(self._tempdir.name, "spotify_config.json"),
                "SPOTIFY_PLAYLISTS_PATH": os.path.join(self._tempdir.name, "spotify_playlists.json"),
            },
        )
        self._env.start()
        spotify_service._reset_token_cache()
        with spotify_service._TRACK_CACHE_LOCK:
            spotify_service._TRACK_CACHE.clear()
        with spotify_service._SYNC_LOCK:
            spotify_service._SYNC_JOBS.clear()
            spotify_service._RUNNING_PLAYLISTS.clear()

    def tearDown(self) -> None:
        self._env.stop()
        self._tempdir.cleanup()

    def _wait_for_job(self, timeout: float = 10.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            jobs = spotify_service.get_sync_jobs()
            if jobs and jobs[0]["status"] in {"done", "error"}:
                return jobs[0]
            time.sleep(0.05)
        self.fail("Sync job did not finish in time.")


class ParsePlaylistIdTests(SpotifyServiceTestCase):
    def test_accepts_url_uri_and_bare_id(self) -> None:
        for value in (
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc",
            "https://open.spotify.com/intl-de/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
            "37i9dQZF1DXcBWIGoYBM5M",
        ):
            self.assertEqual(spotify_service.parse_playlist_id(value), "37i9dQZF1DXcBWIGoYBM5M")

    def test_rejects_non_playlist_links(self) -> None:
        for value in ("", "https://open.spotify.com/album/123", "nope"):
            with self.assertRaises(spotify_service.SpotifyError):
                spotify_service.parse_playlist_id(value)


class ConfigTests(SpotifyServiceTestCase):
    def test_secrets_are_never_returned_by_status(self) -> None:
        spotify_service.save_config({"client_id": "cid", "client_secret": "secret"})
        status = spotify_service.get_status()

        self.assertTrue(status["credentials_configured"])
        self.assertNotIn("client_secret", status)
        self.assertNotIn("client_id", status)

    def test_blank_updates_keep_existing_credentials(self) -> None:
        spotify_service.save_config({"client_id": "cid", "client_secret": "secret"})
        spotify_service.save_config({"auto_sync_enabled": True})

        config = spotify_service.load_config()
        self.assertEqual(config["client_id"], "cid")
        self.assertEqual(config["client_secret"], "secret")
        self.assertTrue(config["auto_sync_enabled"])

    def test_rejects_unsupported_quality(self) -> None:
        with self.assertRaises(spotify_service.SpotifyError):
            spotify_service.save_config({"quality": "OGG"})


class PlaylistTrackingTests(SpotifyServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("spotify_service._api_get", fake_api_get)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_add_playlist_stores_metadata_and_rejects_duplicates(self) -> None:
        spotify_service.add_playlist("https://open.spotify.com/playlist/PL1")

        playlists = spotify_service.list_playlists()
        self.assertEqual(len(playlists), 1)
        self.assertEqual(playlists[0]["name"], "Road Trip")
        self.assertEqual(playlists[0]["owner"], "Max")
        # The episode and the removed track are not counted.
        self.assertEqual(playlists[0]["track_count"], 2)

        with self.assertRaises(spotify_service.SpotifyError):
            spotify_service.add_playlist("https://open.spotify.com/playlist/PL1")

    def test_remove_playlist_requires_a_tracked_playlist(self) -> None:
        with self.assertRaises(spotify_service.SpotifyError):
            spotify_service.remove_playlist("PL1")


class SyncTests(SpotifyServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("spotify_service._api_get", fake_api_get)
        patcher.start()
        self.addCleanup(patcher.stop)
        spotify_service.add_playlist("https://open.spotify.com/playlist/PL1")

    def test_sync_downloads_matched_tracks_and_remembers_them(self) -> None:
        started = {}

        def fake_start_download_job(items, quality, mountpoint):
            started["items"] = items
            started["quality"] = quality
            started["mountpoint"] = mountpoint
            return "deemix-1"

        with patch("spotify_service.connect_deezer", return_value=FakeDeezer()), patch(
            "spotify_service.start_download_job", fake_start_download_job
        ), patch(
            "spotify_service.get_deemix_job",
            return_value={"status": "done", "items": [{"status": "done"}]},
        ):
            spotify_service.start_sync("PL1", "/ipod", "MP3_320")
            job = self._wait_for_job()

        self.assertEqual(job["status"], "done")
        self.assertEqual(job["matched_count"], 1)
        self.assertEqual(job["unmatched_count"], 1)
        self.assertEqual(job["downloaded_count"], 1)

        self.assertEqual(started["quality"], "MP3_320")
        self.assertEqual(started["mountpoint"], "/ipod")
        self.assertEqual(started["items"], [{"id": "111", "type": "track", "title": "Song A", "artist": "Band"}])

        playlist = spotify_service.list_playlists()[0]
        self.assertEqual(playlist["synced_count"], 1)
        self.assertEqual(playlist["unmatched_count"], 1)

        states = {
            track["title"]: track["sync_state"]
            for track in spotify_service.playlist_tracks("PL1")["tracks"]
        }
        self.assertEqual(states, {"Song A": "synced", "Song B": "unmatched"})

    def test_second_sync_skips_already_synced_tracks(self) -> None:
        calls = []

        def fake_start_download_job(items, quality, mountpoint):
            calls.append(items)
            return "deemix-1"

        with patch("spotify_service.connect_deezer", return_value=FakeDeezer()), patch(
            "spotify_service.start_download_job", fake_start_download_job
        ), patch(
            "spotify_service.get_deemix_job",
            return_value={"status": "done", "items": [{"status": "done"}]},
        ):
            spotify_service.start_sync("PL1", "/ipod")
            self._wait_for_job()
            spotify_service.start_sync("PL1", "/ipod")
            job = self._wait_for_job()

        # The matched track is not downloaded twice, and a playlist whose only
        # remaining track is known-unmatched is reported as up to date.
        self.assertEqual(len(calls), 1)
        self.assertEqual(job["status"], "done")
        self.assertIn("up to date", job["message"].lower())

    def test_sync_fails_cleanly_without_a_deezer_session(self) -> None:
        with patch(
            "spotify_service.connect_deezer",
            side_effect=spotify_service.DeemixError("Deezer ARL token is not configured."),
        ):
            spotify_service.start_sync("PL1", "/ipod")
            job = self._wait_for_job()

        self.assertEqual(job["status"], "error")
        self.assertIn("ARL", job["message"])
        self.assertEqual(spotify_service.list_playlists()[0]["last_sync_status"], "error")

    def test_reset_clears_sync_history(self) -> None:
        with patch("spotify_service.connect_deezer", return_value=FakeDeezer()), patch(
            "spotify_service.start_download_job", return_value="deemix-1"
        ), patch(
            "spotify_service.get_deemix_job",
            return_value={"status": "done", "items": [{"status": "done"}]},
        ):
            spotify_service.start_sync("PL1", "/ipod")
            self._wait_for_job()

        spotify_service.reset_playlist_sync_state("PL1")

        playlist = spotify_service.list_playlists()[0]
        self.assertEqual(playlist["synced_count"], 0)
        self.assertEqual(playlist["unmatched_count"], 0)


if __name__ == "__main__":
    unittest.main()
