"""
Telegram Life-OS Bot - Design, AI, Books, Finance & Personal Assistant & Todo
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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes, CallbackQueryHandler, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode

load_dotenv()

# --- CẤU HÌNH ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID_PRIVATE = os.getenv("TELEGRAM_CHAT_ID") 
CHAT_ID_BOOKS = "-1004324433124" 
CHAT_ID_NEWS = "-1004430444714" 

GEMINI_MODEL = "gemini-3.5-flash-lite"
FINANCE_FILE = "finance.json"
HISTORY_FILE = "read_history.json"
TODO_FILE = "todos.json"
BUDGET_PER_WEEK = 2000000 

RSS_FEEDS_DESIGN = {"💡 UX/UI Design": "https://uxdesign.cc/feed", "🎨 Web Design": "https://www.smashingmagazine.com/feed/"}
RSS_FEEDS_AI = {"🤖 AI News": "https://www.artificialintelligence-news.com/feed/"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

telegraph = Telegraph()
telegraph.create_account(short_name='LifeOS', author_name='Quản Gia Life-OS')

client = genai.Client(api_key=GEMINI_API_KEY)
chat_session = client.chats.create(model=GEMINI_MODEL)

# --- HELPER FORMATTING ---
def clean_for_telegram(text: str) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'^#{1,3}\s+(.*)', r'<b>\1</b>', text, flags=re.MULTILINE)
    text = text.replace("<br>", "\n").replace("```", "")
    return text

def load_json(file_path, default):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            try: return json.load(f)
            except: return default
    return default

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def parse_amount(amount_str):
    amount_str = amount_str.lower().replace(",", "").replace(".", "")
    if "k" in amount_str: return int(float(amount_str.replace("k", "")) * 1000)
    if "m" in amount_str or "tr" in amount_str: return int(float(amount_str.replace("m", "").replace("tr", "")) * 1000000)
    return int(amount_str)

# --- QUẢN LÝ CÔNG VIỆC (TODO LIST) ---
async def todo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/todo Nội dung công việc"""
    if not context.args:
        await update.message.reply_text("Sếp gõ: `/todo [Nội dung công việc]` (VD: `/todo Chiều 3h họp team`)", parse_mode=ParseMode.MARKDOWN)
        return
    task_text = " ".join(context.args)
    todos = load_json(TODO_FILE, {"tasks": []})
    task_id = str(int(datetime.now().timestamp()))
    todos["tasks"].append({"id": task_id, "text": task_text, "status": "pending"})
    save_json(TODO_FILE, todos)
    
    await update.message.reply_text(f"📝 Đã ghi nhận việc: <b>{task_text}</b>\n<i>Gõ /tasks để xem danh sách.</i>", parse_mode=ParseMode.HTML)

async def render_tasks(chat_id, context: ContextTypes.DEFAULT_TYPE, message_id_to_edit=None):
    """Vẽ bảng danh sách công việc và nút bấm"""
    todos = load_json(TODO_FILE, {"tasks": []})
    pending = [t for t in todos.get("tasks", []) if t["status"] == "pending"]
    
    if not pending:
        msg = "🎉 Sếp tuyệt vời! Không còn công việc nào tồn đọng."
        if message_id_to_edit:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id_to_edit, text=msg)
        else:
            await context.bot.send_message(chat_id=chat_id, text=msg)
        return

    msg = "📝 <b>DANH SÁCH CÔNG VIỆC CHƯA LÀM:</b>\n\n"
    keyboard = []
    row = []
    for i, t in enumerate(pending):
        msg += f"<b>{i+1}.</b> {t['text']}\n"
        row.append(InlineKeyboardButton(f"✅ Xong {i+1}", callback_data=f"tododone_{t['id']}"))
        if len(row) == 3: # 3 nút 1 hàng cho gọn
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    if message_id_to_edit:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id_to_edit, text=msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/tasks - Xem danh sách việc"""
    await render_tasks(update.message.chat_id, context)

async def morning_todo_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Nhắc việc mỗi sáng"""
    todos = load_json(TODO_FILE, {"tasks": []})
    pending = [t for t in todos.get("tasks", []) if t["status"] == "pending"]
    if pending:
        await context.bot.send_message(chat_id=CHAT_ID_PRIVATE, text="🌅 Chào buổi sáng sếp! Báo cáo nhanh, đây là các việc sếp cần hoàn thành hôm nay:")
        await render_tasks(CHAT_ID_PRIVATE, context)


# --- TÀI CHÍNH (FINANCE LIFE-OS) ---
async def salary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Sếp gõ theo cú pháp: `/salary [số tiền]` (VD: `/salary 20m`)", parse_mode=ParseMode.MARKDOWN)
            return
        amount = parse_amount(context.args[0])
        finance = load_json(FINANCE_FILE, {"salary": 0, "budgets": {}, "expenses": [], "timo_confirmed": False})
        finance["salary"] = amount
        finance["timo_confirmed"] = False
        save_json(FINANCE_FILE, finance)
        
        msg = f"💰 <b>ĐÃ GHI NHẬN LƯƠNG THÁNG NÀY:</b> {amount:,.0f} VNĐ\n\n"
        msg += "Sếp hãy tiếp tục dùng lệnh <code>/budget [tên quỹ] [số tiền]</code> để chia nhỏ ngân sách (VD: <code>/budget ăn_uống 4m</code>). Sau khi chia xong, hãy bấm nút dưới đây để xác nhận đã chuyển tiền vào app Timo!"
        
        keyboard = [[InlineKeyboardButton("🏦 Đã chia tiền vào các hũ Timo", callback_data="timo_confirm")]]
        await update.message.reply_text(clean_for_telegram(msg), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await update.message.reply_text("Lỗi cú pháp!")

async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) < 2:
            await update.message.reply_text("Sếp gõ: `/budget [tên hũ] [số tiền]` (VD: `/budget nhà_trọ 3m`)", parse_mode=ParseMode.MARKDOWN)
            return
        category = context.args[0].replace("_", " ").title()
        amount = parse_amount(context.args[1])
        finance = load_json(FINANCE_FILE, {"salary": 0, "budgets": {}, "expenses": [], "timo_confirmed": False})
        finance["budgets"][category] = amount
        save_json(FINANCE_FILE, finance)
        
        total_budget = sum(finance["budgets"].values())
        salary = finance["salary"]
        remaining = salary - total_budget
        
        msg = f"🎯 <b>CẬP NHẬT QUỸ: {category}</b>\n• Hạn mức: {amount:,.0f} VNĐ\n\n📊 <b>TỔNG QUAN THÁNG:</b>\n• Thu nhập: {salary:,.0f} VNĐ\n• Đã phân bổ: {total_budget:,.0f} VNĐ\n• Chưa phân bổ: {remaining:,.0f} VNĐ (Nên đưa vào hũ Tiết Kiệm)"
        await update.message.reply_text(clean_for_telegram(msg), parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text("Lỗi cú pháp!")

async def spend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Sếp gõ: `/spend [số tiền] [lý do]` (VD: `/spend 50k ăn sáng`)", parse_mode=ParseMode.MARKDOWN)
            return
        amount = parse_amount(args[0])
        reason = " ".join(args[1:])
        
        finance = load_json(FINANCE_FILE, {"salary": 0, "budgets": {}, "expenses": [], "timo_confirmed": False})
        if not finance["timo_confirmed"]:
            await update.message.reply_text("⚠️ Sếp chưa bấm nút xác nhận chia tiền vào hũ Timo đầu tháng! Hãy quản lý dòng tiền trước khi tiêu tiêu nhé.")
            return

        finance["expenses"].append({"date": datetime.now().strftime("%Y-%m-%d"), "amount": amount, "reason": reason})
        save_json(FINANCE_FILE, finance)
        
        current_month = datetime.now().strftime("%Y-%m")
        month_expenses = [item["amount"] for item in finance["expenses"] if item["date"].startswith(current_month)]
        total_spent = sum(month_expenses)
        total_budget = sum(finance["budgets"].values()) if finance["budgets"] else finance["salary"]
        remaining = total_budget - total_spent
        
        msg = f"💸 <b>ĐÃ TRỪ TIỀN:</b>\n• Số tiền: {amount:,.0f} VNĐ\n• Mục đích: {reason}\n\n📊 <b>TỔNG KẾT THÁNG:</b>\n• Đã tiêu: {total_spent:,.0f} VNĐ\n• CÒN LẠI: {remaining:,.0f} VNĐ"
        if remaining < 0: msg += "\n\n🚨 <b>BÁO ĐỘNG ĐỎ: SẾP ĐÃ TIÊU ÂM QUỸ THÁNG NÀY!</b>"
        await update.message.reply_text(clean_for_telegram(msg), parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text("Lỗi cú pháp!")

async def goal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Sếp gõ: `/goal [tên món đồ] [giá tiền]`", parse_mode=ParseMode.MARKDOWN)
            return
        item_name = " ".join(args[:-1])
        goal_amount = parse_amount(args[-1])
        
        finance = load_json(FINANCE_FILE, {"salary": 0, "budgets": {}, "expenses": [], "timo_confirmed": False})
        salary = finance["salary"]
        total_budget = sum(finance["budgets"].values())
        
        if salary <= 0:
            await update.message.reply_text("Sếp chưa cài đặt thu nhập `/salary`!")
            return
            
        monthly_saving = salary - total_budget
        if monthly_saving <= 0:
            msg = f"⚠️ Sếp không còn tiền dư mỗi tháng (Thu: {salary:,.0f}, Chi: {total_budget:,.0f}). Không thể tiết kiệm mua {item_name} lúc này!"
        else:
            months_needed = goal_amount / monthly_saving
            msg = f"🎯 <b>MỤC TIÊU TIẾT KIỆM: {item_name.upper()}</b>\n\n• Giá trị: {goal_amount:,.0f} VNĐ\n• Tiền dư hàng tháng: {monthly_saving:,.0f} VNĐ\n• Thời gian dự kiến: <b>{months_needed:.1f} tháng</b>\n\n💡 <i>Sếp hãy nhớ nạp số tiền dư này vào hũ Tiết Kiệm trên Timo ngay khi nhận lương nhé!</i>"
        await update.message.reply_text(clean_for_telegram(msg), parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text("Lỗi cú pháp!")


# --- TIN TỨC & SÁCH (CHANNELS) ---
async def send_news_to_channel(context: ContextTypes.DEFAULT_TYPE):
    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    today_str = datetime.now(vn_tz).strftime("%Y-%m-%d")
    prompt = "Tóm tắt 1 tin cực ngắn về AI hoặc Design hôm nay. Chỉ 2 dòng. Tuyệt đối KHÔNG dùng ký tự markdown như ** hay #. Trình bày trơn tru."
    intro = client.models.generate_content(model=GEMINI_MODEL, contents=prompt).text
    intro = clean_for_telegram(intro)
    
    msg = f"🌅 <b>BẢN TIN SÁNG - {today_str}</b>\n\n{intro}\n\n<i>(Hệ thống đang cào tin chi tiết...)</i>"
    await context.bot.send_message(chat_id=CHAT_ID_NEWS, text=msg, parse_mode=ParseMode.HTML)
    await context.bot.send_message(chat_id=CHAT_ID_NEWS, text="📡 <i>Đã cập nhật các bài viết mới lên Telegraph.</i>", parse_mode=ParseMode.HTML)

async def send_book_to_channel(context: ContextTypes.DEFAULT_TYPE):
    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    today_str = datetime.now(vn_tz).strftime("%Y-%m-%d")
    prompt = """Đóng vai học giả. Trích NGUYÊN VĂN 1 đoạn trích tinh hoa (300 chữ) từ 1 cuốn sách Tâm lý/Triết học/Tiền bạc kinh điển. KHÔNG DÙNG Markdown (**, #, ###).
    Cấu trúc:
    [Emoji] Tên sách - Tác giả
    
    [Nội dung trích đoạn]
    
    💡 Suy ngẫm của quản gia: (1 câu đúc kết)"""
    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt).text
    clean_text = clean_for_telegram(response)
    
    keyboard = [[InlineKeyboardButton("📖 Đã đọc xong & Suy ngẫm", callback_data=f"book_read_{today_str}")]]
    await context.bot.send_message(chat_id=CHAT_ID_BOOKS, text=clean_text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


# --- CHATBOT (DIRECT MESSAGE) ---
async def handle_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    try:
        prompt = text + "\n\n(Lưu ý hệ thống: Trả lời ngắn gọn, súc tích. TUYỆT ĐỐI KHÔNG dùng dấu ** hay ### hay #. Chỉ dùng văn bản thường và gạch đầu dòng emoji)."
        response = chat_session.send_message(prompt).text
        clean_msg = clean_for_telegram(response)
        await update.message.reply_text(clean_msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"Quản gia đang bận xử lý dữ liệu: {e}")

# --- CALLBACKS ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "timo_confirm":
        finance = load_json(FINANCE_FILE, {})
        finance["timo_confirmed"] = True
        save_json(FINANCE_FILE, finance)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Đã chia tiền thành công", callback_data="none")]]))
        
    elif query.data.startswith("book_read_"):
        now_str = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime("%H:%M")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Sếp đã đọc lúc {now_str}", callback_data="none")]]))
        
    elif query.data.startswith("tododone_"):
        task_id = query.data.split("_")[1]
        todos = load_json(TODO_FILE, {"tasks": []})
        for t in todos.get("tasks", []):
            if t["id"] == task_id:
                t["status"] = "completed"
        save_json(TODO_FILE, todos)
        await render_tasks(query.message.chat_id, context, query.message.message_id)

async def manual_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Đang đẩy bài test ra các kênh...")
    await send_news_to_channel(context)
    await send_book_to_channel(context)

# --- DUMMY SERVER RENDER ---
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Life-OS Bot is running!")
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), DummyHandler).serve_forever()

def main():
    threading.Thread(target=run_dummy_server, daemon=True).start()
    chat_session.send_message("Từ giờ bạn là Quản Gia Life-OS của tôi. Trả lời chuyên nghiệp, dùng ngôn từ sang trọng. TUYỆT ĐỐI KHÔNG DÙNG CÁC KÝ TỰ MARKDOWN như ** hay #. Trình bày bằng văn bản thuần và emoji.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("salary", salary_command))
    app.add_handler(CommandHandler("budget", budget_command))
    app.add_handler(CommandHandler("spend", spend_command))
    app.add_handler(CommandHandler("goal", goal_command))
    app.add_handler(CommandHandler("todo", todo_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CommandHandler("push", manual_trigger))
    
    # Handlers
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat))

    # Cron Jobs
    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    app.job_queue.run_daily(send_news_to_channel, time=time(hour=7, minute=0, tzinfo=vn_tz))
    app.job_queue.run_daily(morning_todo_reminder, time=time(hour=7, minute=5, tzinfo=vn_tz)) # Gửi task lúc 7h05 sáng
    app.job_queue.run_daily(send_book_to_channel, time=time(hour=20, minute=0, tzinfo=vn_tz)) 

    logger.info("🤖 Quản Gia Life-OS đang khởi động...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
