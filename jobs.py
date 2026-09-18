"""Các job chạy định kỳ: bản tin sáng, cheat sheet trưa, trích sách tối."""
import asyncio
import logging
import os
from datetime import datetime, timedelta

import feedparser
import pytz
import trafilatura
from gtts import gTTS
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ai_client import call_gemini_async, clean_for_telegram, telegraph_client
from config import CHAT_ID_BOOKS, CHAT_ID_NEWS, CHAT_ID_PRIVATE, RSS_FEEDS_AI, RSS_FEEDS_DESIGN
from core_actions import is_deadline_overdue, render_tasks_message
from storage import content_history_store, finance_store, health_store, nutrition_store, todo_store
from telegram_helpers import send_chunked_message, unique_temp_path

logger = logging.getLogger(__name__)
VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")

# BUG FIX (17/9, lần 6): trước đây send_business_cheat và
# send_book_to_channel gọi Gemini với prompt Y HỆT mỗi ngày, không hề
# biết các ngày trước đã gửi chủ đề/cuốn sách gì -- Gemini không có
# ký ức giữa các lần gọi API riêng biệt, nên dễ lặp lại nội dung sau
# một thời gian (sếp phản ánh "gửi bài viết giống nhau quá"). Giải
# pháp: lưu lại "lịch sử" các chủ đề/sách đã gửi (content_history_store),
# rồi CHÈN VÀO PROMPT lần sau để chủ động nhắc Gemini né những cái đã
# dùng -- đây là cách thực tế nhất để giảm lặp khi mỗi lần gọi API là
# một phiên độc lập, không có bộ nhớ hội thoại.
HISTORY_KEEP = 30


async def _get_recent_history(list_key: str) -> list:
    history = await content_history_store.read()
    return history.get(list_key, [])[-HISTORY_KEEP:]


async def _append_history(list_key: str, item: str):
    if not item:
        return

    def _mutate(data):
        items = data.setdefault(list_key, [])
        items.append(item)
        if len(items) > HISTORY_KEEP:
            del items[: len(items) - HISTORY_KEEP]
        return data

    await content_history_store.update(_mutate)


async def send_business_cheat(context: ContextTypes.DEFAULT_TYPE):
    recent_topics = await _get_recent_history("cheat_topics")
    avoid_str = (
        "TUYỆT ĐỐI KHÔNG được chọn lại các chiến thuật đã chia sẻ gần đây: " + "; ".join(recent_topics)
        if recent_topics
        else "Đây là lần đầu tiên, thoải mái chọn."
    )
    prompt = f"""Đóng vai một chuyên gia kinh doanh và ngôn ngữ. Hãy chia sẻ 1 'Business Cheat' cực kỳ thực chiến.
    {avoid_str}
    Cấu trúc:
    1. 🧠 Tên chiến thuật (Tên tiếng Việt + Tiếng Anh).
    2. 🎯 Bản chất & Ứng dụng (Giải thích thật ngắn gọn, sắc bén kèm ví dụ).
    3. 📚 English Cheat Sheet (3 từ vựng chuyên ngành. VỚI MỖI TỪ: Cung cấp Phiên âm quốc tế IPA + Cách đọc bồi tiếng Việt cho dễ đọc).
    Không dùng markdown # hay **, chỉ dùng thẻ <b> hoặc <i>.
    QUAN TRỌNG: 2 dòng cuối cùng của kết quả PHẢI ghi đúng cú pháp sau (không hiển thị gì thêm sau đó):
    AUDIO_VOCAB|từ vựng 1, từ vựng 2, từ vựng 3
    TOPIC_NAME|Tên chiến thuật (tiếng Anh, ngắn gọn, dùng để lưu lịch sử tránh lặp)"""
    try:
        res = await call_gemini_async(prompt)

        text_parts = []
        vocab_for_audio = ""
        topic_name = ""
        for line in res.split("\n"):
            if line.startswith("AUDIO_VOCAB|"):
                vocab_for_audio = line.split("|")[1]
            elif line.startswith("TOPIC_NAME|"):
                topic_name = line.split("|", 1)[1].strip()
            else:
                text_parts.append(line)

        body = "\n".join(text_parts)
        msg = f"🍱 <b>BỮA TRƯA DOANH NHÂN</b>\n\n{clean_for_telegram(body)}"

        async def _rep(t, parse_mode="HTML"):
            return await context.bot.send_message(chat_id=CHAT_ID_BOOKS, text=t, parse_mode=parse_mode)

        await send_chunked_message(_rep, msg)
        await _append_history("cheat_topics", topic_name)

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

            # BUG FIX (18/9, lần 9): trước đây cắt cứng text_content chỉ
            # lấy 3000 ký tự đầu (~nửa trang) trước khi đưa cho Gemini
            # dịch -> mọi bài báo dài hơn thế bị dịch THIẾU nguyên phần
            # sau ký tự thứ 3000, không phải do Gemini dịch sót mà do
            # nội dung đó chưa từng được gửi đi. Gemini Flash chịu được
            # input dài hơn thế rất nhiều (context window cỡ triệu
            # token), nên nâng lên 20000 ký tự — đủ cho gần như mọi bài
            # báo trọn vẹn, vẫn có 1 giới hạn để tránh trường hợp hiếm
            # gặp 1 trang cực dài (VD bị lỗi crawl dính nguyên navbar
            # lặp) làm phình prompt vô tội vạ.
            trans_prompt = (
                "Dịch TOÀN BỘ bài viết sang tiếng Việt, không được bỏ sót đoạn nào. Trả về định dạng HTML cơ bản "
                f"(chỉ dùng <h3>, <p>, <ul>, <li>, <b>, <i>). Nguồn:\n\n{text_content[:20000]}"
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
    recent_books = await _get_recent_history("book_titles")
    avoid_str = (
        "TUYỆT ĐỐI KHÔNG được chọn lại các cuốn sách đã trích gần đây: " + "; ".join(recent_books)
        if recent_books
        else "Đây là lần đầu tiên, thoải mái chọn."
    )
    prompt = f"""Trích NGUYÊN VĂN 1 đoạn trích tinh hoa (300 chữ) từ 1 cuốn sách Tâm lý/Tiền bạc kinh điển. KHÔNG DÙNG Markdown (**, #, ###).
    {avoid_str}
    [Emoji] Tên sách - Tác giả
    [Nội dung trích đoạn]
    💡 Suy ngẫm của quản gia: (1 câu đúc kết)
    QUAN TRỌNG: Dòng cuối cùng PHẢI ghi đúng cú pháp sau (không hiển thị gì thêm sau đó):
    BOOK_TITLE|Tên sách - Tác giả"""
    # BUG FIX: bản gốc gọi client.models.generate_content trực tiếp,
    # không có retry/fallback -> job hằng ngày này có thể "trắng tay"
    # nếu Gemini lỗi thoáng qua đúng lúc 20h.
    response = await call_gemini_async(prompt)

    book_title = ""
    text_parts = []
    for line in response.split("\n"):
        if line.startswith("BOOK_TITLE|"):
            book_title = line.split("|", 1)[1].strip()
        else:
            text_parts.append(line)
    body = "\n".join(text_parts).strip()

    keyboard = [[InlineKeyboardButton("📖 Đã đọc xong & Suy ngẫm", callback_data=f"book_read_{today_str}")]]
    await context.bot.send_message(
        chat_id=CHAT_ID_BOOKS,
        text=clean_for_telegram(body),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    await _append_history("book_titles", book_title)


async def manual_trigger(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Đang đẩy bài test ra các kênh...")
    await send_news_to_channel(context)
    await send_business_cheat(context)
    await send_book_to_channel(context)


# Nâng cấp (17/9, lần 7): nhắc cập nhật chi tiêu cuối ngày — nếu hôm
# đó chưa ghi khoản chi nào (kể cả 0đ tức không tiêu gì) thì mới nhắc,
# tránh làm phiền khi sếp đã ghi rồi.
async def remind_expense_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        finance = await finance_store.read()
        today_str = datetime.now(VN_TZ).strftime("%Y-%m-%d")
        today_expenses = [e for e in finance.get("expenses", []) if e.get("date") == today_str]
        if today_expenses:
            return
        await context.bot.send_message(
            chat_id=CHAT_ID_PRIVATE,
            text="🌙 Sếp ơi, hôm nay chưa ghi khoản chi tiêu nào. Đừng quên /spend nếu có phát sinh nhé!",
        )
    except Exception as e:
        logger.error("Lỗi gửi nhắc chi tiêu cuối ngày: %s", e)


# Nâng cấp (17/9, lần 7): "nhắc việc nâng cao" — thay vì chỉ hiện danh
# sách khi sếp tự gõ /tasks, bot chủ động đẩy lại danh sách việc còn
# tồn đọng theo lịch (xem main.py):
#   - urgent_only=False: 3 khung giờ hành chính cố định/ngày, cho MỌI
#     việc còn tồn đọng.
#   - urgent_only=True: mỗi 2 tiếng trong giờ hành chính, CHỈ cho việc
#     gắn !gấp hoặc đã tới/quá hạn (hạn:DD/MM) — để việc gấp không bị
#     trôi mất giữa 2 lần nhắc cố định.
# Dùng chung render_tasks_message() với /tasks (core_actions.py) nên
# mỗi việc luôn có nút "✅ Xong" RIÊNG theo đúng id của nó — bấm xong 1
# việc không hề ảnh hưởng tới các việc còn lại trong danh sách.
async def broadcast_tasks_reminder(context: ContextTypes.DEFAULT_TYPE, urgent_only: bool = False):
    try:
        todos = await todo_store.read()
        pending = [t for t in todos.get("tasks", []) if t["status"] == "pending"]
        if urgent_only:
            pending = [t for t in pending if t.get("urgent") or is_deadline_overdue(t.get("deadline"))]
        if not pending:
            return  # không có gì để nhắc -> im lặng, tránh gửi tin rỗng

        msg, keyboard = render_tasks_message(pending)
        if urgent_only:
            msg = "⚡ <b>NHẮC VIỆC GẤP/QUÁ HẠN:</b>\n\n" + msg.split("\n\n", 1)[1]
        await context.bot.send_message(
            chat_id=CHAT_ID_PRIVATE, text=msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error("Lỗi gửi nhắc việc tự động (urgent_only=%s): %s", urgent_only, e)


async def broadcast_urgent_tasks_reminder(context: ContextTypes.DEFAULT_TYPE):
    await broadcast_tasks_reminder(context, urgent_only=True)


# Nâng cấp (18/9, lần 11 — gói miễn phí): tổng kết nhanh cuối tuần —
# thuần tính toán trên dữ liệu tài chính/sức khoẻ ĐÃ CÓ SẴN trong
# Postgres, KHÔNG gọi Gemini (không tốn thêm hạn mức free API), gửi vào
# chat riêng của sếp mỗi Chủ Nhật, trước giờ backup tự động (xem
# main.py: 21h, backup chạy lúc 22h).
async def weekly_summary_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        today = datetime.now(VN_TZ).date()
        week_start = today - timedelta(days=6)

        finance = await finance_store.read()
        week_expenses = []
        for e in finance.get("expenses", []):
            try:
                e_date = datetime.strptime(e["date"], "%Y-%m-%d").date()
            except Exception:
                continue
            if week_start <= e_date <= today:
                week_expenses.append(e)
        total_week = sum(e["amount"] for e in week_expenses)

        cat_totals: dict[str, float] = {}
        for e in week_expenses:
            cat = e.get("category", "Khac")
            cat_totals[cat] = cat_totals.get(cat, 0) + e["amount"]
        cat_lines = "\n".join(
            f"  • {c}: {v:,.0f} VNĐ" for c, v in sorted(cat_totals.items(), key=lambda x: -x[1])
        )

        msg = (
            f"📅 <b>TỔNG KẾT TUẦN ({week_start.strftime('%d/%m')} - {today.strftime('%d/%m')})</b>\n\n"
            f"💸 <b>Tổng chi tiêu tuần:</b> {total_week:,.0f} VNĐ\n"
        )
        if cat_lines:
            msg += cat_lines + "\n"
        if not week_expenses:
            msg += "  <i>(Không có khoản chi nào được ghi trong tuần)</i>\n"

        health = await health_store.read()
        nutrition = await nutrition_store.read()
        if health and nutrition:
            target = health.get("target_calories", 0)
            days_with_data, total_calories = 0, 0
            d = week_start
            while d <= today:
                day_data = nutrition.get(d.strftime("%Y-%m-%d"))
                if day_data:
                    days_with_data += 1
                    total_calories += day_data.get("consumed_calories", 0)
                d += timedelta(days=1)
            if days_with_data:
                avg = total_calories / days_with_data
                msg += (
                    f"\n🍽️ <b>Trung bình calo/ngày (các ngày có ghi nhận):</b> {avg:,.0f} / {target:,.0f} kcal "
                    f"({days_with_data}/7 ngày có ghi nhận)"
                )

        await context.bot.send_message(chat_id=CHAT_ID_PRIVATE, text=clean_for_telegram(msg), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("Lỗi gửi tổng kết tuần: %s", e)
