import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from config import (
    ADMIN_CHAT_ID,
    AUDIT_RETENTION_DAYS,
    AUDIT_DB_FILE,
    BOT_API_BASE_FILE_URL,
    BOT_API_BASE_URL,
    BOT_API_LOCAL_MODE,
    BOT_TOKEN,
    COOKIES_FILE,
    DOWNLOAD_TIMEOUT,
    MAX_CONCURRENT_DOWNLOADS,
    MEDIA_CACHE_FILE,
    NODE_EXECUTABLE,
    POT_SERVER_HOME,
    STATE_DB_FILE,
    STATE_TTL,
    STATS_FILE,
    TELEGRAM_UPLOAD_LIMIT_MB,
    TMP_ROOT,
)
from audit import AuditStore
from downloader import (
    AuthenticationRequiredError,
    DownloadTimeoutError,
    Downloader,
    MediaTooLargeError,
    MediaUnavailableError,
)
from media_cache import MediaCache
from messages import text
from music_search import Song, search_music
from pot_server import ensure_pot_server
from stats import StatsStore
from state_store import StateStore

URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
DOWNLOAD_CAPTION = "📥 @savings_insta_bot orqali yuklab olindi"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("saving_full_bot")

ALL_USERS_PAGE_SIZE = 10
download_locks: dict[tuple[str, str, str | None], asyncio.Lock] = {}

stats = StatsStore(STATS_FILE)
audit_store = AuditStore(AUDIT_DB_FILE, AUDIT_RETENTION_DAYS)
media_files = MediaCache(MEDIA_CACHE_FILE)
state_store = StateStore(STATE_DB_FILE, STATE_TTL)
downloader = Downloader(
    TMP_ROOT,
    MAX_CONCURRENT_DOWNLOADS,
    COOKIES_FILE,
    POT_SERVER_HOME,
    NODE_EXECUTABLE,
    DOWNLOAD_TIMEOUT,
    TELEGRAM_UPLOAD_LIMIT_MB,
)


def lang_for(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "uz"
    return state_store.language(user.id)


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("O'zbekcha", callback_data="lang:uz")],
            [InlineKeyboardButton("Русский", callback_data="lang:ru")],
            [InlineKeyboardButton("English", callback_data="lang:en")],
        ]
    )


def quality_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("360p", callback_data=f"quality:{request_id}:360"),
                InlineKeyboardButton("720p", callback_data=f"quality:{request_id}:720"),
            ],
            [
                InlineKeyboardButton("1080p", callback_data=f"quality:{request_id}:1080"),
                InlineKeyboardButton("MP3", callback_data=f"quality:{request_id}:audio"),
            ],
        ]
    )


def music_keyboard(
    request_id: str, page: int, total_pages: int, count: int
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    for index in range(count):
        row.append(
            InlineKeyboardButton(
                str(index + 1), callback_data=f"music:pick:{request_id}:{page}:{index}"
            )
        )
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    nav = []
    if page > 1:
        nav.append(
            InlineKeyboardButton(
                "Oldingi", callback_data=f"music:page:{request_id}:{page - 1}"
            )
        )
    if page < total_pages:
        nav.append(
            InlineKeyboardButton(
                "Keyingi", callback_data=f"music:page:{request_id}:{page + 1}"
            )
        )
    if nav:
        rows.append(nav)

    return InlineKeyboardMarkup(rows)


def format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "--:--"
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def format_results(data: dict[str, Any]) -> str:
    lines = [
        f"{idx}. {song.title} ({format_duration(song.duration)})"
        for idx, song in enumerate(data["results"], 1)
    ]
    header = f"Topilgan qo'shiqlar: {data['page']}/{data['total_pages']}"
    return header + "\n\n" + "\n".join(lines)


def is_admin(user_id: int | None) -> bool:
    return bool(user_id and user_id == ADMIN_CHAT_ID)


def short_text(value: str, limit: int = 120) -> str:
    clean = " ".join((value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3] + "..."


def event_time(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%d.%m %H:%M:%S")


def admin_keyboard() -> InlineKeyboardMarkup:
    live_state = "ON" if audit_store.live_enabled() else "OFF"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Statistika", callback_data="admin:stats"),
                InlineKeyboardButton("Oxirgi hodisalar", callback_data="admin:events"),
            ],
            [
                InlineKeyboardButton("Foydalanuvchilar", callback_data="admin:users"),
                InlineKeyboardButton("Tizim holati", callback_data="admin:status"),
            ],
            [
                InlineKeyboardButton(
                    "Barcha foydalanuvchilar",
                    callback_data="admin:allusers:1",
                )
            ],
            [InlineKeyboardButton(f"Jonli log: {live_state}", callback_data="admin:live")],
        ]
    )


def admin_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Orqaga", callback_data="admin:home")]]
    )


def admin_home_text() -> str:
    data = audit_store.dashboard()
    return (
        "SUPER ADMIN PANEL\n\n"
        f"Foydalanuvchilar: {data['users']}\n"
        f"Kiruvchi hodisalar: {data['incoming']}\n"
        f"Bot javoblari: {data['outgoing']}\n"
        f"Bugungi hodisalar: {data['today_events']}\n\n"
        "User dialogini ko'rish: /history USER_ID"
    )


def admin_events_text() -> str:
    events = audit_store.recent_events(15)
    if not events:
        return "Hozircha audit hodisalari yo'q."

    lines = ["OXIRGI HODISALAR", ""]
    for event in events:
        direction = "IN" if event["direction"] == "in" else "OUT"
        username = f"@{event['username']}" if event.get("username") else "username yo'q"
        lines.append(
            f"#{event['id']} {direction} {event_time(event['created_at'])}\n"
            f"{username} | ID {event.get('user_id') or '-'} | {event['kind']}\n"
            f"{short_text(event['content'], 100)}"
        )
    return "\n\n".join(lines)[:4000]


def admin_users_view() -> tuple[str, InlineKeyboardMarkup]:
    users = audit_store.recent_users(10)
    if not users:
        return "Hozircha foydalanuvchilar yo'q.", admin_back_keyboard()

    rows = []
    for user in users:
        username = f"@{user['username']}" if user.get("username") else user["full_name"]
        label = f"{short_text(username, 22)} | {user['user_id']}"
        rows.append(
            [InlineKeyboardButton(label, callback_data=f"admin:user:{user['user_id']}")]
        )
    rows.append([InlineKeyboardButton("Orqaga", callback_data="admin:home")])
    return "FOYDALANUVCHILAR\n\nDialogini ko'rish uchun userni tanlang.", InlineKeyboardMarkup(rows)


def admin_all_users_view(page: int) -> tuple[str, InlineKeyboardMarkup]:
    total_users = audit_store.user_count()
    if not total_users:
        return "Hozircha foydalanuvchilar yo'q.", admin_back_keyboard()

    total_pages = max(1, (total_users + ALL_USERS_PAGE_SIZE - 1) // ALL_USERS_PAGE_SIZE)
    page = min(max(1, page), total_pages)
    offset = (page - 1) * ALL_USERS_PAGE_SIZE
    users = audit_store.users_page(offset, ALL_USERS_PAGE_SIZE)

    rows = []
    for user in users:
        username = f"@{user['username']}" if user.get("username") else user["full_name"]
        label = f"{short_text(username, 22)} | ID {user['user_id']}"
        rows.append(
            [InlineKeyboardButton(label, callback_data=f"admin:user:{user['user_id']}")]
        )

    navigation = []
    if page > 1:
        navigation.append(
            InlineKeyboardButton("Oldingi", callback_data=f"admin:allusers:{page - 1}")
        )
    if page < total_pages:
        navigation.append(
            InlineKeyboardButton("Keyingi", callback_data=f"admin:allusers:{page + 1}")
        )
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton("Orqaga", callback_data="admin:home")])

    content = (
        "BARCHA FOYDALANUVCHILAR\n\n"
        f"Jami: {total_users}\n"
        f"Sahifa: {page}/{total_pages}\n\n"
        "Dialogini ko'rish uchun userni tanlang."
    )
    return content, InlineKeyboardMarkup(rows)


def admin_user_history_text(user_id: int) -> str:
    user = audit_store.user(user_id)
    if not user:
        return f"User topilmadi: {user_id}"

    username = f"@{user['username']}" if user.get("username") else "username yo'q"
    lines = [
        "USER DIALOGI",
        "",
        f"Ism: {user['full_name']}",
        f"Username: {username}",
        f"ID: {user_id}",
        f"Xabarlar: {user['message_count']}",
        "",
    ]
    history = audit_store.user_history(user_id, 20)
    if not history:
        lines.append("Dialog tarixi bo'sh.")
    for event in history:
        speaker = "USER" if event["direction"] == "in" else "BOT"
        lines.append(
            f"{event_time(event['created_at'])} {speaker} [{event['kind']}]\n"
            f"{short_text(event['content'], 160)}"
        )
    return "\n\n".join(lines)[:4000]


def admin_status_text() -> str:
    return (
        "TIZIM HOLATI\n\n"
        "Bot: ishlayapti\n"
        f"Media kesh: {len(media_files.items)}\n"
        f"Parallel yuklashlar: {MAX_CONCURRENT_DOWNLOADS}\n"
        f"Kutilayotgan media: {len(download_locks)}\n"
        f"Upload limiti: {TELEGRAM_UPLOAD_LIMIT_MB} MB\n"
        f"Local Bot API: {'ON' if BOT_API_LOCAL_MODE else 'OFF'}\n"
        f"Jonli log: {'ON' if audit_store.live_enabled() else 'OFF'}\n"
        f"Audit DB: {AUDIT_DB_FILE.name}"
    )


async def send_live_audit(
    app: Application,
    event_id: int,
    user_id: int | None,
    direction: str,
    kind: str,
    content: str,
) -> None:
    if not ADMIN_CHAT_ID or not audit_store.live_enabled() or is_admin(user_id):
        return

    user = audit_store.user(user_id) if user_id else None
    full_name = user["full_name"] if user else "Unknown"
    username = f"@{user['username']}" if user and user.get("username") else "username yo'q"
    title = "USER -> BOT" if direction == "in" else "BOT -> USER"
    message = (
        f"{title} | #{event_id}\n"
        f"{full_name} | {username}\n"
        f"ID: {user_id or '-'} | Tur: {kind}\n\n"
        f"{short_text(content, 2000)}"
    )
    try:
        await app.bot.send_message(
            ADMIN_CHAT_ID,
            message,
            disable_web_page_preview=True,
        )
    except TelegramError:
        logger.warning("Could not send live audit event to admin", exc_info=True)


def record_outgoing(
    app: Application,
    user_id: int | None,
    chat_id: int,
    kind: str,
    content: str,
) -> None:
    event_id = audit_store.record_event(user_id, chat_id, "out", kind, content)
    app.create_task(send_live_audit(app, event_id, user_id, "out", kind, content))


def incoming_message_details(update: Update) -> tuple[str, str]:
    message = update.effective_message
    if not message:
        return "update", ""
    if message.text:
        kind = "command" if message.text.startswith("/") else "text"
        return kind, message.text
    if message.caption:
        return "media_caption", message.caption
    if message.photo:
        return "photo", "Photo"
    if message.video:
        return "video", message.video.file_name or "Video"
    if message.audio:
        return "audio", message.audio.file_name or "Audio"
    if message.document:
        return "document", message.document.file_name or "Document"
    if message.voice:
        return "voice", "Voice message"
    return "message", "Unsupported message"


async def audit_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    chat = update.effective_chat
    if not chat:
        return
    user = update.effective_user
    user_id = user.id if user else None
    if user:
        audit_store.touch_user(
            user.id,
            user.username,
            user.full_name,
            user.language_code,
            increment=True,
        )
    kind, content = incoming_message_details(update)
    event_id = audit_store.record_event(user_id, chat.id, "in", kind, content)
    context.application.create_task(
        send_live_audit(context.application, event_id, user_id, "in", kind, content)
    )


async def audit_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    user = query.from_user
    audit_store.touch_user(
        user.id,
        user.username,
        user.full_name,
        user.language_code,
        increment=True,
    )
    content = query.data or ""
    event_id = audit_store.record_event(
        user.id,
        query.message.chat_id,
        "in",
        "callback",
        content,
    )
    context.application.create_task(
        send_live_audit(context.application, event_id, user.id, "in", "callback", content)
    )


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user:
        stats.touch_user(update.effective_user.id)
    response = text(lang_for(update), "choose_lang")
    await update.message.reply_text(
        response,
        reply_markup=language_keyboard(),
    )
    record_outgoing(
        context.application,
        update.effective_user.id if update.effective_user else None,
        update.effective_chat.id,
        "text",
        response,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    response = text(lang_for(update), "help")
    await update.message.reply_text(response)
    record_outgoing(
        context.application,
        update.effective_user.id if update.effective_user else None,
        update.effective_chat.id,
        "text",
        response,
    )


async def lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    response = text(lang_for(update), "choose_lang")
    await update.message.reply_text(
        response,
        reply_markup=language_keyboard(),
    )
    record_outgoing(
        context.application,
        update.effective_user.id if update.effective_user else None,
        update.effective_chat.id,
        "text",
        response,
    )


async def lang_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    lang = query.data.split(":", 1)[1]
    state_store.set_language(query.from_user.id, lang)

    response = f"{text(lang, 'lang_saved')}\n\n{text(lang, 'start')}"
    await query.edit_message_text(response)
    record_outgoing(
        context.application,
        query.from_user.id,
        query.message.chat_id,
        "text",
        response,
    )


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text(text(lang_for(update), "admin_only"))
        if update.effective_user:
            record_outgoing(
                context.application,
                update.effective_user.id,
                update.effective_chat.id,
                "text",
                text(lang_for(update), "admin_only"),
            )
        return
    response = admin_home_text()
    await update.message.reply_text(response, reply_markup=admin_keyboard())
    record_outgoing(
        context.application,
        update.effective_user.id,
        update.effective_chat.id,
        "text",
        response,
    )


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text(text(lang_for(update), "admin_only"))
        return
    if not context.args or not context.args[0].isdigit():
        response = "Foydalanish: /history USER_ID"
        await update.message.reply_text(response)
        record_outgoing(
            context.application,
            update.effective_user.id,
            update.effective_chat.id,
            "text",
            response,
        )
        return
    response = admin_user_history_text(int(context.args[0]))
    await update.message.reply_text(
        response,
        reply_markup=admin_back_keyboard(),
    )
    record_outgoing(
        context.application,
        update.effective_user.id,
        update.effective_chat.id,
        "text",
        response,
    )


async def admin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text(text(lang_for(update), "admin_only"))
        return

    action = query.data.split(":", 1)[1]
    if action == "home":
        content, keyboard = admin_home_text(), admin_keyboard()
    elif action == "stats":
        content, keyboard = stats.report(), admin_back_keyboard()
    elif action == "events":
        content, keyboard = admin_events_text(), admin_back_keyboard()
    elif action == "users":
        content, keyboard = admin_users_view()
    elif action.startswith("allusers:"):
        page = int(action.rsplit(":", 1)[1])
        content, keyboard = admin_all_users_view(page)
    elif action == "status":
        content, keyboard = admin_status_text(), admin_back_keyboard()
    elif action == "live":
        enabled = audit_store.toggle_live()
        state = "yoqildi" if enabled else "o'chirildi"
        content, keyboard = f"Jonli audit {state}.\n\n{admin_home_text()}", admin_keyboard()
    elif action.startswith("user:"):
        user_id = int(action.split(":", 1)[1])
        content, keyboard = admin_user_history_text(user_id), admin_back_keyboard()
    else:
        content, keyboard = admin_home_text(), admin_keyboard()

    await query.edit_message_text(content, reply_markup=keyboard)
    record_outgoing(
        context.application,
        query.from_user.id,
        query.message.chat_id,
        "text",
        content,
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text or not update.effective_user:
        return

    uid = update.effective_user.id
    lang = lang_for(update)
    body = message.text.strip()
    stats.touch_user(uid)

    match = URL_RE.search(body)
    if match:
        url = match.group(0)
        try:
            downloader.validate_url(url)
        except ValueError:
            response = text(lang, "invalid_url")
            await message.reply_text(response)
            record_outgoing(context.application, uid, message.chat_id, "text", response)
            return
        request_id = state_store.create(uid, "download", {"url": url})
        response = text(lang, "choose_quality")
        await message.reply_text(response, reply_markup=quality_keyboard(request_id))
        record_outgoing(context.application, uid, message.chat_id, "text", response)
        return

    searching_text = text(lang, "searching")
    progress = await message.reply_text(searching_text)
    record_outgoing(context.application, uid, message.chat_id, "text", searching_text)
    try:
        data = await asyncio.to_thread(search_music, body, 1)
    except Exception:
        logger.exception("Music search failed")
        response = text(lang, "error")
        await progress.edit_text(response)
        record_outgoing(context.application, uid, message.chat_id, "text", response)
        return

    if not data["results"]:
        response = text(lang, "not_found")
        await progress.edit_text(response)
        record_outgoing(context.application, uid, message.chat_id, "text", response)
        return

    request_id = state_store.create(uid, "music", {"query": body})
    response = format_results(data)
    await progress.edit_text(
        response,
        reply_markup=music_keyboard(
            request_id, data["page"], data["total_pages"], len(data["results"])
        ),
    )
    record_outgoing(context.application, uid, message.chat_id, "text", response)


async def music_page_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    lang = state_store.language(uid)
    _, _, request_id, page_text = query.data.split(":", 3)
    page = int(page_text)
    request_state = state_store.get(request_id, uid, "music")
    search_text = request_state.get("query") if request_state else None

    if not search_text:
        response = text(lang, "old_list")
        await query.edit_message_text(response)
        record_outgoing(
            context.application, uid, query.message.chat_id, "text", response
        )
        return

    searching_text = text(lang, "searching")
    await query.edit_message_text(searching_text)
    record_outgoing(
        context.application, uid, query.message.chat_id, "text", searching_text
    )
    try:
        data = await asyncio.to_thread(search_music, search_text, page)
    except Exception:
        logger.exception("Music page failed")
        response = text(lang, "error")
        await query.edit_message_text(response)
        record_outgoing(
            context.application, uid, query.message.chat_id, "text", response
        )
        return

    response = format_results(data)
    await query.edit_message_text(
        response,
        reply_markup=music_keyboard(
            request_id, data["page"], data["total_pages"], len(data["results"])
        ),
    )
    record_outgoing(context.application, uid, query.message.chat_id, "text", response)


async def music_pick_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    lang = state_store.language(uid)
    _, _, request_id, page_text, index_text = query.data.split(":", 4)
    request_state = state_store.get(request_id, uid, "music")

    if not request_state or not request_state.get("query"):
        response = text(lang, "old_list")
        await query.edit_message_text(response)
        record_outgoing(
            context.application, uid, query.message.chat_id, "text", response
        )
        return

    page = int(page_text)
    index = int(index_text)
    try:
        data = await asyncio.to_thread(search_music, request_state["query"], page)
    except Exception:
        logger.exception("Music selection refresh failed")
        response = text(lang, "error")
        await query.edit_message_text(response)
        record_outgoing(context.application, uid, query.message.chat_id, "text", response)
        return
    songs = data["results"]
    if index < 0 or index >= len(songs):
        response = text(lang, "bad_choice")
        await query.edit_message_text(response)
        record_outgoing(
            context.application, uid, query.message.chat_id, "text", response
        )
        return

    context.application.create_task(
        send_download(
            context.application,
            uid,
            query.message.chat_id,
            songs[index].url,
            "audio",
            None,
        )
    )
    response = text(lang, "downloading")
    await query.edit_message_text(response)
    record_outgoing(context.application, uid, query.message.chat_id, "text", response)


async def quality_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    lang = state_store.language(uid)
    _, request_id, choice = query.data.split(":", 2)
    request_state = state_store.get(request_id, uid, "download")
    url = request_state.get("url") if request_state else None

    if not url:
        response = text(lang, "no_url")
        await query.edit_message_text(response)
        record_outgoing(
            context.application, uid, query.message.chat_id, "text", response
        )
        return

    mode = "audio" if choice == "audio" else "video"
    quality = None if mode == "audio" else choice

    context.application.create_task(
        send_download(context.application, uid, query.message.chat_id, url, mode, quality)
    )
    response = text(lang, "downloading")
    await query.edit_message_text(response)
    record_outgoing(context.application, uid, query.message.chat_id, "text", response)


async def send_download(
    app: Application,
    uid: int,
    chat_id: int,
    url: str,
    mode: str,
    quality: str | None,
) -> None:
    key = (downloader.canonical_url(url), mode, quality)
    lock = download_locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            await _send_download(app, uid, chat_id, url, mode, quality)
    finally:
        if not lock.locked():
            download_locks.pop(key, None)


async def _send_download(
    app: Application,
    uid: int,
    chat_id: int,
    url: str,
    mode: str,
    quality: str | None,
) -> None:
    lang = state_store.language(uid)
    file_path = None
    started_at = time.monotonic()
    cache_url = downloader.canonical_url(url)

    try:
        cached = media_files.get(cache_url, mode, quality)
        if cached:
            try:
                await send_cached_media(app, chat_id, cached)
                stats.count_success(mode)
                record_outgoing(
                    app,
                    uid,
                    chat_id,
                    cached["send_as"],
                    f"{DOWNLOAD_CAPTION}\nSource: {cache_url}",
                )
                logger.info("Media cache hit; sent in %.2fs", time.monotonic() - started_at)
                return
            except BadRequest:
                media_files.delete(cache_url, mode, quality)

        if mode == "video" and downloader.supports_direct_fetch(url):
            remote_media = None
            try:
                remote_media = await downloader.resolve_remote_video(url, quality)
            except Exception:
                logger.exception("Remote video URL resolution failed")

            if remote_media and (
                remote_media.filesize is None
                or remote_media.filesize <= 20 * 1024 * 1024
                or BOT_API_LOCAL_MODE
            ):
                try:
                    sent = await app.bot.send_video(
                        chat_id,
                        video=remote_media.url,
                        caption=DOWNLOAD_CAPTION,
                        supports_streaming=True,
                    )
                except TelegramError:
                    logger.info("Telegram remote fetch failed; using local upload")
                else:
                    if sent.video:
                        media_files.put(
                            cache_url,
                            mode,
                            quality,
                            sent.video.file_id,
                            "video",
                        )
                    stats.count_success(mode)
                    record_outgoing(
                        app,
                        uid,
                        chat_id,
                        "video",
                        f"{DOWNLOAD_CAPTION}\nSource: {cache_url}",
                    )
                    logger.info(
                        "Remote media sent in %.2fs",
                        time.monotonic() - started_at,
                    )
                    return

        file_path = await downloader.download(url, mode, quality)
        sent_kind = mode
        if mode == "audio":
            sent = await app.bot.send_audio(
                chat_id,
                audio=file_path,
                caption=DOWNLOAD_CAPTION,
            )
            if sent.audio:
                media_files.put(cache_url, mode, quality, sent.audio.file_id, "audio")
            sent_kind = "audio"
        else:
            try:
                sent = await app.bot.send_video(
                    chat_id,
                    video=file_path,
                    caption=DOWNLOAD_CAPTION,
                    supports_streaming=True,
                )
                if sent.video:
                    media_files.put(cache_url, mode, quality, sent.video.file_id, "video")
                sent_kind = "video"
            except BadRequest:
                sent = await app.bot.send_document(
                    chat_id,
                    document=file_path,
                    caption=DOWNLOAD_CAPTION,
                )
                if sent.document:
                    media_files.put(cache_url, mode, quality, sent.document.file_id, "document")
                sent_kind = "document"

        stats.count_success(mode)
        record_outgoing(
            app,
            uid,
            chat_id,
            sent_kind,
            f"{DOWNLOAD_CAPTION}\nSource: {cache_url}",
        )
        logger.info("Fresh media sent in %.2fs", time.monotonic() - started_at)
    except AuthenticationRequiredError:
        logger.warning("YouTube requires authentication for the selected media")
        response = text(lang, "youtube_blocked")
        await app.bot.send_message(chat_id, response)
        record_outgoing(app, uid, chat_id, "text", response)
    except MediaUnavailableError:
        logger.info("Selected media is unavailable")
        response = text(lang, "unavailable")
        await app.bot.send_message(chat_id, response)
        record_outgoing(app, uid, chat_id, "text", response)
    except MediaTooLargeError:
        logger.info("Selected media exceeds Telegram upload limit")
        response = text(lang, "too_large")
        await app.bot.send_message(chat_id, response)
        record_outgoing(app, uid, chat_id, "text", response)
    except DownloadTimeoutError:
        logger.info("Selected media exceeded the download deadline")
        response = text(lang, "timeout")
        await app.bot.send_message(chat_id, response)
        record_outgoing(app, uid, chat_id, "text", response)
    except Exception:
        logger.exception("Download failed")
        response = text(lang, "error")
        await app.bot.send_message(chat_id, response)
        record_outgoing(app, uid, chat_id, "text", response)
    finally:
        if file_path:
            downloader.cleanup(file_path)


async def send_cached_media(app: Application, chat_id: int, cached: dict) -> None:
    file_id = cached["file_id"]
    send_as = cached["send_as"]
    if send_as == "audio":
        await app.bot.send_audio(chat_id, audio=file_id, caption=DOWNLOAD_CAPTION)
    elif send_as == "video":
        await app.bot.send_video(
            chat_id,
            video=file_id,
            caption=DOWNLOAD_CAPTION,
            supports_streaming=True,
        )
    else:
        await app.bot.send_document(chat_id, document=file_id, caption=DOWNLOAD_CAPTION)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    if error:
        logger.error(
            "Unhandled Telegram update error",
            exc_info=(type(error), error, error.__traceback__),
        )
    else:
        logger.error("Unhandled Telegram update error")


def build_app() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")
    if BOT_API_LOCAL_MODE and not (BOT_API_BASE_URL and BOT_API_BASE_FILE_URL):
        raise RuntimeError(
            "BOT_API_LOCAL_MODE requires BOT_API_BASE_URL and BOT_API_BASE_FILE_URL"
        )

    request = HTTPXRequest(
        connection_pool_size=max(4, MAX_CONCURRENT_DOWNLOADS + 2),
        read_timeout=DOWNLOAD_TIMEOUT,
        write_timeout=DOWNLOAD_TIMEOUT,
        media_write_timeout=DOWNLOAD_TIMEOUT,
        pool_timeout=30,
    )
    builder = ApplicationBuilder().token(BOT_TOKEN).request(request)
    if BOT_API_BASE_URL:
        builder = builder.base_url(BOT_API_BASE_URL)
    if BOT_API_BASE_FILE_URL:
        builder = builder.base_file_url(BOT_API_BASE_FILE_URL)
    if BOT_API_LOCAL_MODE:
        builder = builder.local_mode(True)
    app = builder.build()

    app.add_handler(MessageHandler(filters.ALL, audit_message_handler), group=-1)
    app.add_handler(CallbackQueryHandler(audit_callback_handler), group=-1)
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("lang", lang_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("panel", admin_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(
        CallbackQueryHandler(
            admin_cb,
            pattern=r"^admin:(?:home|stats|events|users|status|live|user:\d+|allusers:\d+)$",
        )
    )
    app.add_handler(CallbackQueryHandler(lang_cb, pattern=r"^lang:(uz|ru|en)$"))
    app.add_handler(
        CallbackQueryHandler(
            quality_cb, pattern=r"^quality:[A-Za-z0-9_-]+:(audio|360|720|1080)$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            music_page_cb, pattern=r"^music:page:[A-Za-z0-9_-]+:\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            music_pick_cb, pattern=r"^music:pick:[A-Za-z0-9_-]+:\d+:\d+$"
        )
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_error_handler(error_handler)
    return app


def main() -> None:
    logger.info("Saving full bot started")
    ensure_pot_server(POT_SERVER_HOME, NODE_EXECUTABLE)
    build_app().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
    STATE_DB_FILE,
    STATE_TTL,
    TELEGRAM_UPLOAD_LIMIT_MB,
