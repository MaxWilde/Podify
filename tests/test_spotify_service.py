import base64
import io
import json
import os
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import patch

import spotify_service


PLAYLIST_ID = "3cEYpjA9oz9GiPac4AsH4n"

# A trimmed copy of a real embed payload: two tracks, one podcast episode, and
# two cover-art sizes.
EMBED_HTML = """<html><body><script id="__NEXT_DATA__" type="application/json">
{"props": {"pageProps": {"state": {"data": {"entity": {
  "type": "playlist", "id": "3cEYpjA9oz9GiPac4AsH4n", "name": "Road Trip",
  "subtitle": "Max",
  "coverArt": {"sources": [{"width": 640, "url": "http://img/640.jpg"},
                            {"width": 300, "url": "http://img/300.jpg"}]},
  "trackList": [
    {"uri": "spotify:track:1AWQoqb9bSvzTjaLralEkT", "title": "Song A",
     "subtitle": "Band", "duration": 210000},
    {"uri": "spotify:track:0NfYAsKygCYwPA2BgTZ1qg", "title": "Song B",
     "subtitle": "Band, Guest", "duration": 180000},
    {"uri": "spotify:episode:abc", "title": "An Episode", "subtitle": "Host", "duration": 100}
  ]}}}}}}
</script></body></html>"""

# The main playlist page: base64 initialState, the reader Podify prefers.
PAGE_STATE = {
    "entities": {
        "items": {
            "spotify:playlist:3cEYpjA9oz9GiPac4AsH4n": {
                "id": "3cEYpjA9oz9GiPac4AsH4n",
                "name": "Road Trip",
                "ownerV2": {"data": {"name": "Max"}},
                "images": {
                    "items": [
                        {
                            "sources": [
                                {"width": 640, "url": "http://img/640.jpg"},
                                {"width": 300, "url": "http://img/300.jpg"},
                            ]
                        }
                    ]
                },
                "content": {
                    "totalCount": 3,
                    "items": [
                        {
                            "itemV2": {
                                "data": {
                                    "__typename": "Track",
                                    "uri": "spotify:track:1AWQoqb9bSvzTjaLralEkT",
                                    "name": "Song A",
                                    "artists": {"items": [{"profile": {"name": "Band"}}]},
                                    "albumOfTrack": {"name": "Alb"},
                                    "duration": {"totalMilliseconds": 210000},
                                }
                            }
                        },
                        {
                            "itemV2": {
                                "data": {
                                    "__typename": "Track",
                                    "uri": "spotify:track:0NfYAsKygCYwPA2BgTZ1qg",
                                    "name": "Song B",
                                    "artists": {
                                        "items": [
                                            {"profile": {"name": "Band"}},
                                            {"profile": {"name": "Guest"}},
                                        ]
                                    },
                                    "albumOfTrack": {"name": "Alb"},
                                    "duration": {"totalMilliseconds": 180000},
                                }
                            }
                        },
                        {
                            "itemV2": {
                                "data": {
                                    "__typename": "PodcastEpisode",
                                    "uri": "spotify:episode:abc",
                                    "name": "An Episode",
                                    "artists": {"items": []},
                                }
                            }
                        },
                    ],
                },
            }
        }
    }
}


def page_html(state: dict = None) -> bytes:
    encoded = base64.b64encode(
        json.dumps(PAGE_STATE if state is None else state).encode()
    ).decode()
    return f'<html><script id="initialState">{encoded}</script></html>'.encode()


SONG_A_ID = "1AWQoqb9bSvzTjaLralEkT"
SONG_B_ID = "0NfYAsKygCYwPA2BgTZ1qg"


def http_response(body: bytes = None):
    """Stand-in for urlopen's response object."""
    payload = page_html() if body is None else body

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return "https://open.spotify.com/playlist/" + PLAYLIST_ID

        def read(self, size=None):
            return payload

    return FakeResponse()


class FakeDeezerAPI:
    """Matches only "Song A"; everything else is unmatched."""

    def get_track_id_from_metadata(self, artist, track, album):
        return "111" if track == "Song A" else "0"

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
        with spotify_service._TRACK_CACHE_LOCK:
            spotify_service._TRACK_CACHE.clear()
        with spotify_service._SYNC_LOCK:
            spotify_service._SYNC_JOBS.clear()
            spotify_service._RUNNING_PLAYLISTS.clear()

        # Nothing in the suite may reach the network; tests that need HTTP
        # override this with serve_playlist().
        guard = patch(
            "urllib.request.urlopen", side_effect=AssertionError("unexpected network call")
        )
        guard.start()
        self.addCleanup(guard.stop)

    @staticmethod
    def serve_playlist(body: bytes = None):
        """Serve the main-page fixture (or arbitrary markup) to the reader."""
        return patch("urllib.request.urlopen", return_value=http_response(page_html() if body is None else body))

    def use_stubbed_playlist(self) -> None:
        patcher = self.serve_playlist()
        patcher.start()
        self.addCleanup(patcher.stop)

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

    def test_follows_short_share_links(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def geturl(self):
                return "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=x"

            def read(self, size=None):
                return b""

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            self.assertEqual(
                spotify_service.parse_playlist_id("https://spotify.link/AbCdEf123"),
                "37i9dQZF1DXcBWIGoYBM5M",
            )

    def test_short_link_falls_back_to_the_landing_page_markup(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def geturl(self):
                return "https://spotify.link/AbCdEf123"

            def read(self, size=None):
                return b'<a href="https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M">go</a>'

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            self.assertEqual(
                spotify_service.parse_playlist_id("https://spotify.link/AbCdEf123"),
                "37i9dQZF1DXcBWIGoYBM5M",
            )

    def test_unresolvable_short_link_reports_a_parse_error(self) -> None:
        with patch("urllib.request.urlopen", side_effect=OSError("offline")):
            with self.assertRaises(spotify_service.SpotifyError) as ctx:
                spotify_service.parse_playlist_id("https://spotify.link/AbCdEf123")
        self.assertIn("does not look like", str(ctx.exception))

    def test_rejects_non_playlist_links(self) -> None:
        for value in (
            "",
            "https://open.spotify.com/album/123",
            "nope",
            # A truncated or placeholder id must fail here, not at the API.
            "https://open.spotify.com/playlist/YOUR_ID_HERE",
        ):
            with self.assertRaises(spotify_service.SpotifyError):
                spotify_service.parse_playlist_id(value)


class ConfigTests(SpotifyServiceTestCase):
    def test_partial_updates_keep_existing_values(self) -> None:
        spotify_service.save_config({"check_interval_minutes": 30, "quality": "MP3_320"})
        spotify_service.save_config({"auto_sync_enabled": True})

        config = spotify_service.load_config()
        self.assertEqual(config["check_interval_minutes"], 30)
        self.assertEqual(config["quality"], "MP3_320")
        self.assertTrue(config["auto_sync_enabled"])

    def test_rejects_unsupported_quality(self) -> None:
        with self.assertRaises(spotify_service.SpotifyError):
            spotify_service.save_config({"quality": "OGG"})


class PlaylistReaderTests(SpotifyServiceTestCase):
    """Playlists are read from Spotify's public pages, with no credentials."""

    def test_reads_public_playlist_from_the_main_page(self) -> None:
        with self.serve_playlist():
            data = spotify_service.fetch_playlist(PLAYLIST_ID)

        self.assertEqual(data["name"], "Road Trip")
        self.assertEqual(data["owner"], "Max")
        # Mid-size cover is preferred over the 640px one.
        self.assertEqual(data["image_url"], "http://img/300.jpg")
        # The podcast episode is dropped.
        self.assertEqual(data["track_count"], 2)

        first, second = data["tracks"]
        self.assertEqual(first["spotify_id"], SONG_A_ID)
        self.assertEqual(first["duration_seconds"], 210)
        # The album is only available from this reader, and sharpens matching.
        self.assertEqual(first["album"], "Alb")
        # The primary artist is what Deezer matching keys on.
        self.assertEqual(second["artist"], "Band")
        self.assertEqual(second["artists"], ["Band", "Guest"])

    def test_reports_tracks_beyond_the_readable_page(self) -> None:
        state = json.loads(json.dumps(PAGE_STATE))
        entity = state["entities"]["items"]["spotify:playlist:" + PLAYLIST_ID]
        entity["content"]["totalCount"] = 120

        with self.serve_playlist(page_html(state)):
            data = spotify_service.fetch_playlist(PLAYLIST_ID)

        self.assertEqual(data["track_count"], 2)
        self.assertEqual(data["incomplete_count"], 118)

    def test_falls_back_to_the_embed_page(self) -> None:
        # The main page is unreadable; the embed page still answers. The embed
        # lags behind playlist edits, so it is only ever the fallback.
        with patch(
            "urllib.request.urlopen",
            side_effect=[http_response(b"<html>changed</html>"), http_response(EMBED_HTML.encode())],
        ):
            data = spotify_service.fetch_playlist(PLAYLIST_ID)

        self.assertEqual(data["name"], "Road Trip")
        self.assertEqual(data["track_count"], 2)

    def test_unreadable_page_reports_an_error(self) -> None:
        with self.serve_playlist(b"<html>no data here</html>"):
            with self.assertRaises(spotify_service.SpotifyError):
                spotify_service.fetch_playlist(PLAYLIST_ID)

    def test_missing_playlist_reports_not_found(self) -> None:
        error = urllib.error.HTTPError("http://x", 404, "gone", {}, io.BytesIO(b""))
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(spotify_service.SpotifyError) as ctx:
                spotify_service.fetch_playlist(PLAYLIST_ID)
        self.assertIn("not found", str(ctx.exception).lower())


class PlaylistTrackingTests(SpotifyServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.use_stubbed_playlist()

    def test_add_playlist_stores_metadata_and_rejects_duplicates(self) -> None:
        spotify_service.add_playlist("https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsH4n")

        playlists = spotify_service.list_playlists()
        self.assertEqual(len(playlists), 1)
        self.assertEqual(playlists[0]["name"], "Road Trip")
        self.assertEqual(playlists[0]["owner"], "Max")
        # The episode and the removed track are not counted.
        self.assertEqual(playlists[0]["track_count"], 2)

        with self.assertRaises(spotify_service.SpotifyError):
            spotify_service.add_playlist("https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsH4n")

    def test_remove_playlist_requires_a_tracked_playlist(self) -> None:
        with self.assertRaises(spotify_service.SpotifyError):
            spotify_service.remove_playlist("3cEYpjA9oz9GiPac4AsH4n")


class SyncTests(SpotifyServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.use_stubbed_playlist()
        # The iPod mirror talks to the device; it is covered on its own below.
        self.mirror_calls: list[list[dict]] = []
        mirror = patch(
            "spotify_service._mirror_playlist_to_ipod",
            side_effect=lambda _pid, _name, _mount, tracks: (
                self.mirror_calls.append(tracks) or 'iPod playlist "Road Trip": 1 track(s).'
            ),
        )
        mirror.start()
        self.addCleanup(mirror.stop)
        spotify_service.add_playlist("https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsH4n")

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
            spotify_service.start_sync("3cEYpjA9oz9GiPac4AsH4n", "/ipod", "MP3_320")
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

        # The device playlist is reconciled against every track in the Spotify
        # playlist, not just the ones downloaded in this run.
        self.assertEqual(len(self.mirror_calls), 1)
        self.assertEqual([t["title"] for t in self.mirror_calls[0]], ["Song A", "Song B"])
        self.assertIn("iPod playlist", job["message"])

        states = {
            track["title"]: track["sync_state"]
            for track in spotify_service.playlist_tracks("3cEYpjA9oz9GiPac4AsH4n")["tracks"]
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
            spotify_service.start_sync("3cEYpjA9oz9GiPac4AsH4n", "/ipod")
            self._wait_for_job()
            spotify_service.start_sync("3cEYpjA9oz9GiPac4AsH4n", "/ipod")
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
            spotify_service.start_sync("3cEYpjA9oz9GiPac4AsH4n", "/ipod")
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
            spotify_service.start_sync("3cEYpjA9oz9GiPac4AsH4n", "/ipod")
            self._wait_for_job()

        spotify_service.reset_playlist_sync_state("3cEYpjA9oz9GiPac4AsH4n")

        playlist = spotify_service.list_playlists()[0]
        self.assertEqual(playlist["synced_count"], 0)
        self.assertEqual(playlist["unmatched_count"], 0)


class BackfillTests(SpotifyServiceTestCase):
    """Tracks synced before Deezer tags were recorded get them filled in."""

    def setUp(self) -> None:
        super().setUp()
        self.use_stubbed_playlist()
        spotify_service.add_playlist("https://open.spotify.com/playlist/" + PLAYLIST_ID)
        spotify_service._update_playlist(PLAYLIST_ID, synced_ids=[SONG_A_ID], synced_tracks={})

    def test_resolves_missing_tags_once(self) -> None:
        with self.serve_playlist():
            tracks = spotify_service.fetch_playlist(PLAYLIST_ID)["tracks"]

        with patch("spotify_service.connect_deezer", return_value=FakeDeezer()), patch(
            "spotify_service._match_on_deezer",
            return_value={"id": "111", "title": "Song A - Remastered", "artist": "Band"},
        ) as matcher:
            spotify_service._backfill_deezer_tags(PLAYLIST_ID, tracks)
            # Only the synced track needs tags, and a second pass is a no-op.
            self.assertEqual(matcher.call_count, 1)
            spotify_service._backfill_deezer_tags(PLAYLIST_ID, tracks)
            self.assertEqual(matcher.call_count, 1)

        with spotify_service._PLAYLISTS_LOCK:
            record = next(p for p in spotify_service._load_playlists() if p["id"] == PLAYLIST_ID)
        self.assertEqual(
            record["synced_tracks"][SONG_A_ID], {"title": "Song A - Remastered", "artist": "Band"}
        )

    def test_survives_a_missing_deezer_session(self) -> None:
        with self.serve_playlist():
            tracks = spotify_service.fetch_playlist(PLAYLIST_ID)["tracks"]

        with patch(
            "spotify_service.connect_deezer",
            side_effect=spotify_service.DeemixError("no ARL"),
        ):
            spotify_service._backfill_deezer_tags(PLAYLIST_ID, tracks)  # must not raise


class IpodMirrorTests(SpotifyServiceTestCase):
    """The tracked playlist is reproduced on the device with the same songs."""

    def setUp(self) -> None:
        super().setUp()
        self.use_stubbed_playlist()
        spotify_service.add_playlist("https://open.spotify.com/playlist/" + PLAYLIST_ID)
        # Song A downloaded (Deezer spells it with a version suffix), Song B not.
        spotify_service._update_playlist(
            PLAYLIST_ID,
            synced_ids=[SONG_A_ID],
            synced_tracks={SONG_A_ID: {"title": "Song A - Remastered", "artist": "Band"}},
        )
        self.library = {
            "tracks": [
                {"id": 7, "title": "Song A - Remastered", "artist": "Band"},
                {"id": 8, "title": "Something Else", "artist": "Other"},
            ],
            "playlists": [],
        }

    def _run_mirror(self):
        with patch("spotify_service.load_library", return_value=self.library), patch(
            "spotify_service.create_ipod_playlist"
        ) as create, patch("spotify_service.add_tracks_to_ipod_playlist") as add, patch(
            "spotify_service.remove_tracks_from_ipod_playlist"
        ) as remove, patch(
            "spotify_service.delete_ipod_playlist"
        ) as delete:
            tracks = spotify_service.fetch_playlist(PLAYLIST_ID)["tracks"]
            message = spotify_service._mirror_playlist_to_ipod(
                PLAYLIST_ID, "Road Trip", "/ipod", tracks
            )
        return message, create, add, remove, delete

    def test_creates_the_playlist_with_the_synced_tracks(self) -> None:
        with self.serve_playlist():
            message, create, add, remove, _delete = self._run_mirror()

        create.assert_called_once_with("/ipod", "Road Trip")
        add.assert_called_once_with("/ipod", "Road Trip", [7])
        self.assertFalse(remove.called)
        self.assertIn("1 track(s)", message)

        record = spotify_service.list_playlists()[0]
        self.assertEqual(record["ipod_playlist_name"], "Road Trip")
        self.assertEqual(record["ipod_track_count"], 1)

    def test_removes_tracks_that_left_the_spotify_playlist(self) -> None:
        # The device playlist holds an extra track that is no longer wanted.
        self.library["playlists"] = [{"name": "Road Trip", "track_ids": [7, 99]}]

        with self.serve_playlist():
            _message, _create, add, remove, _delete = self._run_mirror()

        remove.assert_called_once_with("/ipod", "Road Trip", [99])
        self.assertFalse(add.called)

    def test_renaming_the_playlist_drops_the_old_mirror(self) -> None:
        spotify_service._update_playlist(PLAYLIST_ID, ipod_playlist_name="Old Name")

        with self.serve_playlist():
            _message, create, _add, _remove, delete = self._run_mirror()

        delete.assert_called_once_with("/ipod", "Old Name")
        create.assert_called_once_with("/ipod", "Road Trip")

    def test_matches_across_featured_artist_and_version_differences(self) -> None:
        # The device carries Deezer's tags reshaped by the converter: a featured
        # artist Spotify does not list, and a version suffix.
        self.library["tracks"] = [
            {"id": 11, "title": "Song A (Remastered)", "artist": "Band feat. Guest"},
        ]
        spotify_service._update_playlist(PLAYLIST_ID, synced_tracks={})

        with self.serve_playlist():
            _message, _create, add, _remove, _delete = self._run_mirror()

        add.assert_called_once_with("/ipod", "Road Trip", [11])

    def test_matches_on_title_alone_when_unambiguous(self) -> None:
        self.library["tracks"] = [{"id": 12, "title": "Song A", "artist": "Completely Different"}]
        spotify_service._update_playlist(PLAYLIST_ID, synced_tracks={})

        with self.serve_playlist():
            _message, _create, add, _remove, _delete = self._run_mirror()

        add.assert_called_once_with("/ipod", "Road Trip", [12])

    def test_ambiguous_title_with_no_artist_match_is_not_guessed(self) -> None:
        self.library["tracks"] = [
            {"id": 12, "title": "Song A", "artist": "Some Band"},
            {"id": 13, "title": "Song A", "artist": "Another Band"},
        ]
        spotify_service._update_playlist(PLAYLIST_ID, synced_tracks={})

        with self.serve_playlist():
            message, _create, add, _remove, _delete = self._run_mirror()

        self.assertFalse(add.called)
        self.assertEqual(message, "")

    def test_names_the_tracks_it_could_not_locate(self) -> None:
        spotify_service._update_playlist(
            PLAYLIST_ID,
            synced_ids=[SONG_A_ID, SONG_B_ID],
            synced_tracks={SONG_A_ID: {"title": "Song A - Remastered", "artist": "Band"}},
        )

        with self.serve_playlist():
            message, _create, _add, _remove, _delete = self._run_mirror()

        self.assertIn("1 synced track(s) not found", message)
        self.assertIn("Song B", message)

    def test_reports_tracks_it_cannot_find_in_the_library(self) -> None:
        self.library["tracks"] = [{"id": 8, "title": "Something Else", "artist": "Other"}]
        spotify_service._update_playlist(
            PLAYLIST_ID,
            synced_ids=[SONG_A_ID, SONG_B_ID],
            synced_tracks={SONG_A_ID: {"title": "Song A", "artist": "Band"}},
        )

        with self.serve_playlist():
            message, _create, _add, _remove, _delete = self._run_mirror()

        self.assertEqual(message, "")


if __name__ == "__main__":
    unittest.main()
