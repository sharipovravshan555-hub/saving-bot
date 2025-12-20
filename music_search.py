# music_search.py
import math
from typing import Dict
from yt_dlp import YoutubeDL

PAGE_SIZE = 10  # har sahifada 10 ta qo'shiq

def search_music(query: str, page: int = 1) -> Dict:
    """
    YouTube'dan musiqa qidiradi.
    Natija: 10 tadan qo'shiq + pagination info
    """
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(
            f"ytsearch50:{query}",
            download=False
        )

    entries = info.get("entries", [])
    total = len(entries)

    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_items = entries[start:end]

    results = []
    for e in page_items:
        if not e:
            continue
        results.append({
            "title": e.get("title"),
            "url": f"https://www.youtube.com/watch?v={e.get('id')}",
            "duration": e.get("duration") or 0,
        })

    return {
        "query": query,
        "page": page,
        "total": total,
        "total_pages": math.ceil(total / PAGE_SIZE) if total else 1,
        "results": results,
    }
