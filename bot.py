#!/usr/bin/env python3
"""
🎙 Telegram Transcription Bot
Распознаёт голос в: голосовых сообщениях, видео-кружках, видео с аудио
Работает в личных чатах и группах. Отвечает субтитрами на то же сообщение.
"""

import os
import sys
import logging
import tempfile
import asyncio
from pathlib import Path
from datetime import datetime

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import whisper

# ══════════════════════════════════════════════════════
#  НАСТРОЙКИ (из переменных окружения)
# ══════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ Переменная окружения BOT_TOKEN не задана!")

# Модель Whisper (tiny, base, small, medium, large)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")

# Максимальное количество одновременно обрабатываемых файлов
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "2"))

# Максимальная длина текста ответа (Telegram: 4096 символов)
MAX_REPLY_LEN = 4000

# В группах бот обрабатывает сообщения только если его упомянули
# (для личных чатов всегда обрабатывает)
REQUIRE_MENTION_IN_GROUPS = os.getenv("REQUIRE_MENTION_IN_GROUPS", "true").lower() == "true"

# Текст приветствия
WELCOME_TEXT = (
    "👋 Привет! Я бот-транскрибатор.\n\n"
    "📋 *Что я умею:*\n"
    "🎙 Голосовые сообщения → текст\n"
    "📹 Видео-кружки → текст\n"
    "🎬 Видео с озвучкой → текст\n\n"
    "💬 Работаю в личных чатах и *группах*.\n"
    "Просто отправь или перешли голосовое / кружок — "
    "и я сразу отвечу субтитрами!\n\n"
    "🌍 Язык определяется *автоматически*."
)

# ══════════════════════════════════════════════════════
#  ЛОГИРОВАНИЕ
# ══════════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════
#  ЗАГРУЗКА МОДЕЛИ
# ══════════════════════════════════════════════════════

logger.info(f"⏳ Загружаю модель Whisper '{WHISPER_MODEL}'...")
model = whisper.load_model(WHISPER_MODEL)
logger.info("✅ Модель загружена и готова к работе!")

# Семафор для ограничения количества одновременных транскрибаций
transcription_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

# ══════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ══════════════════════════════════════════════════════

def should_handle(update: Update) -> bool:
    """Определяет, нужно ли обрабатывать сообщение."""
    message = update.effective_message
    chat = update.effective_chat

    # Личные чаты — обрабатываем всегда
    if chat.type == "private":
        return True

    # Группы — только если бот упомянут или сообщение является ответом на сообщение бота
    if REQUIRE_MENTION_IN_GROUPS:
        # Проверяем упоминание через entities
        if message.entities:
            for entity in message.entities:
                if entity.type == "mention" and message.text:
                    username = message.text[entity.offset:entity.offset + entity.length]
                    if username == f"@{update.get_bot().username}":
                        return True
        # Проверяем, что сообщение является ответом на сообщение бота
        if message.reply_to_message and message.reply_to_message.from_user.is_bot:
            return True
        return False
    else:
        # Если не требуется упоминание, обрабатываем все
        return True

async def transcribe_audio(file_path: str) -> str:
    """Запускает Whisper в отдельном потоке с ограничением параллельности."""
    async with transcription_semaphore:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: model.transcribe(file_path, task="transcribe"),
        )
        text = result.get("text", "").strip()
        return text

def truncate_text(text: str, limit: int) -> str:
    """Обрезает текст до заданной длины, добавляя многоточие."""
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."

# ══════════════════════════════════════════════════════
#  КОМАНДЫ
# ══════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает текущее состояние бота."""
    msg = (
        f"✅ Бот работает\n"
        f"📦 Модель: {WHISPER_MODEL}\n"
        f"🔄 Макс. параллельных задач: {MAX_CONCURRENT}\n"
        f"👥 В группах: {'только при упоминании' if REQUIRE_MENTION_IN_GROUPS else 'все сообщения'}"
    )
    await update.message.reply_text(msg)

# ══════════════════════════════════════════════════════
#  ОСНОВНОЙ ОБРАБОТЧИК МЕДИА
# ══════════════════════════════════════════════════════

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat

    # Проверяем, нужно ли обрабатывать это сообщение
    if not should_handle(update):
        return

    # Определяем тип медиа
    if message.voice:
        media = message.voice
        label = "🎙 Голосовое"
        suffix = ".ogg"
    elif message.video_note:
        media = message.video_note
        label = "📹 Кружок"
        suffix = ".mp4"
    elif message.video and message.video.file_size:
        media = message.video
        label = "🎬 Видео"
        suffix = ".mp4"
    else:
        return  # не наш тип

    # Показываем, что бот начал обработку
    await context.bot.send_chat_action(chat_id=chat.id, action="typing")

    tmp_path = None
    try:
        # Скачиваем файл
        tg_file = await context.bot.get_file(media.file_id)
        logger.info(f"Скачиваю {label} (ID: {media.file_id}, размер: {media.file_size} байт)")

        # Создаём временный файл
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name

        await tg_file.download_to_drive(custom_path=tmp_path)
        logger.info(f"Файл сохранён: {tmp_path}")

        # Снова отправляем действие "печатает" (транскрибация может занять время)
        await context.bot.send_chat_action(chat_id=chat.id, action="typing")

        # Транскрибируем
        start_time = datetime.now()
        text = await transcribe_audio(tmp_path)
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Транскрибация завершена за {elapsed:.1f} сек, символов: {len(text)}")

        if not text:
            await message.reply_text(
                "🤔 Не удалось распознать речь — возможно, сообщение слишком тихое или без слов."
            )
            return

        # Форматируем ответ, обрезаем при необходимости
        reply = f"{label} — субтитры:\n\n💬 {text}"
        reply = truncate_text(reply, MAX_REPLY_LEN)

        # Отправляем ответ
        await message.reply_text(reply)
        logger.info(f"[{chat.title or chat.id}] {label} распознан: {text[:60]}..." if len(text) > 60 else f"[{chat.title or chat.id}] {label} распознан: {text}")

    except Exception as e:
        logger.error(f"Ошибка при обработке медиа: {e}", exc_info=True)
        await message.reply_text(
            "⚠️ Произошла ошибка при распознавании. Попробуй отправить ещё раз."
        )
    finally:
        # Удаляем временный файл
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
                logger.debug(f"Удалён временный файл: {tmp_path}")
            except Exception as del_err:
                logger.warning(f"Не удалось удалить файл {tmp_path}: {del_err}")

# ══════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════

def main():
    # Создаём приложение
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Регистрируем команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))

    # Обработчик медиа (голосовые, кружки, видео)
    media_filter = filters.VOICE | filters.VIDEO_NOTE | filters.VIDEO
    app.add_handler(MessageHandler(media_filter, handle_media))

    logger.info("🚀 Бот запущен! Жду сообщений...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
