TEXTS = {
    "uz": {
        "start": (
            "Salom! Menga YouTube/TikTok/Instagram link yuboring yoki "
            "qo'shiq nomini yozing."
        ),
        "choose_lang": "Tilni tanlang:",
        "lang_saved": "Til saqlandi.",
        "choose_quality": "Formatni tanlang:",
        "searching": "Qidiryapman...",
        "not_found": "Hech narsa topilmadi.",
        "downloading": "Yuklanmoqda, biroz kuting...",
        "ready_audio": "MP3 tayyor.",
        "ready_video": "Video tayyor.",
        "error": "Xatolik yuz berdi. Keyinroq qayta urinib ko'ring.",
        "youtube_blocked": "YouTube server so'rovini tasdiqlashni talab qildi. Boshqa video yoki keyinroq qayta urinib ko'ring.",
        "old_list": "Ro'yxat eskirgan. Qayta qidiring.",
        "bad_choice": "Noto'g'ri tanlov.",
        "no_url": "Avval link yuboring.",
        "invalid_url": "Faqat YouTube, TikTok yoki Instagram havolasini yuboring.",
        "too_large": "Video Telegram limitidan katta. Pastroq sifatni tanlang.",
        "timeout": "Yuklash juda uzoq davom etdi. Pastroq sifatni tanlab qayta urining.",
        "unavailable": "Bu video mavjud emas, yopiq yoki hududingizda cheklangan.",
        "admin_only": "Bu buyruq faqat admin uchun.",
        "help": (
            "Link yuborsangiz video yoki MP3 qilib yuklab beraman.\n"
            "Qo'shiq nomini yozsangiz YouTube'dan qidirib, tanlanganini MP3 qilaman.\n\n"
            "Buyruqlar:\n"
            "/start - boshlash\n"
            "/lang - til tanlash\n"
            "/admin - statistika"
        ),
    },
    "ru": {
        "start": (
            "Привет! Отправьте ссылку YouTube/TikTok/Instagram или "
            "название песни."
        ),
        "choose_lang": "Выберите язык:",
        "lang_saved": "Язык сохранен.",
        "choose_quality": "Выберите формат:",
        "searching": "Ищу...",
        "not_found": "Ничего не найдено.",
        "downloading": "Скачиваю, подождите...",
        "ready_audio": "MP3 готов.",
        "ready_video": "Видео готово.",
        "error": "Произошла ошибка. Попробуйте позже.",
        "youtube_blocked": "YouTube запросил дополнительную проверку сервера. Попробуйте другое видео или повторите позже.",
        "old_list": "Список устарел. Повторите поиск.",
        "bad_choice": "Неверный выбор.",
        "no_url": "Сначала отправьте ссылку.",
        "invalid_url": "Отправьте ссылку только с YouTube, TikTok или Instagram.",
        "too_large": "Видео превышает лимит Telegram. Выберите качество ниже.",
        "timeout": "Загрузка заняла слишком много времени. Выберите качество ниже.",
        "unavailable": "Видео недоступно, закрыто или ограничено в вашем регионе.",
        "admin_only": "Эта команда только для админа.",
        "help": (
            "Отправьте ссылку, и я скачаю видео или MP3.\n"
            "Напишите название песни, и я найду ее на YouTube.\n\n"
            "Команды:\n"
            "/start - старт\n"
            "/lang - выбрать язык\n"
            "/admin - статистика"
        ),
    },
    "en": {
        "start": (
            "Hi! Send a YouTube/TikTok/Instagram link or type a song name."
        ),
        "choose_lang": "Choose language:",
        "lang_saved": "Language saved.",
        "choose_quality": "Choose format:",
        "searching": "Searching...",
        "not_found": "Nothing found.",
        "downloading": "Downloading, please wait...",
        "ready_audio": "MP3 is ready.",
        "ready_video": "Video is ready.",
        "error": "Something went wrong. Please try again later.",
        "youtube_blocked": "YouTube requested additional server verification. Try another video or retry later.",
        "old_list": "This list expired. Search again.",
        "bad_choice": "Bad choice.",
        "no_url": "Send a link first.",
        "invalid_url": "Send a YouTube, TikTok, or Instagram link only.",
        "too_large": "The video exceeds Telegram's limit. Choose a lower quality.",
        "timeout": "The download took too long. Choose a lower quality and retry.",
        "unavailable": "This video is unavailable, private, or region-restricted.",
        "admin_only": "This command is admin only.",
        "help": (
            "Send a link and I will download video or MP3.\n"
            "Type a song name and I will search YouTube.\n\n"
            "Commands:\n"
            "/start - start\n"
            "/lang - choose language\n"
            "/admin - stats"
        ),
    },
}


def text(lang: str, key: str) -> str:
    return TEXTS.get(lang, TEXTS["uz"]).get(key, TEXTS["uz"][key])
