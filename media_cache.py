import hashlib
import json
import threading
import time
from pathlib import Path


class MediaCache:
    def __init__(self, path: Path, max_items: int = 2000):
        self.path = path
        self.max_items = max_items
        self.lock = threading.RLock()
        self.items = self._load()

    @staticmethod
    def _key(url: str, mode: str, quality: str | None) -> str:
        value = f"{mode}|{quality or ''}|{url}".encode("utf-8")
        return hashlib.sha256(value).hexdigest()

    def _load(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            items = data.get("items", {})
            return items if isinstance(items, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def get(self, url: str, mode: str, quality: str | None) -> dict | None:
        with self.lock:
            item = self.items.get(self._key(url, mode, quality))
            return dict(item) if item else None

    def put(
        self,
        url: str,
        mode: str,
        quality: str | None,
        file_id: str,
        send_as: str,
    ) -> None:
        with self.lock:
            self.items[self._key(url, mode, quality)] = {
                "file_id": file_id,
                "send_as": send_as,
                "saved_at": int(time.time()),
            }
            if len(self.items) > self.max_items:
                oldest = sorted(
                    self.items,
                    key=lambda key: self.items[key].get("saved_at", 0),
                )[: len(self.items) - self.max_items]
                for key in oldest:
                    self.items.pop(key, None)
            self._save()

    def delete(self, url: str, mode: str, quality: str | None) -> None:
        with self.lock:
            if self.items.pop(self._key(url, mode, quality), None):
                self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps({"version": 1, "items": self.items}, ensure_ascii=True),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
