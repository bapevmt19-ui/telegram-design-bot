"""Các job chạy định kỳ: bản tin sáng, cheat sheet trưa, trích sách tối."""
import asyncio
import logging
import os
from datetime import datetime

import feedparser
import pytz
import trafilatura
from gtts import gTTS
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ai_client import call_gemini_async, clean_for_telegram, telegraph_client
from config import CHAT_ID_BOOKS, CHAT_ID_NEWS, RSS_FEEDS_AI, RSS_FEEDS_DESIGN
from telegram_helpers import send_chunked_message, unique_temp_path

logger = logging.getLogger(__name__)
VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")


async def send_business_cheat(context: ContextTypes.DEFAULT_TYPE):
    prompt = """Đóng vai một chuyên gia kinh doanh và ngôn ngữ. Hãy chia sẻ 1 'Business Cheat' cực kỳ thực chiến.
    Cấu trúc:
    1. 🧠 Tên chiến thuật (Tên tiếng Việt + Tiếng Anh).
    2. 🎯 Bản chất & Ứng dụng (Giải thích thật ngắn gọn, sắc bén kèm ví dụ).
    3. 📚 English Cheat Sheet (3 từ vựng chuyên ngành. VỚI MỖI TỪ: Cung cấp Phiên âm quốc tế IPA + Cách đọc bồi tiếng Việt cho dễ đọc).
    Không dùng markdown # hay **, chỉ dùng thẻ <b> hoặc <i>.
    QUAN TRỌNG: Dòng cuối cùng của kết quả PHẢI ghi đúng cú pháp sau để hệ thống tạo giọng đọc chuẩn bản xứ:
    AUDIO_VOCAB|từ vựng 1, từ vựng 2, từ vựng 3"""
    try:
        res = await call_gemini_async(prompt)

        text_parts = []
        vocab_for_audio = ""
        for line in res.split("\n"):
            if line.startswith("AUDIO_VOCAB|"):
                vocab_for_audio = line.split("|")[1]
            else:
                text_parts.append(line)

        body = "\n".join(text_parts)
        msg = f"🍱 <b>BỮA TRƯA DOANH NHÂN</b>\n\n{clean_for_telegram(body)}"

        async def _rep(t, parse_mode="HTML"):
            return await context.bot.send_message(chat_id=CHAT_ID_BOOKS, text=t, parse_mode=parse_mode)

        await send_chunked_message(_rep, msg)

        if vocab_for_audio:
            audio_path = unique_temp_path("vocab", ".mp3")
            # gTTS().save() là I/O mạng đồng bộ -> chạy trong thread
            # riêng để không đơ bot trong lúc tạo giọng đọc.
            await asyncio.to_thread(lambda: gTTS(text=vocab_for_audio, lang="en").save(audio_path))
            try:
                with open(audio_path, "rb") as voice:
                    await context.bot.send_voice(chat_id=CHAT_ID_BOOKS, voice=voice)
            finally:
                if os.path.exists(audio_path):
                    os.remove(audio_path)
    except Exception as e:
        logger.error("Lỗi gửi Business Cheat: %s", e)


async def send_news_to_channel(context: ContextTypes.DEFAULT_TYPE):
    today_str = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    prompt = "Tóm tắt 1 tin cực ngắn về AI hoặc Design hôm nay. Chỉ 2 dòng. Tuyệt đối KHÔNG dùng ký tự markdown như ** hay #."
    try:
        intro = await call_gemini_async(prompt)
    except Exception:
        intro = "Chúc sếp một ngày mới tràn đầy năng lượng!"

    msg = (
        f"🌅 <b>BẢN TIN SÁNG - {today_str}</b>\n\n{clean_for_telegram(intro)}\n\n"
        "<i>(Hệ thống đang cào và dịch tin chi tiết, sếp đợi 1 phút nhé...)</i>"
    )

    async def _rep(t, parse_mode="HTML"):
        return await context.bot.send_message(chat_id=CHAT_ID_NEWS, text=t, parse_mode=parse_mode)

    await send_chunked_message(_rep, msg)

    articles_sent = 0
    try:
        feeds = [
            ("💡 UX/UI Design", RSS_FEEDS_DESIGN["💡 UX/UI Design"], "🎨 Design"),
            ("🤖 AI News", RSS_FEEDS_AI["🤖 AI News"], "🤖 AI"),
        ]
        for _title, url, tag in feeds:
            # feedparser.parse + trafilatura là network I/O đồng bộ ->
            # chạy trong thread riêng.
            feed = await asyncio.to_thread(feedparser.parse, url)
            if not feed.entries:
                continue
            entry = feed.entries[0]
            downloaded = await asyncio.to_thread(trafilatura.fetch_url, entry.link)
            if not downloaded:
                continue
            text_content = await asyncio.to_thread(trafilatura.extract, downloaded)
            if not text_content:
                continue

            trans_prompt = (
                "Dịch bài viết sang tiếng Việt. Trả về định dạng HTML cơ bản "
                f"(chỉ dùng <h3>, <p>, <ul>, <li>, <b>, <i>). Nguồn:\n\n{text_content[:3000]}"
            )
            trans_html = await call_gemini_async(trans_prompt)
            trans_html = (
                trans_html.replace("```html", "").replace("```", "").replace("<h1>", "<h3>").replace("<h2>", "<h3>")
            )
            response = await asyncio.to_thread(
                telegraph_client.create_page,
                title=entry.title[:100],
                html_content=trans_html + f"<br><br><a href='{entry.link}'>Link bài viết gốc</a>",
            )
            await send_chunked_message(_rep, f"{tag}: <a href='{response['url']}'>{entry.title}</a>")
            articles_sent += 1
    except Exception as e:
        logger.error("Lỗi cào tin: %s", e)

    if articles_sent > 0:
        keyboard = [[InlineKeyboardButton("👁️ Xác nhận đã đọc xong tin", callback_data=f"read_{today_str}")]]
        await context.bot.send_message(
            chat_id=CHAT_ID_NEWS,
            text="📡 <i>Đã dịch và cập nhật xong bản tin hôm nay!</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def send_book_to_channel(context: ContextTypes.DEFAULT_TYPE):
    today_str = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    prompt = """Trích NGUYÊN VĂN 1 đoạn trích tinh hoa (300 chữ) từ 1 cuốn sách Tâm lý/Tiền bạc kinh điển. KHÔNG DÙNG Markdown (**, #, ###).
    [Emoji] Tên sách - Tác giả
    [Nội dung trích đoạn]
    💡 Suy ngẫm của quản gia: (1 câu đúc kết)"""
    # BUG FIX: bản gốc gọi client.models.generate_content trực tiếp,
    # không có retry/fallback -> job hằng ngày này có thể "trắng tay"
    # nếu Gemini lỗi thoáng qua đúng lúc 20h.
    response = await call_gemini_async(prompt)
    keyboard = [[InlineKeyboardButton("📖 Đã đọc xong & Suy ngẫm", callback_data=f"book_read_{today_str}")]]
    await context.bot.send_message(
        chat_id=CHAT_ID_BOOKS,
        text=clean_for_telegram(response),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def manual_trigger(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Đang đẩy bài test ra các kênh...")
    await send_news_to_channel(context)
    await send_business_cheat(context)
    await send_book_to_channel(context)
