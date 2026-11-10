import asyncio
import html
import logging
import re
import secrets
import sys
import time

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

STICKER_URL_REGEX = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/addstickers/([a-zA-Z0-9_]+)",
    re.IGNORECASE
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


async def clone_sticker_set(target_set_name: str, message: Message):
    """
    Клонирование стикерпака. Вмещает до 120 стикеров в один пак.
    Если стикеров больше 120 — разбивает на части (Part 1, Part 2).
    """
    user_id = message.from_user.id
    if user_id in active_users:
        await message.reply("⏳ У вас уже выполняется клонирование. Пожалуйста, подождите!")
        return

    active_users.add(user_id)
    status_msg = await message.reply(
        "⏳ <b>Клонирую стикерпак... / Cloning sticker pack...</b>",
        parse_mode=ParseMode.HTML
    )

    try:
        # 1. Получаем исходный стикерпак
        try:
            original_set = await bot.get_sticker_set(name=target_set_name)
        except TelegramBadRequest as e:
            logger.warning(f"Стикерпак не найден: {target_set_name} ({e})")
            await status_msg.edit_text(
                "❌ Стикерпак не найден / Sticker pack not found.\n"
                "Проверьте ссылку / Check the link.",
                parse_mode=ParseMode.HTML
            )
            return

        total_stickers = len(original_set.stickers)
        if total_stickers == 0:
            await status_msg.edit_text("❌ Этот стикерпак пуст / This sticker pack is empty.")
            return

        # 2. Надежное определение формата (проверяем и сет, и отдельные стикеры)
        first_st = original_set.stickers[0] if original_set.stickers else None
        is_anim = bool(original_set.is_animated or (first_st and first_st.is_animated))
        is_vid = bool(original_set.is_video or (first_st and first_st.is_video))

        if is_anim:
            sticker_format = "animated"
            type_name = "анимированный"
        elif is_vid:
            sticker_format = "video"
            type_name = "видео"
        else:
            sticker_format = "static"
            type_name = "статичный"

        # Лимит Telegram на один набор любого типа — 120 стикеров
        max_stickers_per_pack = 120

        # Разбиваем на части, только если стикеров действительно больше 120
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
                title = f"{original_set.title} (Part {part_idx})"[:64]
            else:
                title = f"{original_set.title} (Copy)"[:64]

            new_pack_name = generate_pack_name(user_id, bot_info.username, part=part_idx)

            # Первые до 50 стикеров передаются разом в create_new_sticker_set
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

            # Создаем набор
            await safe_api_call(
                bot.create_new_sticker_set,
                user_id=user_id,
                name=new_pack_name,
                title=title,
                stickers=first_batch,
                sticker_format=sticker_format
            )

            added_count = len(first_batch)

            # Если в наборе больше 50 стикеров (до 120), догружаем остальные
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
                                    prog_text = f"⏳ <b>Копирую часть {part_idx}/{total_parts}:</b> {added_count}/{len(part_stickers)}..."
                                else:
                                    prog_text = f"⏳ <b>Копирую стикеры / Copying:</b> {added_count}/{len(part_stickers)}..."
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

        # 4. Финальное сообщение
        if total_parts == 1:
            pack = created_packs[0]
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Добавить пак / Add Pack", url=pack["url"])]
                ]
            )
            safe_title = html.escape(pack["title"])
            await status_msg.edit_text(
                f"🎉 <b>Стикерпак готов! / Sticker pack is ready!</b>\n\n"
                f"🏷 <b>Название / Title:</b> {safe_title}\n"
                f"👤 <b>Владелец / Owner:</b> Вы / You\n"
                f"📊 <b>Стикеров / Stickers:</b> {pack['count']}\n"
                f"🎨 <b>Тип / Type:</b> {type_name}\n\n"
                f"🔗 <b>Ссылка / Link:</b> {pack['url']}",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        else:
            keyboard_buttons = [
                [InlineKeyboardButton(text=f"➕ Часть {p['part']} / Part {p['part']} ({p['count']} шт)", url=p["url"])]
                for p in created_packs
            ]
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            parts_text = "\n".join([
                f"• <b>Часть {p['part']} / Part {p['part']}</b> ({p['count']} шт): {p['url']}"
                for p in created_packs
            ])

            await status_msg.edit_text(
                f"🎉 <b>Стикерпак успешно скопирован! / Ready!</b>\n\n"
                f"ℹ️ В наборе более 120 стикеров, поэтому создано {total_parts} части:\n\n"
                f"{parts_text}\n\n"
                f"👤 <b>Владелец:</b> Вы / You",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )

        logger.info(f"Успешно обработан: {target_set_name} -> {len(created_packs)} частей.")

    except TelegramBadRequest as e:
        logger.error(f"TelegramBadRequest: {e}", exc_info=True)
        error_text = html.escape(str(e))
        if "PEER_ID_INVALID" in error_text or "USER_IS_BLOCKED" in error_text:
            msg = "❌ Ошибка: напишите боту в личные сообщения / Message the bot directly."
        else:
            msg = f"❌ Ошибка Telegram / Error: <code>{error_text}</code>"
        await status_msg.edit_text(msg, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.exception("Ошибка при клонировании")
        await status_msg.edit_text(f"❌ Ошибка / Error: {e}")

    finally:
        active_users.discard(user_id)


@dp.message(CommandStart())
async def handle_start(message: Message):
    first_name = html.escape(message.from_user.first_name or "друг")
    text = (
        f"👋 <b>Привет, {first_name}! / Hello!</b>\n\n"
        f"Отправь мне <b>любой стикер</b> или ссылку на пак — я мгновенно создам твою личную копию!\n\n"
        f"Send me <b>any sticker</b> or pack link — I will instantly clone it as your own!"
    )
    await message.reply(text, parse_mode=ParseMode.HTML)


@dp.message(Command("help"))
async def handle_help(message: Message):
    await message.reply(
        "💡 <b>Как пользоваться / How to use:</b>\n\n"
        "1. Отправь любой стикер из нужного пака.\n"
        "2. Или отправь ссылку вида <code>t.me/addstickers/...</code>\n"
        "3. Бот мгновенно создаст пак от твоего имени!\n\n"
        "1. Send any sticker from the set.\n"
        "2. Or send a link like <code>t.me/addstickers/...</code>\n"
        "3. The bot will instantly clone it under your ownership!",
        parse_mode=ParseMode.HTML
    )


@dp.message(F.sticker)
async def handle_sticker(message: Message):
    sticker = message.sticker
    if not sticker.set_name:
        await message.reply("❌ Этот стикер не привязан к набору / Standalone sticker (no pack).")
        return

    await clone_sticker_set(sticker.set_name, message)


@dp.message(F.text)
async def handle_text(message: Message):
    text = message.text.strip()
    match = STICKER_URL_REGEX.search(text)
    if match:
        set_name = match.group(1)
        await clone_sticker_set(set_name, message)
        return

    if re.match(r"^[a-zA-Z0-9_]{3,64}$", text) and not text.startswith("/"):
        await clone_sticker_set(text, message)
        return

    await message.reply(
        "Отправьте мне стикер или ссылку на пак вида:\n"
        "Send me a sticker or pack link:\n"
        "<code>https://t.me/addstickers/name</code>",
        parse_mode=ParseMode.HTML
    )


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
