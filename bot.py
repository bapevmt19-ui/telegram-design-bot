"""
Telegram Super Bot - Design, AI, Books, Finance & Personal Assistant
"""
import os
import json
import logging
import asyncio
import re
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
from google.genai import types

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes, CallbackQueryHandler, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_MODEL = "gemini-3.5-flash-lite"
HISTORY_FILE = "read_history.json"
FINANCE_FILE = "finance.json"
BUDGET_PER_WEEK = 2000000 # 2 triệu VNĐ mặc định (Bạn có thể sửa ở đây)

# Thêm nguồn tin AI
RSS_FEEDS_DESIGN = {
    "💡 UX/UI Design": "https://uxdesign.cc/feed",
    "🎨 Web Design": "https://www.smashingmagazine.com/feed/",
}
RSS_FEEDS_AI = {
    "🤖 AI News": "https://www.artificialintelligence-news.com/feed/"
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

telegraph = Telegraph()
telegraph.create_account(short_name='SuperDaily', author_name='Super Bot')

# Khởi tạo Client Gemini toàn cục và Bộ Nhớ Chat
client = genai.Client(api_key=GEMINI_API_KEY)
chat_session = client.chats.create(model=GEMINI_MODEL) # Lưu ngữ cảnh chat đa lượt

# --- HỆ QUẢN TRỊ DATABASE ---
def load_json(file_path, default):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            try: return json.load(f)
            except: return default
    return default

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# --- TRỤ CỘT 2: KẾ TOÁN TÀI CHÍNH ---
def parse_amount(amount_str):
    amount_str = amount_str.lower().replace(",", "").replace(".", "")
    if "k" in amount_str:
        return int(float(amount_str.replace("k", "")) * 1000)
    if "m" in amount_str or "tr" in amount_str:
        val = amount_str.replace("m", "").replace("tr", "")
        return int(float(val) * 1000000)
    return int(amount_str)

async def spend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý lệnh: /spend 50k ăn sáng"""
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Sai cú pháp! Hãy dùng: `/spend [số tiền] [lý do]`\nVí dụ: `/spend 50k ăn sáng` hoặc `/spend 1.5M Mua áo`", parse_mode=ParseMode.MARKDOWN)
            return
            
        amount_str = args[0]
        reason = " ".join(args[1:])
        amount = parse_amount(amount_str)
        
        vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        now = datetime.now(vn_tz)
        week_num = now.isocalendar()[1]
        
        finance_data = load_json(FINANCE_FILE, {"budget": BUDGET_PER_WEEK, "expenses": []})
        finance_data["expenses"].append({
            "date": now.strftime("%Y-%m-%d %H:%M"),
            "amount": amount,
            "reason": reason,
            "week": week_num
        })
        save_json(FINANCE_FILE, finance_data)
        
        total_week = sum(item["amount"] for item in finance_data["expenses"] if item.get("week") == week_num)
        remaining = finance_data["budget"] - total_week
        
        msg = f"💸 **Đã ghi nhận chi tiêu:**\n- Số tiền: {amount:,.0f} VNĐ\n- Lý do: {reason}\n\n📊 **Thống kê tuần này:**\n- Đã tiêu: {total_week:,.0f} VNĐ\n- Còn lại: {remaining:,.0f} VNĐ"
        if remaining < 0:
            msg += "\n\n⚠️ **BÁO ĐỘNG ĐỎ: BẠN ĐÃ TIÊU LỐ NGÂN SÁCH TUẦN NÀY!**"
            
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Lỗi cú pháp. Chi tiết: {e}")

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    week_num = datetime.now(vn_tz).isocalendar()[1]
    finance_data = load_json(FINANCE_FILE, {"budget": BUDGET_PER_WEEK, "expenses": []})
    
    weekly_expenses = [item for item in finance_data["expenses"] if item.get("week") == week_num]
    total_week = sum(item["amount"] for item in weekly_expenses)
    remaining = finance_data["budget"] - total_week
    
    msg = f"📊 **BÁO CÁO TÀI CHÍNH TUẦN NÀY**\nNgân sách: {finance_data['budget']:,.0f} VNĐ\n\n"
    for item in weekly_expenses:
        msg += f"- {item['date']}: {item['amount']:,.0f} đ ({item['reason']})\n"
        
    msg += f"\nTổng chi: **{total_week:,.0f} VNĐ**\nCòn lại: **{remaining:,.0f} VNĐ**"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# --- TRỤ CỘT 1 & 3: LẤY TIN, ĐỌC SÁCH, CHATBOT ---
def robust_scrape(url):
    content = None
    downloaded = trafilatura.fetch_url(url)
    content = trafilatura.extract(downloaded) if downloaded else None
    if not content or len(content) < 200:
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(resp.content, 'html.parser')
            content = "\n\n".join([p.get_text() for p in soup.find_all(['p', 'h2', 'h3'])])
        except Exception: pass
    if not content or len(content) < 200:
        try:
            proxy_url = f"https://api.allorigins.win/get?url={requests.utils.quote(url)}"
            resp = requests.get(proxy_url, timeout=15)
            html_data = resp.json().get('contents', '')
            soup = BeautifulSoup(html_data, 'html.parser')
            content = "\n\n".join([p.get_text() for p in soup.find_all(['p', 'h2', 'h3'])])
        except Exception: pass
    return content

def translate_and_publish(title: str, original_url: str, topic_type: str = "design") -> str:
    try:
        content = robust_scrape(original_url)
        if not content or len(content) < 200: return original_url

        if topic_type == "ai":
            prompt = f"Dịch và tóm tắt tin tức AI sau sang tiếng Việt. \nTiêu đề: {title}\nNội dung: {content[:7000]}\nYêu cầu: Viết chuyên nghiệp, trình bày Markdown. THÊM 1 MỤC CUỐI CÙNG: '💡 Gợi ý áp dụng AI này vào công việc/cuộc sống'."
        else:
            prompt = f"Dịch bài viết UI/UX Design sau sang tiếng Việt. Tiêu đề: {title}\nNội dung: {content[:7000]}\nYêu cầu: GIỮ NGUYÊN thuật ngữ chuyên ngành (Layout, Grid...). Trình bày Markdown, không HTML."

        res = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        vn_markdown = res.text + f"\n\n---\n🔗 [**Đọc bài gốc tại đây**]({original_url})"
        html_content = markdown.markdown(vn_markdown).replace('<h1>', '<h3>').replace('</h1>', '</h3>').replace('<h2>', '<h3>').replace('</h2>', '</h3>')
        response = telegraph.create_page(title=title, html_content=html_content, author_name="Super Bot", author_url=original_url)
        return response['url']
    except Exception:
        return original_url

async def fetch_news_logic(feeds_dict, topic_type="design"):
    sections = []
    for topic, url in feeds_dict.items():
        feed = feedparser.parse(url)
        if not feed.entries: continue
        entries_news = []
        for entry in feed.entries[:2]: 
            tele_url = translate_and_publish(entry.title, entry.link, topic_type)
            p = f"Dịch tiêu đề và tóm tắt 1 câu Insight đắt giá nhất của bài này:\nTitle: {entry.title}\nContent: {entry.description}\nFormat: \nTIEU_DE: [Tiêu đề]\nINSIGHT: [Insight]"
            try:
                res = client.models.generate_content(model=GEMINI_MODEL, contents=p).text.strip()
                td = re.search(r"TIEU_DE:\s*(.*)", res).group(1)
                ins = re.search(r"INSIGHT:\s*(.*)", res).group(1)
            except:
                td, ins = entry.title, "Tin hay đáng đọc."
            entries_news.append(f"• <b>{td}</b>\n💡 <i>Insight:</i> {ins}\n👉 <a href='{tele_url}'>Đọc chi tiết</a>")
        sections.append(f"📌 <b>{topic}</b>\n\n" + "\n\n".join(entries_news))
    return "\n\n".join(sections)

async def book_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📚 Đang vào thư viện tìm cho bạn một cuốn sách tinh hoa...")
    prompt = """Bạn là Thủ thư AI. Hãy chọn NGẪU NHIÊN 1 cuốn sách kinh điển về (Kinh tế, Tâm lý học, Triết học, Giao tiếp hoặc Phát triển bản thân - Tiền bạc) ĐÃ ĐƯỢC XUẤT BẢN BẢN DỊCH TIẾNG VIỆT.
Viết 1 bài review gồm:
1. Tiêu đề sách (Kèm tên tiếng Anh)
2. Tóm tắt cốt lõi (3 câu)
3. 💡 3 Bài học thực tiễn áp dụng vào cuộc sống.
Trình bày đẹp bằng Markdown, dùng emoji trực quan."""
    res = client.models.generate_content(model=GEMINI_MODEL, contents=prompt).text
    await update.message.reply_text(res, parse_mode=ParseMode.MARKDOWN)

async def handle_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý Chatbot tự nhiên và đọc URL"""
    text = update.message.text
    urls = re.findall(r'(https?://\S+)', text)
    
    if urls:
        url = urls[0]
        await update.message.reply_text("🔍 Đang đọc nội dung trang web bạn gửi...")
        content = robust_scrape(url)
        if not content:
            await update.message.reply_text("❌ Mình không thể đọc được nội dung từ link này.")
            return
        prompt = f"Người dùng vừa gửi link. Nội dung:\n{content[:15000]}\n\nHãy tóm tắt nội dung này, nêu bật các ý chính và giải thích chi tiết nếu có khái niệm chuyên môn. Trình bày thân thiện, trực quan."
        try:
            res = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            await update.message.reply_text(res.text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await update.message.reply_text(f"Lỗi phân tích: {e}")
    else:
        # Chat có ngữ cảnh
        try:
            response = chat_session.send_message(text)
            await update.message.reply_text(response.text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await update.message.reply_text("Lỗi chat: " + str(e))


# --- LỊCH TRÌNH VÀ TƯƠNG TÁC ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("read_"):
        date_str = query.data.split("_")[1]
        h = load_json(HISTORY_FILE, {})
        h[date_str] = True
        save_json(HISTORY_FILE, h)
        now_str = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime("%H:%M")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Đã đọc lúc {now_str}", callback_data="already_read")]]))

async def send_daily_news(context: ContextTypes.DEFAULT_TYPE):
    chat_id = TELEGRAM_CHAT_ID
    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    today_str = datetime.now(vn_tz).strftime("%Y-%m-%d")
    yesterday_str = (datetime.now(vn_tz) - timedelta(days=1)).strftime("%Y-%m-%d")
    
    h = load_json(HISTORY_FILE, {})
    missed_yesterday = h.get(yesterday_str, True) == False
    if today_str not in h:
        h[today_str] = False
        save_json(HISTORY_FILE, h)

    news_design = await fetch_news_logic(RSS_FEEDS_DESIGN, "design")
    news_ai = await fetch_news_logic(RSS_FEEDS_AI, "ai")
    
    header = f"📰 <b>BẢN TIN SÁNG - {today_str}</b>\n{'━' * 30}\n\n"
    if missed_yesterday:
        header = "⚠️ <i>Cảnh báo: Hôm qua bạn đã bỏ lỡ việc cập nhật kiến thức. Đừng để tụt hậu nhé!</i>\n\n" + header
        
    digest = header + news_design + "\n\n" + news_ai + "\n\n" + f"{'━' * 30}\n🤖 <i>Dịch & Tổng hợp bởi Super Bot</i>"
    
    keyboard = [[InlineKeyboardButton("👁️ Xác nhận đã đọc", callback_data=f"read_{today_str}")]]
    
    parts, text = [], digest
    while len(text) > 4000:
        split_pos = text.rfind("\n", 0, 4000)
        if split_pos == -1: split_pos = 4000
        parts.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    if text: parts.append(text)
    
    for i, part in enumerate(parts):
        is_last = (i == len(parts) - 1)
        await context.bot.send_message(chat_id=chat_id, text=part, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup(keyboard) if is_last else None)
        if not is_last: await asyncio.sleep(1)

async def auto_finance_report(context: ContextTypes.DEFAULT_TYPE):
    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    week_num = datetime.now(vn_tz).isocalendar()[1]
    finance_data = load_json(FINANCE_FILE, {"budget": BUDGET_PER_WEEK, "expenses": []})
    weekly_expenses = [item for item in finance_data["expenses"] if item.get("week") == week_num]
    total_week = sum(item["amount"] for item in weekly_expenses)
    remaining = finance_data["budget"] - total_week
    
    msg = f"📊 **TỔNG KẾT TÀI CHÍNH CUỐI TUẦN**\nNgân sách: {finance_data['budget']:,.0f} VNĐ\n\nTổng chi: **{total_week:,.0f} VNĐ**\nCòn lại: **{remaining:,.0f} VNĐ**\n\n"
    if remaining < 0: msg += "⚠️ Tuần này bạn đã lạm chi. Hãy điều chỉnh vào tuần sau nhé!"
    else: msg += "🎉 Chúc mừng bạn đã chi tiêu trong tầm kiểm soát!"
    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Đang cào tin Đa Kênh (Design & AI), vui lòng đợi...")
    asyncio.create_task(send_daily_news(context))

# --- DUMMY SERVER RENDER ---
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Super Bot is running!")
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), DummyHandler).serve_forever()


def main():
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    # Ép Gemini nhập vai Trợ lý
    chat_session.send_message("Bây giờ bạn là Siêu Trợ Lý cá nhân của tôi trên Telegram. Lĩnh vực cốt lõi: Design, Sách, AI, Tài chính. Hãy trả lời thân thiện, trực quan, dùng emoji và format rõ ràng bằng tiếng Việt.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("book", book_command))
    app.add_handler(CommandHandler("spend", spend_command))
    app.add_handler(CommandHandler("report", report_command))
    
    # Callbacks & Messages
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat))

    # Cron Jobs
    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    app.job_queue.run_daily(send_daily_news, time=time(hour=7, minute=0, tzinfo=vn_tz))
    app.job_queue.run_daily(auto_finance_report, time=time(hour=21, minute=0, tzinfo=vn_tz), days=(6,)) # Tối Chủ Nhật (Ngày thứ 6 trong isocalendar)

    logger.info("🤖 Super Bot đang khởi động...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
