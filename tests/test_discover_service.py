import os
import tempfile
import time
import unittest
from unittest.mock import patch

import discover_service as ds


class _SyncThread:
    """Runs a background job inline so the add flow can be asserted on."""

    def __init__(self, target=None, args=(), daemon=None):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


def _track(path, title, album, artist, playcount=0):
    return {
        "ipod_path": path,
        "title": title,
        "album": album,
        "artist": artist,
        "album_artist": artist,
        "playcount": playcount,
        "genre": "Rock",
    }


EXISTING = _track(":iPod_Control:Music:F00:AAAA.m4a", "Airbag", "OK Computer", "Radiohead", 12)
NEW_A = _track(":iPod_Control:Music:F01:BBBB.m4a", "Song One", "New Album", "Some Band")
NEW_B = _track(":iPod_Control:Music:F02:CCCC.m4a", "Song Two", "New Album", "Some Band")
# Uploaded by hand while the trial download was running; must not be attributed.
UNRELATED = _track(":iPod_Control:Music:F03:DDDD.m4a", "Other", "Other Record", "Someone Else")

ALBUM = {"id": "555", "title": "New Album", "artist": "Some Band", "artist_id": "77", "cover_url": "", "reason": "Test"}


class DiscoverServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "DISCOVER_STATE_PATH": os.path.join(self.tmp.name, "state.json"),
                "DISCOVER_CACHE_PATH": os.path.join(self.tmp.name, "cache.json"),
            },
        )
        self.env.start()
        self.patches = [
            patch.object(ds.threading, "Thread", _SyncThread),
            patch.object(ds, "_check_can_add", lambda mountpoint: None),
            patch.object(ds, "get_deemix_job", return_value={
                "status": "done",
                "items": [{"status": "done", "progress": 100}],
                "added_to_ipod_count": 2,
            }),
            patch.object(ds, "start_download_job", return_value="job-1"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.env.stop()
        self.tmp.cleanup()

    def _add(self, mode="trial", after=None):
        libraries = [
            {"mountpoint": "/ipod", "tracks": [EXISTING]},
            {"mountpoint": "/ipod", "tracks": after or [EXISTING, NEW_A, NEW_B, UNRELATED]},
        ]
        with patch.object(ds, "load_library", side_effect=libraries):
            ds.add_album(ALBUM, mode, "/ipod")
        return ds._get_album("555")

    def test_trial_records_only_the_albums_new_tracks(self):
        record = self._add()
        self.assertEqual(record["status"], "trial")
        paths = sorted(t["ipod_path"] for t in record["tracks"])
        self.assertEqual(paths, sorted([NEW_A["ipod_path"], NEW_B["ipod_path"]]))
        self.assertAlmostEqual(record["expires_at"] - record["added_at"], 7 * ds.DAY_SECONDS, delta=5)

    def test_permanent_add_is_kept_without_timer(self):
        record = self._add(mode="permanent")
        self.assertEqual(record["status"], "kept")
        self.assertEqual(record["expires_at"], 0)

    def test_trial_whose_tracks_cannot_be_found_is_kept_not_timed(self):
        record = self._add(after=[EXISTING, UNRELATED])
        self.assertEqual(record["status"], "kept")
        self.assertEqual(record["tracks"], [])

    def test_failed_download_marks_record_failed(self):
        with patch.object(ds, "get_deemix_job", return_value={
            "status": "error", "items": [{"status": "error", "error": "No rights"}], "added_to_ipod_count": 0,
        }), patch.object(ds, "load_library", return_value={"mountpoint": "/ipod", "tracks": [EXISTING]}):
            ds.add_album(ALBUM, "trial", "/ipod")
        record = ds._get_album("555")
        self.assertEqual(record["status"], "failed")
        self.assertIn("No rights", record["message"])

    def test_expired_trial_is_deleted_silently(self):
        self._add()
        ds._update_album("555", expires_at=time.time() - 1)
        library = {"mountpoint": "/ipod", "tracks": [EXISTING, NEW_A, dict(NEW_B, playcount=3), UNRELATED]}
        with patch.object(ds, "_ipod_present", return_value=True), patch.object(
            ds, "load_library", return_value=library
        ), patch.object(ds, "delete_tracks") as delete:
            expired = ds.sweep_expired("/ipod", force=True)
        self.assertEqual(expired, 1)
        delete.assert_called_once()
        self.assertEqual(sorted(delete.call_args[0][1]), sorted([NEW_A["ipod_path"], NEW_B["ipod_path"]]))
        record = ds._get_album("555")
        self.assertEqual(record["status"], "expired")
        self.assertEqual(record["plays"], 3)

    def test_expiry_skips_paths_that_now_hold_other_music(self):
        # A different iPod on the same mountpoint can reuse the file names.
        self._add()
        ds._update_album("555", expires_at=time.time() - 1)
        other_ipod = {
            "mountpoint": "/ipod",
            "tracks": [dict(NEW_A, title="Not It", album="Different"), dict(NEW_B, album="Different")],
        }
        with patch.object(ds, "_ipod_present", return_value=True), patch.object(
            ds, "load_library", return_value=other_ipod
        ), patch.object(ds, "delete_tracks") as delete:
            ds.sweep_expired("/ipod", force=True)
        delete.assert_not_called()

    def test_trial_not_due_is_left_alone(self):
        self._add()
        with patch.object(ds, "_ipod_present", return_value=True), patch.object(ds, "delete_tracks") as delete:
            self.assertEqual(ds.sweep_expired("/ipod", force=True), 0)
        delete.assert_not_called()
        self.assertEqual(ds._get_album("555")["status"], "trial")

    def test_expiry_waits_for_the_ipod(self):
        self._add()
        ds._update_album("555", expires_at=time.time() - 1)
        with patch.object(ds, "_ipod_present", return_value=False), patch.object(ds, "delete_tracks") as delete:
            self.assertEqual(ds.sweep_expired("/ipod", force=True), 0)
        delete.assert_not_called()
        self.assertEqual(ds._get_album("555")["status"], "trial")

    def test_keep_stops_the_timer(self):
        self._add()
        ds.keep_album("555")
        record = ds._get_album("555")
        self.assertEqual(record["status"], "kept")
        self.assertEqual(record["expires_at"], 0)

    def test_extend_adds_days(self):
        record = self._add()
        ds.extend_album("555", 7)
        self.assertAlmostEqual(
            ds._get_album("555")["expires_at"] - record["expires_at"], 7 * ds.DAY_SECONDS, delta=1
        )

    def test_keep_with_upgrade_swaps_the_trial_copy(self):
        self._add()
        upgraded_a = dict(NEW_A, ipod_path=":iPod_Control:Music:F09:EEEE.m4a")
        libraries = [
            {"mountpoint": "/ipod", "tracks": [EXISTING, NEW_A, NEW_B]},
            {"mountpoint": "/ipod", "tracks": [EXISTING, NEW_A, NEW_B, upgraded_a]},
            {"mountpoint": "/ipod", "tracks": [EXISTING, NEW_A, NEW_B, upgraded_a]},
        ]
        with patch.object(ds, "load_library", side_effect=libraries), patch.object(ds, "delete_tracks") as delete:
            ds.keep_album("555", upgrade=True, quality="FLAC")
        self.assertEqual(sorted(delete.call_args[0][1]), sorted([NEW_A["ipod_path"], NEW_B["ipod_path"]]))
        record = ds._get_album("555")
        self.assertEqual(record["status"], "kept")
        self.assertEqual([t["ipod_path"] for t in record["tracks"]], [upgraded_a["ipod_path"]])

    def test_track_trial_records_only_that_song(self):
        libraries = [
            {"mountpoint": "/ipod", "tracks": [EXISTING]},
            {"mountpoint": "/ipod", "tracks": [EXISTING, NEW_A, NEW_B, UNRELATED]},
        ]
        song = {"id": "555", "title": "Song Two", "artist": "Some Band", "album": "New Album"}
        with patch.object(ds, "load_library", side_effect=libraries), patch.object(
            ds, "start_download_job", return_value="job-2"
        ) as start:
            ds.add_album(song, "trial", "/ipod", item_type="track")
        self.assertEqual(start.call_args[0][0][0]["type"], "track")
        self.assertEqual(start.call_args[0][0][0]["id"], "555")
        # Kept apart from an album that happens to share the Deezer id.
        record = ds._get_album("track-555")
        self.assertEqual(record["status"], "trial")
        self.assertEqual([t["ipod_path"] for t in record["tracks"]], [NEW_B["ipod_path"]])

    def test_retry_keeps_the_item_type(self):
        with patch.object(ds, "get_deemix_job", return_value={
            "status": "error", "items": [{"status": "error", "error": "x"}], "added_to_ipod_count": 0,
        }), patch.object(ds, "load_library", return_value={"mountpoint": "/ipod", "tracks": [EXISTING]}):
            ds.add_album({"id": "9", "title": "Song Two", "artist": "Some Band"}, "trial", "/ipod", item_type="track")
        with patch.object(ds, "load_library", return_value={"mountpoint": "/ipod", "tracks": [EXISTING]}), patch.object(
            ds, "start_download_job", return_value="job-3"
        ) as start:
            ds.retry_album("track-9", "/ipod")
        self.assertEqual(start.call_args[0][0][0], {"id": "9", "type": "track", "title": "Song Two", "artist": "Some Band"})

    def test_trial_limit(self):
        ds.save_preferences({"max_active_trials": 1})
        self._add()
        with self.assertRaises(ds.DiscoverError):
            ds.add_album(dict(ALBUM, id="556"), "trial", "/ipod")

    def test_suggestions_hide_dismissed_added_and_blocked(self):
        items = [
            {"id": "1", "artist_id": "a"},
            {"id": "2", "artist_id": "b"},
            {"id": "3", "artist_id": "c"},
            {"id": "555", "artist_id": "d"},
        ]
        ds._mutate_state(lambda s: s.update(suggestions={"generated_at": 1, "temperature": 0.5, "items": items}))
        self._add()
        ds.dismiss_album("1")
        ds.block_artist("b", "B")
        self.assertEqual([i["id"] for i in ds.get_suggestions()["items"]], ["3"])


class RecommendationHelperTests(unittest.TestCase):
    def test_owned_album_matches_through_edition_suffixes(self):
        profile = ds._library_profile([EXISTING])
        self.assertTrue(ds._is_owned("OK Computer (Collector's Edition)", "Radiohead", profile["owned"]))
        self.assertTrue(ds._is_owned("OK Computer - Remastered", "Radiohead feat. Someone", profile["owned"]))
        self.assertFalse(ds._is_owned("OK Computer", "Some Covers Band", profile["owned"]))

    def test_play_counts_weight_seeds(self):
        tracks = [_track(f"p{i}", "t", "A", "Played", 50) for i in range(2)]
        tracks += [_track(f"u{i}", "t", "B", "Unplayed", 0) for i in range(4)]
        artists = ds._library_profile(tracks)["artists"]
        self.assertGreater(artists["played"]["weight"], artists["unplayed"]["weight"])

    def test_temperature_moves_the_preferred_distance(self):
        self.assertGreater(ds._distance_affinity(0, 0.0), ds._distance_affinity(3, 0.0))
        self.assertGreater(ds._distance_affinity(3, 1.0), ds._distance_affinity(0, 1.0))

    def test_compilations_are_filtered(self):
        for title in ("Greatest Hits", "Live at Leeds", "Album (Live)", "The Essential X"):
            self.assertIsNotNone(ds._NOT_A_STUDIO_ALBUM.search(title), title)
        for title in ("Live Through This", "Hits Different", "OK Computer"):
            self.assertIsNone(ds._NOT_A_STUDIO_ALBUM.search(title), title)


class DiscoverRoutesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"DISCOVER_STATE_PATH": os.path.join(self.tmp.name, "state.json")})
        self.env.start()
        from app import app

        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_preferences_are_clamped(self):
        response = self.client.post("/api/discover/preferences", json={"temperature": 3, "trial_days": 0})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["temperature"], 1.0)
        self.assertEqual(response.get_json()["trial_days"], 1)

    def test_refresh_requires_a_mountpoint(self):
        response = self.client.post("/api/discover/suggestions/refresh", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Connect an iPod", response.get_json()["error"])

    def test_add_rejects_unknown_mode(self):
        response = self.client.post(
            "/api/discover/albums", json={"album": ALBUM, "mode": "forever", "mountpoint": "/ipod"}
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
