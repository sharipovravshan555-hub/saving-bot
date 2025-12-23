#!/usr/bin/env python3
"""
SAVING BOT
Video + MP3 + Music Search
"""

import re
import time
import json
import asyncio
import tempfile
import shutil
import logging
import os
from pathlib import Path
from datetime import date
from typing import Dict, Any, Optional

from yt_dlp import YoutubeDL
from music_search import search_music

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = 5151373754

MAX_CONCURRENT_DOWNLOADS = 2
DOWNLOAD_READ_TIMEOUT = 600
TMP_ROOT = Path(tempfile.gettempdir()) / "saving_bot_tmp"
TMP_ROOT.mkdir(exist_ok=True)

URL_RE = re.compile(r"https?://[^\s]+")

# ================= LOG =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("saving_bot")

# ================= MEMORY =================
user_lang: Dict[int, str] = {}
pending_url: Dict[int, str] = {}
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
music_cache: Dict[int, list] = {}

# ================= TEXTS =================
TEXTS = {
    "uz": {
        "start": "Salom! Link yoki qo‘shiq nomini yozing 🎵",
        "choose_quality": "Sifatni tanlang:",
        "downloading": "⏳ Yuklanmoqda...",
        "sent_video": "🎬 Video tayyor",
        "sent_audio": "🎧 MP3 tayyor",
        "no_url": "Iltimos, link yoki qo‘shiq nomini yozing",
        "error": "❌ Xatolik yuz berdi",
    },
    "ru": {
        "start": "Привет! Отправь ссылку или название песни 🎵",
        "choose_quality": "Выберите качество:",
        "downloading": "⏳ Скачивается...",
        "sent_video": "🎬 Видео готово",
        "sent_audio": "🎧 MP3 готов",
        "no_url": "Отправьте ссылку или название песни",
        "error": "❌ Ошибка",
    },
    "en": {
        "start": "Hi! Send link or song name 🎵",
        "choose_quality": "Choose quality:",
        "downloading": "⏳ Downloading...",
        "sent_video": "🎬 Video ready",
        "sent_audio": "🎧 MP3 ready",
        "no_url": "Send link or song name",
        "error": "❌ Error",
    },
}

def T(uid: int, key: str) -> str:
    return TEXTS.get(user_lang.get(uid, "uz"), TEXTS["uz"])[key]

# ================= STATS =================
STATS_FILE = Path("stats.json")

def load_stats():
    if STATS_FILE.exists():
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    return {
        "start_time": time.time(),
        "total_users": 0,
        "total_videos": 0,
        "total_mp3": 0,
        "daily": {}
    }

def save_stats():
    STATS_FILE.write_text(json.dumps(STATS, indent=2), encoding="utf-8")

STATS = load_stats()

def today_key():
    return date.today().isoformat()

def mark_user(uid: int):
    t = today_key()
    STATS.setdefault("daily", {})
    STATS["daily"].setdefault(t, {"users": [], "videos": 0, "mp3": 0})
    if uid not in STATS["daily"][t]["users"]:
        STATS["daily"][t]["users"].append(uid)
    STATS["total_users"] = len({u for d in STATS["daily"].values() for u in d["users"]})
    save_stats()

# ================= DOWNLOAD =================
async def download_worker(app, uid, chat_id, url, mode, quality):
    mark_user(uid)

    job_tmp = TMP_ROOT / f"{uid}_{int(time.time())}"
    job_tmp.mkdir(exist_ok=True)

    msg = await app.bot.send_message(chat_id, T(uid, "downloading"))
    outtmpl = str(job_tmp / "%(title).200s.%(ext)s")

    if mode == "audio":
        STATS["total_mp3"] += 1
        STATS["daily"][today_key()]["mp3"] += 1
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "quiet": True
        }
    else:
        STATS["total_videos"] += 1
        STATS["daily"][today_key()]["videos"] += 1
        fmt = f"bestvideo[height<={quality}]+bestaudio/best"
        ydl_opts = {
            "format": fmt,
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
            "quiet": True
        }

    save_stats()

    def run():
        with YoutubeDL(ydl_opts) as y:
            y.extract_info(url, download=True)

    try:
        async with download_semaphore:
            await asyncio.get_event_loop().run_in_executor(None, run)

        file = max(job_tmp.glob("*"), key=lambda p: p.stat().st_size)

        if mode == "audio":
            await app.bot.send_audio(chat_id, audio=open(file, "rb"))
            await app.bot.send_message(chat_id, T(uid, "sent_audio"))
        else:
            try:
                await app.bot.send_video(chat_id, video=open(file, "rb"))
            except:
                await app.bot.send_document(chat_id, document=open(file, "rb"))
            await app.bot.send_message(chat_id, T(uid, "sent_video"))

    except Exception as e:
        logger.error(e)
        await app.bot.send_message(chat_id, T(uid, "error"))
    finally:
        shutil.rmtree(job_tmp, ignore_errors=True)

# ================= HANDLERS =================
async def start(update, ctx):
    uid = update.effective_user.id
    kb = [
        [InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang_uz")],
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
    ]
    await update.message.reply_text("Tilni tanlang:", reply_markup=InlineKeyboardMarkup(kb))

async def lang_cb(update, ctx):
    q = update.callback_query
    await q.answer()
    user_lang[q.from_user.id] = q.data.split("_")[1]
    await q.edit_message_text(T(q.from_user.id, "start"))

async def text_handler(update, ctx):
    msg = update.message
    uid = msg.from_user.id
    text = msg.text.strip()
    t = msg.text.strip()
    ctx.user_data["music_query"] = t


    # URL bo‘lsa
    m = URL_RE.search(text)
    if m:
        pending_url[uid] = m.group(0)
        kb = [
            [InlineKeyboardButton("360p", callback_data="q_360"),
             InlineKeyboardButton("720p", callback_data="q_720")],
            [InlineKeyboardButton("1080p", callback_data="q_1080"),
             InlineKeyboardButton("MP3", callback_data="q_mp3")],
        ]
        return await msg.reply_text(T(uid, "choose_quality"), reply_markup=InlineKeyboardMarkup(kb))

    # MUSIC SEARCH
    data = search_music(text, page=1)
    if not data["results"]:
        return await msg.reply_text("❌ Hech narsa topilmadi")
    music_cache[uid] = data["results"]


    lines = [f"{i}. {x['title']}" for i, x in enumerate(data["results"], 1)]

    kb, row = [], []
    for i in range(1, len(data["results"]) + 1):
        row.append(InlineKeyboardButton(str(i), callback_data=f"music_{i}"))
        if i % 5 == 0:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    if data["total_pages"] > 1:
        kb.append([InlineKeyboardButton("➡️ Keyingi", callback_data="music_next_2")])

    await msg.reply_text(
        "🎵 Topilgan qo‘shiqlar:\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def quality_cb(update, ctx):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    url = pending_url.get(uid)

    if not url:
        return

    sel = q.data.replace("q_", "")
    mode = "audio" if sel == "mp3" else "video"
    quality = None if mode == "audio" else sel

    await q.edit_message_text("⏳ Boshlanmoqda...")
    ctx.application.create_task(
        download_worker(ctx.application, uid, q.message.chat_id, url, mode, quality)
    )
async def music_next_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    data_q = query.data  # masalan: music_next_2

    try:
        page = int(data_q.split("_")[-1])
    except:
        return

    # Oxirgi qidiruvni eslab qolgan bo‘lishimiz kerak
    query_text = ctx.user_data.get("music_query")
    if not query_text:
        return await query.edit_message_text("❌ Qidiruv topilmadi.")

    from music_search import search_music
    data = search_music(query_text, page)

    if not data["results"]:
        return await query.edit_message_text("❌ Hech narsa topilmadi.")

    # Matn
    lines = []
    for i, item in enumerate(data["results"], start=1):
        lines.append(f"{i}. {item['title']}")

    # Tugmalar (1 qatorda 5 tadan)
    kb = []
    row = []
    for i in range(1, len(data["results"]) + 1):
        row.append(
            InlineKeyboardButton(
                f"{i}",
                callback_data=f"music_{i}"
            )
        )
        if i % 5 == 0:
            kb.append(row)
            row = []

    if row:
        kb.append(row)

    # Keyingi sahifa bo‘lsa
    if data["page"] < data["total_pages"]:
        kb.append([
            InlineKeyboardButton(
                "➡️ Keyingi",
                callback_data=f"music_next_{data['page'] + 1}"
            )
        ])

    await query.edit_message_text(
        "🎵 Topilgan qo‘shiqlar:\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def music_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    data = query.data  # masalan: music_3

    if uid not in music_cache:
        return await query.message.reply_text("❌ Ro'yxat topilmadi.")

    try:
        index = int(data.split("_")[1]) - 1
        song = music_cache[uid][index]
    except:
        return await query.message.reply_text("❌ Noto‘g‘ri tanlov.")

    url = song["url"]

    await query.message.reply_text("🎧 MP3 yuklanmoqda...")

    # MP3 yuklash
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "outtmpl": "%(title).200s.%(ext)s",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }

    loop = asyncio.get_event_loop()

    def run_dl():
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info).replace(".webm", ".mp3").replace(".m4a", ".mp3")

    try:
        file_path = await loop.run_in_executor(None, run_dl)
        with open(file_path, "rb") as f:
            await query.message.reply_audio(audio=f)
        os.remove(file_path)
    except Exception as e:
        await query.message.reply_text("❌ MP3 yuklashda xatolik.")


async def admin_cmd(update, ctx):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    t = today_key()
    uptime = int(time.time() - STATS["start_time"])
    h, m = uptime // 3600, (uptime % 3600) // 60

    await update.message.reply_text(
        f"📊 ADMIN PANEL\n\n"
        f"👥 Jami userlar: {STATS['total_users']}\n"
        f"🎬 Jami video: {STATS['total_videos']}\n"
        f"🎧 Jami MP3: {STATS['total_mp3']}\n\n"
        f"📅 Bugun:\n"
        f"👤 Aktiv: {len(STATS['daily'].get(t, {}).get('users', []))}\n"
        f"🎬 Video: {STATS['daily'].get(t, {}).get('videos', 0)}\n"
        f"🎧 MP3: {STATS['daily'].get(t, {}).get('mp3', 0)}\n\n"
        f"⏱ Uptime: {h} soat {m} daqiqa"
    )
async def music_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    data = q.data  # masalan: music_3

    if uid not in music_cache:
        return await q.edit_message_text("❌ Ro‘yxat eskirgan, qayta qidiring")

    index = int(data.split("_")[1]) - 1
    songs = music_cache[uid]

    if index < 0 or index >= len(songs):
        return await q.edit_message_text("❌ Noto‘g‘ri tanlov")

    song = songs[index]
    url = song["url"]

    await q.edit_message_text("⏳ Yuklanmoqda...")

    # MP3 sifatida yuklaymiz
    context.application.create_task(
        download_worker(
            context.application,
            uid,
            q.message.chat_id,
            url,
            mode="audio",
            quality=None
        )
    )


# ================= MAIN =================
def main():
    req = HTTPXRequest(read_timeout=DOWNLOAD_READ_TIMEOUT)
    app = ApplicationBuilder().token(BOT_TOKEN).request(req).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CallbackQueryHandler(lang_cb, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(quality_cb, pattern="^q_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(music_cb, pattern=r"^music_"))
    app.add_handler(CallbackQueryHandler(quality_cb, pattern=r"^q_"))
    app.add_handler(CallbackQueryHandler(music_next_cb, pattern=r"^music_next_"))


    logger.info("SAVING BOT STARTED")
    app.run_polling()

if __name__ == "__main__":
    main()



