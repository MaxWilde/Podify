import os
import tempfile
import unittest

from settings_service import scan_audio_files


class SettingsServiceTests(unittest.TestCase):
    def test_scan_audio_files_includes_only_flac_recursive(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            nested = os.path.join(root, "a", "b")
            os.makedirs(nested, exist_ok=True)

            flac_root = os.path.join(root, "song1.flac")
            flac_nested = os.path.join(nested, "song2.FLAC")
            mp3_nested = os.path.join(nested, "song3.mp3")

            with open(flac_root, "wb") as fh:
                fh.write(b"flac1")
            with open(flac_nested, "wb") as fh:
                fh.write(b"flac2")
            with open(mp3_nested, "wb") as fh:
                fh.write(b"mp3")

            files, indexed = scan_audio_files(root)

            self.assertEqual(set(files), {flac_root, flac_nested})
            self.assertEqual(set(indexed.keys()), {flac_root, flac_nested})


if __name__ == "__main__":
    unittest.main()
