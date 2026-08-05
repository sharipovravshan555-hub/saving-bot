import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from downloader import Downloader
from music_search import Song, search_music
from state_store import StateStore
from stats import StatsStore


class DownloaderTests(unittest.TestCase):
    def test_supported_media_hosts(self):
        urls = [
            "https://youtu.be/abc",
            "https://www.youtube.com/watch?v=abc",
            "https://www.instagram.com/reel/abc/",
            "https://vm.tiktok.com/abc/",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(Downloader.validate_url(url), url)

    def test_rejects_untrusted_and_credential_urls(self):
        urls = [
            "http://127.0.0.1/secret",
            "https://youtube.com.evil.example/video",
            "https://user:pass@youtube.com/watch?v=abc",
            "file:///etc/passwd",
        ]
        for url in urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    Downloader.validate_url(url)

    def test_canonical_youtube_url_drops_tracking(self):
        result = Downloader.canonical_url(
            "https://m.youtube.com/watch?v=abc123&utm_source=test"
        )
        self.assertEqual(result, "https://www.youtube.com/watch?v=abc123")


class StateStoreTests(unittest.TestCase):
    def test_language_and_callback_state_persist_and_are_user_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.db"
            store = StateStore(path)
            store.set_language(10, "ru")
            request_id = store.create(10, "download", {"url": "https://youtu.be/a"})

            reopened = StateStore(path)
            self.assertEqual(reopened.language(10), "ru")
            self.assertEqual(
                reopened.get(request_id, 10, "download"),
                {"url": "https://youtu.be/a"},
            )
            self.assertIsNone(reopened.get(request_id, 11, "download"))
            self.assertIsNone(reopened.get(request_id, 10, "music"))

    def test_expired_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.db"
            store = StateStore(path, ttl=60)
            request_id = store.create(10, "music", {"query": "song"})
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    "UPDATE requests SET created_at = ? WHERE request_id = ?",
                    (int(time.time()) - 61, request_id),
                )
                connection.commit()
            finally:
                connection.close()
            self.assertIsNone(store.get(request_id, 10, "music"))


class MusicSearchTests(unittest.TestCase):
    def test_real_pagination_uses_multiple_pages(self):
        songs = tuple(Song(f"Song {index}", f"https://youtu.be/{index}", index) for index in range(25))
        with patch("music_search._search_entries", return_value=songs):
            page = search_music("query", 2)
        self.assertEqual(page["total_pages"], 3)
        self.assertEqual(len(page["results"]), 10)
        self.assertEqual(page["results"][0].title, "Song 10")


class StatsStoreTests(unittest.TestCase):
    def test_corrupt_file_recovers_and_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stats.json"
            path.write_text("not-json", encoding="utf-8")
            store = StatsStore(path)
            store.touch_user(1)
            store.count_success("video")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["total_users"], 1)
            self.assertEqual(data["total_videos"], 1)


if __name__ == "__main__":
    unittest.main()
