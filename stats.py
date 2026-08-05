import json
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any


class StatsStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.data = self._load()
        if not self.data.get("start_time"):
            self.data["start_time"] = time.time()
            self.save()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                pass
        return {
            "start_time": time.time(),
            "total_users": 0,
            "total_videos": 0,
            "total_mp3": 0,
            "daily": {},
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    @staticmethod
    def today() -> str:
        return date.today().isoformat()

    def touch_user(self, user_id: int) -> None:
        with self.lock:
            day = self.today()
            self.data.setdefault("daily", {})
            self.data["daily"].setdefault(day, {"users": [], "videos": 0, "mp3": 0})
            if user_id not in self.data["daily"][day]["users"]:
                self.data["daily"][day]["users"].append(user_id)

            all_users = {
                user
                for stats in self.data["daily"].values()
                for user in stats.get("users", [])
            }
            self.data["total_users"] = len(all_users)
            self.save()

    def count_success(self, kind: str) -> None:
        with self.lock:
            day = self.today()
            self.data.setdefault("daily", {})
            self.data["daily"].setdefault(day, {"users": [], "videos": 0, "mp3": 0})

            if kind == "audio":
                self.data["total_mp3"] = self.data.get("total_mp3", 0) + 1
                self.data["daily"][day]["mp3"] += 1
            else:
                self.data["total_videos"] = self.data.get("total_videos", 0) + 1
                self.data["daily"][day]["videos"] += 1
            self.save()

    def report(self) -> str:
        day = self.today()
        uptime = int(time.time() - self.data.get("start_time", time.time()))
        hours = uptime // 3600
        minutes = (uptime % 3600) // 60
        today_stats = self.data.get("daily", {}).get(day, {})

        return (
            "ADMIN PANEL\n\n"
            f"Jami userlar: {self.data.get('total_users', 0)}\n"
            f"Jami video: {self.data.get('total_videos', 0)}\n"
            f"Jami MP3: {self.data.get('total_mp3', 0)}\n\n"
            "Bugun:\n"
            f"Aktiv: {len(today_stats.get('users', []))}\n"
            f"Video: {today_stats.get('videos', 0)}\n"
            f"MP3: {today_stats.get('mp3', 0)}\n\n"
            f"Uptime: {hours} soat {minutes} daqiqa"
        )
