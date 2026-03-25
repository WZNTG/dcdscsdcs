"""
🎙 Telegram Transcription Bot
Распознаёт голос в: голосовых сообщениях, видео-кружках, видео с аудио
Работает в личных чатах и группах. Отвечает субтитрами на то же сообщение.
"""

import os
import logging
import tempfile
import asyncio
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
#  НАСТРОЙКИ — замени токен на свой!
# ══════════════════════════════════════════════════════

BOT_TOKEN = "8651118716:AAGaclMWYm1nyb73c-NBtPUPzKrqIOyTpss"

# Модель Whisper:
#   "tiny"   — ~1 ГБ RAM, быстро, чуть хуже качество
#   "base"   — ~1 ГБ RAM, хороший баланс  ← рекомендуется
#   "small"  — ~2 ГБ RAM, точнее
#   "medium" — ~5 ГБ RAM, ещё точнее
#   "large"  — ~10 ГБ RAM, максимум
WHISPER_MODEL = "base"

# Текст приветствия после /start
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
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════
#  ЗАГРУЗКА МОДЕЛИ
# ══════════════════════════════════════════════════════

logger.info(f"⏳ Загружаю модель Whisper '{WHISPER_MODEL}'...")
model = whisper.load_model(WHISPER_MODEL)
logger.info("✅ Модель загружена и готова к работе!")

# ══════════════════════════════════════════════════════
#  ТРАНСКРИБАЦИЯ
# ══════════════════════════════════════════════════════

async def transcribe_audio(file_path: str) -> str:
    """Запускает Whisper в отдельном потоке (не блокирует event loop)."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: model.transcribe(file_path, task="transcribe"),
    )
    text = result.get("text", "").strip()
    return text

# ══════════════════════════════════════════════════════
#  КОМАНДА /start
# ══════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")

# ══════════════════════════════════════════════════════
#  ОБРАБОТЧИК МЕДИА
# ══════════════════════════════════════════════════════

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat

    # Определяем тип сообщения
    if message.voice:
        media    = message.voice
        label    = "🎙 Голосовое"
        suffix   = ".ogg"
    elif message.video_note:
        media    = message.video_note
        label    = "📹 Кружок"
        suffix   = ".mp4"
    elif message.video and message.video.file_size:
        media    = message.video
        label    = "🎬 Видео"
        suffix   = ".mp4"
    else:
        return

    # Показываем индикатор «печатает»
    await context.bot.send_chat_action(chat_id=chat.id, action="typing")

    tmp_path = None
    try:
        # Скачиваем файл
        tg_file = await context.bot.get_file(media.file_id)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        await tg_file.download_to_drive(custom_path=tmp_path)

        # Снова «печатает» (распознавание может занять время)
        await context.bot.send_chat_action(chat_id=chat.id, action="typing")

        # Транскрибируем
        text = await transcribe_audio(tmp_path)

        if not text:
            await message.reply_text(
                "🤔 Не удалось распознать речь — возможно, сообщение слишком тихое или без слов."
            )
            return

        # Форматируем ответ
        reply = f"{label} — субтитры:\n\n💬 {text}"

        # Отвечаем реплаем на исходное сообщение
        await message.reply_text(reply)

        logger.info(
            f"[{chat.title or chat.id}] {label} распознан: {text[:60]}..."
            if len(text) > 60 else
            f"[{chat.title or chat.id}] {label} распознан: {text}"
        )

    except Exception as e:
        logger.error(f"Ошибка при обработке медиа: {e}", exc_info=True)
        await message.reply_text(
            "⚠️ Произошла ошибка при распознавании. Попробуй отправить ещё раз."
        )

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

# ══════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════

def main():
    if BOT_TOKEN == "ВСТАВЬ_ТОКЕН_СЮДА":
        raise ValueError("❌ Вставь токен бота в переменную BOT_TOKEN!")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_start))

    # Медиа — работает в личке, группах, супергруппах
    media_filter = filters.VOICE | filters.VIDEO_NOTE | filters.VIDEO
    app.add_handler(MessageHandler(media_filter, handle_media))

    logger.info("🚀 Бот запущен! Жду сообщений...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
