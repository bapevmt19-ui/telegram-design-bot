"""
Telegram Design News Bot - Interactive Habit Tracker
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timedelta, time
import pytz

from dotenv import load_dotenv
import feedparser
import trafilatura
import requests
from bs4 import BeautifulSoup
from telegraph import Telegraph
import markdown
from google import genai

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes, CallbackQueryHandler, CommandHandler
from telegram.constants import ParseMode

# ─── Cấu hình ───────────────────────────────────────────────
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_MODEL = "gemini-3.5-flash-lite"
HISTORY_FILE = "read_history.json"

RSS_FEEDS = {
    "💡 UX/UI Design (UX Collective)": "https://uxdesign.cc/feed",
    "🎨 Web Design (Smashing Mag)": "https://www.smashingmagazine.com/feed/",
    "✨ Graphic Design (Creative Bloq)": "https://www.creativebloq.com/feed",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

telegraph = Telegraph()
telegraph.create_account(short_name='DesignDaily', author_name='Design Daily Bot')


# ─── Database Thói Quen ─────────────────────────────────────
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=4)


# ─── Logic Tương Tác (Nút Bấm) ───────────────────────────────
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Tắt biểu tượng loading
    data = query.data
    
    if data.startswith("read_"):
        date_str = data.split("_")[1]
        
        # Cập nhật database
        history = load_history()
        history[date_str] = True
        save_history(history)
        
        # Đổi giao diện nút bấm
        now_str = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime("%H:%M")
        keyboard = [[InlineKeyboardButton(f"✅ Đã đọc lúc {now_str}", callback_data="already_read")]]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data == "already_read":
        await query.answer("Bạn đã xác nhận đọc bản tin này rồi!", show_alert=True)


# ─── Cào & Dịch Tin ─────────────────────────────────────────
def create_gemini_client() -> genai.Client:
    return genai.Client(api_key=GEMINI_API_KEY)


def translate_and_publish(client: genai.Client, title: str, original_url: str) -> str:
    try:
        content = None
        downloaded = trafilatura.fetch_url(original_url)
        content = trafilatura.extract(downloaded) if downloaded else None
        
        if not content or len(content) < 200:
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                resp = requests.get(original_url, headers=headers, timeout=10)
                soup = BeautifulSoup(resp.content, 'html.parser')
                content = "\n\n".join([p.get_text() for p in soup.find_all(['p', 'h2', 'h3'])])
            except Exception: pass

        if not content or len(content) < 200:
            try:
                proxy_url = f"https://api.allorigins.win/get?url={requests.utils.quote(original_url)}"
                resp = requests.get(proxy_url, timeout=15)
                html_data = resp.json().get('contents', '')
                soup = BeautifulSoup(html_data, 'html.parser')
                content = "\n\n".join([p.get_text() for p in soup.find_all(['p', 'h2', 'h3'])])
            except Exception: pass

        if not content or len(content) < 200:
            return original_url

        prompt = f"""Dịch bài viết chuyên ngành UI/UX/Graphic Design sau sang tiếng Việt.
Tiêu đề gốc: {title}
Nội dung gốc (cắt bớt): 
{content[:7000]}

YÊU CẦU DỊCH THUẬT CHUYÊN NGÀNH:
1. TUYỆT ĐỐI GIỮ NGUYÊN các thuật ngữ tiếng Anh chuyên ngành (ví dụ: Layout, Grid, Typography, User Flow, Wireframe, Prototype, Padding, Component...).
2. Dịch thoát ý, văn phong chuyên nghiệp, hiện đại.
3. Trình bày bằng cú pháp Markdown. KHÔNG dùng HTML tags. Bỏ qua các đoạn quảng cáo.
"""
        res = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        vn_markdown = res.text + f"\n\n---\n🔗 [**Đọc bài viết gốc bằng tiếng Anh tại đây**]({original_url})"

        html_content = markdown.markdown(vn_markdown)
        html_content = html_content.replace('<h1>', '<h3>').replace('</h1>', '</h3>').replace('<h2>', '<h3>').replace('</h2>', '</h3>')

        response = telegraph.create_page(title=title, html_content=html_content, author_name="Design Daily", author_url=original_url)
        return response['url']
    except Exception as e:
        logger.error(f"Lỗi khi xử lý bài {title}: {e}")
        return original_url


def fetch_and_summarize(client: genai.Client, rss_url: str) -> str:
    feed = feedparser.parse(rss_url)
    if not feed.entries: return "⚠️ Không có bài viết mới."
    
    sections = []
    for entry in feed.entries[:2]: 
        telegraph_url = translate_and_publish(client, entry.title, entry.link)
        prompt_summary = f"""Đóng vai Senior Designer, phân tích bài:
Title: {entry.title}
Content: {entry.description}
1. Dịch Tiêu đề sang Tiếng Việt (Giữ nguyên thuật ngữ chuyên ngành).
2. Rút ra 1 Insight cốt lõi (1-2 câu Tiếng Việt) chứa bài học đắt giá nhất.
TIEU_DE: [Tiêu đề dịch]
INSIGHT: [Insight]"""
        try:
            insight_res = client.models.generate_content(model=GEMINI_MODEL, contents=prompt_summary)
            res_text = insight_res.text.strip()
            tieu_de_dich, insight_dich = entry.title, "Bài viết chuyên sâu về Design."
            for line in res_text.split('\n'):
                if line.startswith('TIEU_DE:'): tieu_de_dich = line.replace('TIEU_DE:', '').strip()
                elif line.startswith('INSIGHT:'): insight_dich = line.replace('INSIGHT:', '').strip()
        except:
            tieu_de_dich, insight_dich = entry.title, "Bài viết chuyên sâu."

        sections.append(f"• <b>{tieu_de_dich}</b>\n💡 <i>Insight:</i> {insight_dich}\n👉 <a href='{telegraph_url}'>Đọc bản Tiếng Việt</a>")
    return "\n\n".join(sections)


def split_message(text: str, max_len: int) -> list[str]:
    parts = []
    while len(text) > max_len:
        split_pos = text.rfind("\n", 0, max_len)
        if split_pos == -1: split_pos = max_len
        parts.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    if text: parts.append(text)
    return parts


async def generate_and_send_digest(context: ContextTypes.DEFAULT_TYPE):
    chat_id = TELEGRAM_CHAT_ID
    
    # 1. Quản lý Thói quen đọc (Habit Tracker)
    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    today_str = datetime.now(vn_tz).strftime("%Y-%m-%d")
    yesterday_str = (datetime.now(vn_tz) - timedelta(days=1)).strftime("%Y-%m-%d")
    
    history = load_history()
    
    missed_yesterday = False
    if yesterday_str in history and history[yesterday_str] == False:
        missed_yesterday = True
        
    if today_str not in history:
        history[today_str] = False
        save_history(history)

    # 2. Tạo bản tin
    client = create_gemini_client()
    sections = []
    for topic, url in RSS_FEEDS.items():
        logger.info(f"Đang xử lý Topic: {topic}")
        news = fetch_and_summarize(client, url)
        sections.append(f"📌 <b>{topic}</b>\n\n{news}")

    header = f"📰 <b>BẢN TIN DESIGN - {today_str}</b>\n{'━' * 30}\n\n"
    if missed_yesterday:
        header = "⚠️ <i>Ê chăn ấm nệm êm ơi! Ngày hôm qua bạn đã bỏ lỡ bản tin Design quan trọng đấy nhé! Đọc ngay tin hôm nay để không bị tụt hậu!</i> 😤\n\n" + header
        
    footer = f"\n\n{'━' * 30}\n🤖 <i>Dịch & Tổng hợp bởi Gemini AI</i>"
    digest = header + "\n\n".join(sections) + footer

    # 3. Gắn nút và Gửi
    keyboard = [[InlineKeyboardButton("👁️ Xác nhận đã đọc", callback_data=f"read_{today_str}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    max_len = 4000
    if len(digest) <= max_len:
        await context.bot.send_message(chat_id=chat_id, text=digest, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=reply_markup)
    else:
        parts = split_message(digest, max_len)
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            await context.bot.send_message(chat_id=chat_id, text=part, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=reply_markup if is_last else None)
            if not is_last: await asyncio.sleep(1)


# ─── Lệnh Gọi Chạy Test ─────────────────────────────────────
async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /news để người dùng ép bot cào tin ngay lập tức."""
    await update.message.reply_text("⏳ Đang cào và dịch tin Design mới nhất, vui lòng đợi khoảng 40 giây...")
    # Chạy background để không block bot
    asyncio.create_task(generate_and_send_digest(context))


# ─── Dummy Web Server (Dành cho Render) ─────────────────────
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    server.serve_forever()

# ─── Khởi chạy Bot ──────────────────────────────────────────
def main():
    if not GEMINI_API_KEY or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("❌ Thiếu cấu hình API Key.")
        return

    # Khởi động Web Server giả để Render không tắt Bot
    threading.Thread(target=run_dummy_server, daemon=True).start()

    logger.info("🤖 Telegram Design Bot (24/7) đang khởi động...")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Xử lý nút bấm và lệnh
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(CommandHandler("news", news_command))

    # Đặt lịch chạy lúc 7h sáng và 18h chiều (Giờ VN)
    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    t_morning = time(hour=7, minute=0, tzinfo=vn_tz)
    t_evening = time(hour=18, minute=0, tzinfo=vn_tz)
    
    job_queue = application.job_queue
    job_queue.run_daily(generate_and_send_digest, time=t_morning)
    job_queue.run_daily(generate_and_send_digest, time=t_evening)

    # Chạy vòng lặp lắng nghe tương tác (24/7)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
