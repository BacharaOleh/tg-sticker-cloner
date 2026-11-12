import asyncio
import html
import json
import logging
import os
import re
import secrets
import sys
import time
from typing import Optional

# Принудительно настраиваем UTF-8 вывод для консоли Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputSticker,
    Message,
)

from config import BOT_TOKEN, validate_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("StickerCloner")

validate_config()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Защита от параллельных дублирующих запросов от одного пользователя
active_users: set[int] = set()

# Временное хранилище пака, если пользователь отправил стикер до выбора языка
pending_packs: dict[int, str] = {}

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LANGS_FILE = os.path.join(DATA_DIR, "user_langs.json")

STICKER_URL_REGEX = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/addstickers/([a-zA-Z0-9_]+)",
    re.IGNORECASE
)

TEXTS = {
    "ru": {
        "welcome": (
            "👋 <b>Привет, {name}!</b>\n\n"
            "Отправь мне <b>любой стикер</b> или ссылку на пак — я мгновенно создам твою личную копию!\n\n"
            "<i>Сменить язык: /lang</i>"
        ),
        "help": (
            "💡 <b>Как пользоваться:</b>\n\n"
            "1. Отправь любой стикер из нужного пака.\n"
            "2. Или отправь ссылку вида <code>t.me/addstickers/...</code>\n"
            "3. Бот мгновенно создаст пак от твоего имени!\n\n"
            "Сменить язык: /lang"
        ),
        "already_cloning": "⏳ У вас уже выполняется клонирование. Пожалуйста, подождите!",
        "cloning_start": "⏳ <b>Клонирую стикерпак...</b>",
        "not_found": "❌ Стикерпак не найден. Проверьте ссылку.",
        "empty_pack": "❌ Этот стикерпак пуст.",
        "copying_progress": "⏳ <b>Копирую стикеры:</b> {added}/{total}...",
        "copying_part_progress": "⏳ <b>Копирую часть {part}/{total_parts}:</b> {added}/{total}...",
        "add_btn": "➕ Добавить пак",
        "add_part_btn": "➕ Часть {part} ({count} шт)",
        "ready_single": (
            "🎉 <b>Стикерпак готов!</b>\n\n"
            "🏷 <b>Название:</b> {title}\n"
            "👤 <b>Владелец:</b> Вы\n"
            "📊 <b>Стикеров:</b> {count}\n\n"
            "🔗 <b>Ссылка:</b> {url}"
        ),
        "ready_multi": (
            "🎉 <b>Стикерпак успешно скопирован!</b>\n\n"
            "ℹ️ В наборе более 120 стикеров, поэтому создано {total_parts} части:\n\n"
            "{parts_text}\n\n"
            "👤 <b>Владелец:</b> Вы"
        ),
        "part_line": "• <b>Часть {part}</b> ({count} шт): {url}",
        "copy_suffix": "Копия",
        "part_label": "Часть",
        "standalone_sticker": "❌ Этот стикер не привязан к набору.",
        "invalid_input": "Отправьте мне стикер или ссылку на пак вида:\n<code>https://t.me/addstickers/name</code>",
        "err_direct": "❌ Ошибка: напишите боту в личные сообщения.",
        "err_tg": "❌ Ошибка Telegram: <code>{error}</code>",
        "err_generic": "❌ Ошибка: {error}",
    },
    "en": {
        "welcome": (
            "👋 <b>Hello, {name}!</b>\n\n"
            "Send me <b>any sticker</b> or pack link — I will instantly clone it as your own!\n\n"
            "<i>Change language: /lang</i>"
        ),
        "help": (
            "💡 <b>How to use:</b>\n\n"
            "1. Send any sticker from the set.\n"
            "2. Or send a link like <code>t.me/addstickers/...</code>\n"
            "3. The bot will instantly clone it under your ownership!\n\n"
            "Change language: /lang"
        ),
        "already_cloning": "⏳ Cloning is already in progress. Please wait!",
        "cloning_start": "⏳ <b>Cloning sticker pack...</b>",
        "not_found": "❌ Sticker pack not found. Check the link.",
        "empty_pack": "❌ This sticker pack is empty.",
        "copying_progress": "⏳ <b>Copying stickers:</b> {added}/{total}...",
        "copying_part_progress": "⏳ <b>Copying part {part}/{total_parts}:</b> {added}/{total}...",
        "add_btn": "➕ Add Pack",
        "add_part_btn": "➕ Part {part} ({count})",
        "ready_single": (
            "🎉 <b>Sticker pack is ready!</b>\n\n"
            "🏷 <b>Title:</b> {title}\n"
            "👤 <b>Owner:</b> You\n"
            "📊 <b>Stickers:</b> {count}\n\n"
            "🔗 <b>Link:</b> {url}"
        ),
        "ready_multi": (
            "🎉 <b>Sticker pack is ready!</b>\n\n"
            "ℹ️ The pack has over 120 stickers, so {total_parts} parts were created:\n\n"
            "{parts_text}\n\n"
            "👤 <b>Owner:</b> You"
        ),
        "part_line": "• <b>Part {part}</b> ({count}): {url}",
        "copy_suffix": "Copy",
        "part_label": "Part",
        "standalone_sticker": "❌ This sticker does not belong to any pack.",
        "invalid_input": "Send me a sticker or pack link like:\n<code>https://t.me/addstickers/name</code>",
        "err_direct": "❌ Error: please message the bot directly.",
        "err_tg": "❌ Telegram error: <code>{error}</code>",
        "err_generic": "❌ Error: {error}",
    },
}


def load_user_langs() -> dict[int, str]:
    """Загружает сохраненные языки пользователей с диска."""
    try:
        if os.path.exists(LANGS_FILE):
            with open(LANGS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                return {int(k): v for k, v in raw.items() if v in ("ru", "en")}
    except Exception as e:
        logger.warning(f"Не удалось загрузить user_langs.json: {e}")
    return {}


def save_user_langs(langs: dict[int, str]) -> None:
    """Сохраняет языки пользователей на диск."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LANGS_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in langs.items()}, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Не удалось сохранить user_langs.json: {e}")


user_langs: dict[int, str] = load_user_langs()


def t(lang: str, key: str, **kwargs) -> str:
    """Возвращает локализованную строку."""
    pack = TEXTS.get(lang, TEXTS["en"])
    template = pack.get(key, TEXTS["en"].get(key, key))
    return template.format(**kwargs) if kwargs else template


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
            ]
        ]
    )


async def send_language_prompt(message: Message) -> None:
    await message.reply(
        "🌐 <b>Выберите язык / Choose your language:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=language_keyboard(),
    )


def generate_pack_name(user_id: int, bot_username: str, part: int = 1) -> str:
    """
    Генерирует уникальный slug для URL (до 64 символов, заканчивается на _by_<bot_username>).
    """
    suffix = f"_by_{bot_username}"
    short_id = secrets.token_hex(2)
    timestamp = hex(int(time.time()))[2:]
    prefix = f"s{user_id}_p{part}_{timestamp}_{short_id}"

    max_prefix_len = 64 - len(suffix)
    if len(prefix) > max_prefix_len:
        prefix = prefix[:max_prefix_len]

    return f"{prefix}{suffix}"


async def safe_api_call(coroutine_func, *args, max_retries: int = 5, **kwargs):
    """
    Автоматическое ожидание и повтор при FloodWait (TelegramRetryAfter).
    """
    for attempt in range(max_retries):
        try:
            return await coroutine_func(*args, **kwargs)
        except TelegramRetryAfter as e:
            wait_time = e.retry_after + 1
            logger.warning(f"Telegram FloodWait: спим {wait_time} сек (попытка {attempt + 1}/{max_retries})")
            await asyncio.sleep(wait_time)
        except Exception as e:
            raise e
    raise RuntimeError("Превышено максимальное число повторов API")


async def clone_sticker_set(target_set_name: str, reply_target: Message, user_id: int, lang: str):
    """
    Клонирование стикерпака. Вмещает до 120 стикеров в один пак.
    Если стикеров больше 120 — разбивает на части (Part 1, Part 2).
    """
    if user_id in active_users:
        await reply_target.reply(t(lang, "already_cloning"))
        return

    active_users.add(user_id)
    status_msg = await reply_target.reply(
        t(lang, "cloning_start"),
        parse_mode=ParseMode.HTML
    )

    try:
        # 1. Получаем исходный стикерпак
        try:
            original_set = await bot.get_sticker_set(name=target_set_name)
        except TelegramBadRequest as e:
            logger.warning(f"Стикерпак не найден: {target_set_name} ({e})")
            await status_msg.edit_text(t(lang, "not_found"), parse_mode=ParseMode.HTML)
            return

        total_stickers = len(original_set.stickers)
        if total_stickers == 0:
            await status_msg.edit_text(t(lang, "empty_pack"))
            return

        # 2. Определяем формат для Telegram API (пользователю не показываем)
        first_st = original_set.stickers[0] if original_set.stickers else None
        is_anim = bool(original_set.is_animated or (first_st and first_st.is_animated))
        is_vid = bool(original_set.is_video or (first_st and first_st.is_video))

        if is_anim:
            sticker_format = "animated"
        elif is_vid:
            sticker_format = "video"
        else:
            sticker_format = "static"

        max_stickers_per_pack = 120
        chunks = [
            original_set.stickers[i:i + max_stickers_per_pack]
            for i in range(0, total_stickers, max_stickers_per_pack)
        ]
        total_parts = len(chunks)

        bot_info = await bot.get_me()
        created_packs = []

        logger.info(
            f"Начало копирования: {target_set_name} ({total_stickers} шт, формат: {sticker_format}). "
            f"Частей: {total_parts}"
        )

        # 3. Создаем стикерпак (или части)
        for part_idx, part_stickers in enumerate(chunks, start=1):
            if total_parts > 1:
                title = f"{original_set.title} ({t(lang, 'part_label')} {part_idx})"[:64]
            else:
                title = f"{original_set.title} ({t(lang, 'copy_suffix')})"[:64]

            new_pack_name = generate_pack_name(user_id, bot_info.username, part=part_idx)

            first_batch_data = part_stickers[:50]
            remaining_batch_data = part_stickers[50:]

            first_batch = [
                InputSticker(
                    sticker=s.file_id,
                    format=sticker_format,
                    emoji_list=[s.emoji] if s.emoji else ["😀"]
                )
                for s in first_batch_data
            ]

            await safe_api_call(
                bot.create_new_sticker_set,
                user_id=user_id,
                name=new_pack_name,
                title=title,
                stickers=first_batch,
                sticker_format=sticker_format
            )

            added_count = len(first_batch)

            if remaining_batch_data:
                last_edit_time = time.time()
                for s in remaining_batch_data:
                    input_sticker = InputSticker(
                        sticker=s.file_id,
                        format=sticker_format,
                        emoji_list=[s.emoji] if s.emoji else ["😀"]
                    )
                    try:
                        await safe_api_call(
                            bot.add_sticker_to_set,
                            user_id=user_id,
                            name=new_pack_name,
                            sticker=input_sticker
                        )
                        added_count += 1

                        now = time.time()
                        if now - last_edit_time > 2.0 or added_count == len(part_stickers):
                            try:
                                if total_parts > 1:
                                    prog_text = t(
                                        lang, "copying_part_progress",
                                        part=part_idx, total_parts=total_parts,
                                        added=added_count, total=len(part_stickers)
                                    )
                                else:
                                    prog_text = t(
                                        lang, "copying_progress",
                                        added=added_count, total=len(part_stickers)
                                    )
                                await status_msg.edit_text(prog_text, parse_mode=ParseMode.HTML)
                                last_edit_time = now
                            except Exception:
                                pass

                        await asyncio.sleep(0.08)
                    except Exception as e:
                        logger.warning(f"Ошибка при добавлении стикера {s.file_id}: {e}")
                        continue

            pack_url = f"https://t.me/addstickers/{new_pack_name}"
            created_packs.append({
                "part": part_idx,
                "title": title,
                "count": added_count,
                "url": pack_url
            })

            if part_idx < total_parts:
                await asyncio.sleep(1.0)

        # 4. Финальное сообщение (без строки о типе стикеров)
        if total_parts == 1:
            pack = created_packs[0]
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=t(lang, "add_btn"), url=pack["url"])]
                ]
            )
            await status_msg.edit_text(
                t(
                    lang, "ready_single",
                    title=html.escape(pack["title"]),
                    count=pack["count"],
                    url=pack["url"]
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        else:
            keyboard_buttons = [
                [
                    InlineKeyboardButton(
                        text=t(lang, "add_part_btn", part=p["part"], count=p["count"]),
                        url=p["url"]
                    )
                ]
                for p in created_packs
            ]
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            parts_text = "\n".join([
                t(lang, "part_line", part=p["part"], count=p["count"], url=p["url"])
                for p in created_packs
            ])

            await status_msg.edit_text(
                t(lang, "ready_multi", total_parts=total_parts, parts_text=parts_text),
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )

        logger.info(f"Успешно обработан: {target_set_name} -> {len(created_packs)} частей.")

    except TelegramBadRequest as e:
        logger.error(f"TelegramBadRequest: {e}", exc_info=True)
        error_text = html.escape(str(e))
        if "PEER_ID_INVALID" in error_text or "USER_IS_BLOCKED" in error_text:
            msg = t(lang, "err_direct")
        else:
            msg = t(lang, "err_tg", error=error_text)
        await status_msg.edit_text(msg, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.exception("Ошибка при клонировании")
        await status_msg.edit_text(t(lang, "err_generic", error=html.escape(str(e))), parse_mode=ParseMode.HTML)

    finally:
        active_users.discard(user_id)


@dp.message(CommandStart())
async def handle_start(message: Message):
    # Всегда сначала показываем выбор языка
    await send_language_prompt(message)


@dp.message(Command("lang", "language"))
async def handle_lang_cmd(message: Message):
    await send_language_prompt(message)


@dp.callback_query(F.data.startswith("lang:"))
async def handle_lang_choice(callback: CallbackQuery):
    lang = callback.data.split(":", 1)[1]
    if lang not in ("ru", "en"):
        lang = "ru"

    user_id = callback.from_user.id
    user_langs[user_id] = lang
    save_user_langs(user_langs)

    await callback.answer()
    first_name = html.escape(callback.from_user.first_name or ("друг" if lang == "ru" else "friend"))

    await callback.message.edit_text(
        t(lang, "welcome", name=first_name),
        parse_mode=ParseMode.HTML
    )

    # Если пользователь прислал стикер/ссылку до выбора языка — запускаем клонирование сразу
    pending_set = pending_packs.pop(user_id, None)
    if pending_set:
        await clone_sticker_set(pending_set, callback.message, user_id, lang)


@dp.message(Command("help"))
async def handle_help(message: Message):
    user_id = message.from_user.id
    lang = user_langs.get(user_id)
    if not lang:
        await send_language_prompt(message)
        return
    await message.reply(t(lang, "help"), parse_mode=ParseMode.HTML)


async def process_pack_request(set_name: str, message: Message):
    user_id = message.from_user.id
    lang = user_langs.get(user_id)
    if not lang:
        pending_packs[user_id] = set_name
        await send_language_prompt(message)
        return
    await clone_sticker_set(set_name, message, user_id, lang)


@dp.message(F.sticker)
async def handle_sticker(message: Message):
    user_id = message.from_user.id
    lang = user_langs.get(user_id, "ru")
    sticker = message.sticker
    if not sticker.set_name:
        await message.reply(t(lang, "standalone_sticker"))
        return

    await process_pack_request(sticker.set_name, message)


@dp.message(F.text)
async def handle_text(message: Message):
    text = message.text.strip()
    match = STICKER_URL_REGEX.search(text)
    if match:
        await process_pack_request(match.group(1), message)
        return

    if re.match(r"^[a-zA-Z0-9_]{3,64}$", text) and not text.startswith("/"):
        await process_pack_request(text, message)
        return

    user_id = message.from_user.id
    lang = user_langs.get(user_id)
    if not lang:
        await send_language_prompt(message)
        return
    await message.reply(t(lang, "invalid_input"), parse_mode=ParseMode.HTML)


async def main():
    bot_info = await bot.get_me()
    logger.info(f"Бот запущен: @{bot_info.username} (ID: {bot_info.id})")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
