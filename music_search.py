import math
from dataclasses import dataclass
from functools import lru_cache

from yt_dlp import YoutubeDL

from config import COOKIES_FILE, NODE_EXECUTABLE, POT_SERVER_HOME

PAGE_SIZE = 10
SEARCH_LIMIT = 50


@dataclass(frozen=True)
class Song:
    title: str
    url: str
    duration: int


@lru_cache(maxsize=256)
def _search_entries(query: str) -> tuple[Song, ...]:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "js_runtimes": {"node": {"path": NODE_EXECUTABLE}},
        "extractor_args": {
            "youtubepot-bgutilscript": {"server_home": [str(POT_SERVER_HOME)]}
        },
    }
    if COOKIES_FILE.is_file():
        ydl_opts["cookiefile"] = str(COOKIES_FILE)

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch{SEARCH_LIMIT}:{query}", download=False)

    results = []
    for item in info.get("entries", []):
        if not item:
            continue
        video_id = item.get("id")
        if not video_id:
            continue
        results.append(
            Song(
                title=item.get("title") or "Untitled",
                url=f"https://www.youtube.com/watch?v={video_id}",
                duration=int(item.get("duration") or 0),
            )
        )
    return tuple(results)


def search_music(query: str, page: int = 1) -> dict:
    page = max(1, page)
    normalized_query = " ".join(query.casefold().split())
    entries = _search_entries(normalized_query)
    total = len(entries)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(page, total_pages)

    start = (page - 1) * PAGE_SIZE
    results = list(entries[start : start + PAGE_SIZE])

    return {
        "query": query,
        "page": page,
        "total": total,
        "total_pages": total_pages,
        "results": results,
    }
