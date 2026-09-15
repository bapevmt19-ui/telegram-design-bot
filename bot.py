"""
Telegram Life-OS Bot - Design, AI, Books, Finance, Todo, Voice & Chart
"""
import os
import json
import logging
import asyncio
import re
from datetime import datetime, time
import pytz
import matplotlib
matplotlib.use('Agg') # Cho phép vẽ biểu đồ trên server không có màn hình
import matplotlib.pyplot as plt

from dotenv import load_dotenv
import feedparser
import trafilatura
from telegraph import Telegraph
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
TODO_FILE = "todos.json"
IDEAS_FILE = "ideas.json"

RSS_FEEDS_DESIGN = {"💡 UX/UI Design": "https://uxdesign.cc/feed", "🎨 Web Design": "https://www.smashingmagazine.com/feed/"}
RSS_FEEDS_AI = {"🤖 AI News": "https://www.artificialintelligence-news.com/feed/"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

telegraph = Telegraph()
telegraph.create_account(short_name='LifeOS', author_name='Quản Gia Life-OS')

client = genai.Client(api_key=GEMINI_API_KEY)
chat_session = client.chats.create(
    model=GEMINI_MODEL,
    config=dict(system_instruction="Từ giờ bạn là Quản Gia Life-OS của tôi. Trả lời chuyên nghiệp, dùng ngôn từ sang trọng. TUYỆT ĐỐI KHÔNG DÙNG CÁC KÝ TỰ MARKDOWN như ** hay #. Trình bày bằng văn bản thuần và emoji.")
)

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
    amount_str = amount_str.lower().replace(",", "").replace(".", "").strip()
    if "k" in amount_str: return int(float(amount_str.replace("k", "")) * 1000)
    if "m" in amount_str or "tr" in amount_str: return int(float(amount_str.replace("m", "").replace("tr", "")) * 1000000)
    return int(amount_str)

# --- CORE LOGIC (Dùng chung cho Lệnh gõ và Giọng nói) ---
async def execute_spend(chat_id, context, amount, reason):
    finance = load_json(FINANCE_FILE, {"salary": 0, "budgets": {}, "expenses": [], "timo_confirmed": False})
    if not finance["timo_confirmed"]:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Sếp chưa bấm nút xác nhận chia tiền vào hũ Timo đầu tháng!")
        return

    finance["expenses"].append({"date": datetime.now().strftime("%Y-%m-%d"), "amount": amount, "reason": reason})
    save_json(FINANCE_FILE, finance)
    
    current_month = datetime.now().strftime("%Y-%m")
    month_expenses = [item["amount"] for item in finance["expenses"] if item["date"].startswith(current_month)]
    total_spent = sum(month_expenses)
    total_budget = sum(finance["budgets"].values()) if finance["budgets"] else finance["salary"]
    remaining = total_budget - total_spent
    
    msg = f"💸 <b>ĐÃ TRỪ TIỀN:</b>\n• Số tiền: {amount:,.0f} VNĐ\n• Mục đích: {reason}\n\n📊 <b>CÒN LẠI THÁNG NÀY:</b> {remaining:,.0f} VNĐ"
    if remaining < 0: msg += "\n\n🚨 <b>BÁO ĐỘNG ĐỎ: SẾP ĐÃ TIÊU ÂM QUỸ THÁNG NÀY!</b>"
    await context.bot.send_message(chat_id=chat_id, text=clean_for_telegram(msg), parse_mode=ParseMode.HTML)

async def execute_todo(chat_id, context, task_text):
    todos = load_json(TODO_FILE, {"tasks": []})
    task_id = str(int(datetime.now().timestamp()))
    todos["tasks"].append({"id": task_id, "text": task_text, "status": "pending"})
    save_json(TODO_FILE, todos)
    await context.bot.send_message(chat_id=chat_id, text=f"📝 Đã ghi nhận việc: <b>{task_text}</b>", parse_mode=ParseMode.HTML)

async def execute_idea(chat_id, context, idea_text):
    ideas = load_json(IDEAS_FILE, {"ideas": []})
    ideas["ideas"].append({"date": datetime.now().strftime("%Y-%m-%d"), "text": idea_text})
    save_json(IDEAS_FILE, ideas)
    await context.bot.send_message(chat_id=chat_id, text="💡 <b>Đã cất ý tưởng này vào Bộ Não Thứ 2!</b>\n<i>(Sếp có thể hỏi lại bất cứ lúc nào)</i>", parse_mode=ParseMode.HTML)

# --- QUẢN LÝ TÀI CHÍNH ---
async def salary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = parse_amount(context.args[0])
        finance = load_json(FINANCE_FILE, {"salary": 0, "budgets": {}, "expenses": [], "timo_confirmed": False})
        finance["salary"] = amount
        finance["timo_confirmed"] = False
        save_json(FINANCE_FILE, finance)
        msg = f"💰 <b>ĐÃ GHI NHẬN LƯƠNG:</b> {amount:,.0f} VNĐ\nSếp hãy chia /budget và bấm nút dưới đây để xác nhận đã thao tác trên app Timo!"
        keyboard = [[InlineKeyboardButton("🏦 Đã chia tiền vào các hũ Timo", callback_data="timo_confirm")]]
        await update.message.reply_text(clean_for_telegram(msg), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await update.message.reply_text("Lỗi cú pháp! Gõ: /salary [số tiền]")

async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        category = context.args[0].replace("_", " ").title()
        amount = parse_amount(context.args[1])
        finance = load_json(FINANCE_FILE, {"salary": 0, "budgets": {}, "expenses": [], "timo_confirmed": False})
        finance["budgets"][category] = amount
        save_json(FINANCE_FILE, finance)
        await update.message.reply_text(f"🎯 <b>CẬP NHẬT QUỸ: {category}</b>\n• Hạn mức: {amount:,.0f} VNĐ", parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text("Lỗi cú pháp! Gõ: /budget [tên hũ] [số tiền]")

async def spend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = parse_amount(context.args[0])
        reason = " ".join(context.args[1:])
        await execute_spend(update.message.chat_id, context, amount, reason)
    except Exception:
        await update.message.reply_text("Lỗi cú pháp! Gõ: /spend [số tiền] [lý do]")

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vẽ biểu đồ chi tiêu"""
    finance = load_json(FINANCE_FILE, {"salary": 0, "budgets": {}, "expenses": [], "timo_confirmed": False})
    current_month = datetime.now().strftime("%Y-%m")
    month_expenses = [item for item in finance.get("expenses", []) if item["date"].startswith(current_month)]
    
    if not month_expenses:
        await update.message.reply_text("Tháng này sếp chưa tiêu đồng nào cả!")
        return
        
    categories = {}
    for exp in month_expenses:
        # Nhóm theo từ đầu tiên (Ví dụ: "Ăn sáng" -> "Ăn")
        cat = exp['reason'].split()[0].title()
        categories[cat] = categories.get(cat, 0) + exp['amount']
        
    labels = list(categories.keys())
    sizes = list(categories.values())
    
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, colors=plt.cm.Paired.colors)
    ax.axis('equal')
    
    chart_path = "chart.png"
    plt.title(f"Phân bổ chi tiêu tháng {current_month}")
    plt.savefig(chart_path, bbox_inches='tight')
    plt.close()
    
    await update.message.reply_photo(photo=open(chart_path, 'rb'), caption=f"📊 Báo cáo phân bổ chi tiêu tháng {current_month}")

async def goal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        item_name = " ".join(context.args[:-1])
        goal_amount = parse_amount(context.args[-1])
        finance = load_json(FINANCE_FILE, {"salary": 0, "budgets": {}, "expenses": [], "timo_confirmed": False})
        salary = finance.get("salary", 0)
        total_budget = sum(finance.get("budgets", {}).values())
        monthly_saving = salary - total_budget
        
        if monthly_saving <= 0:
            msg = f"⚠️ Sếp không còn tiền dư mỗi tháng (Thu: {salary:,.0f}, Chi: {total_budget:,.0f}). Không thể tiết kiệm!"
        else:
            months_needed = goal_amount / monthly_saving
            msg = f"🎯 <b>MỤC TIÊU: {item_name.upper()}</b>\n• Thời gian dự kiến: <b>{months_needed:.1f} tháng</b>"
        await update.message.reply_text(clean_for_telegram(msg), parse_mode=ParseMode.HTML)
    except Exception:
        pass

# --- TODO LIST ---
async def todo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task_text = " ".join(context.args)
    await execute_todo(update.message.chat_id, context, task_text)

async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    todos = load_json(TODO_FILE, {"tasks": []})
    pending = [t for t in todos.get("tasks", []) if t["status"] == "pending"]
    if not pending:
        await update.message.reply_text("🎉 Không còn công việc nào tồn đọng.")
        return
    msg = "📝 <b>DANH SÁCH CÔNG VIỆC CHƯA LÀM:</b>\n\n"
    keyboard = []
    row = []
    for i, t in enumerate(pending):
        msg += f"<b>{i+1}.</b> {t['text']}\n"
        row.append(InlineKeyboardButton(f"✅ Xong {i+1}", callback_data=f"tododone_{t['id']}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

# --- VOICE OS & CHATBOT ---
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý giọng nói bằng Gemini"""
    status_msg = await update.message.reply_text("🎙️ <i>Đang nghe và phân tích giọng nói...</i>", parse_mode=ParseMode.HTML)
    try:
        voice_file = await context.bot.get_file(update.message.voice.file_id)
        file_path = "temp_voice.ogg"
        await voice_file.download_to_drive(file_path)
        
        audio = client.files.upload(file=file_path)
        prompt = """Nghe file âm thanh và phân loại ý định của sếp. Chỉ trả về ĐÚNG 1 DÒNG DUY NHẤT theo chuẩn sau:
        1. Tiêu tiền: SPEND|<số_tiền_bằng_số>|<lý_do> (VD: SPEND|50000|ăn phở)
        2. Nhắc việc: TODO|<nội_dung> (VD: TODO|chiều 3h họp team)
        3. Lưu ý tưởng: IDEA|<nội_dung_ý_tưởng>
        4. Hỏi đáp: CHAT|<câu_hỏi_của_người_dùng>"""
        
        res = client.models.generate_content(model="gemini-1.5-flash", contents=[audio, prompt]).text.strip()
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=status_msg.message_id)
        
        if res.startswith("SPEND|"):
            parts = res.split("|", 2)
            await execute_spend(update.message.chat_id, context, parse_amount(parts[1]), parts[2])
        elif res.startswith("TODO|"):
            await execute_todo(update.message.chat_id, context, res.split("|", 1)[1])
        elif res.startswith("IDEA|"):
            await execute_idea(update.message.chat_id, context, res.split("|", 1)[1])
        elif res.startswith("CHAT|"):
            chat_text = res.split("|", 1)[1]
            await handle_chat_text(update, context, chat_text)
        else:
            await update.message.reply_text(f"Không nhận diện được lệnh: {res}")
    except Exception as e:
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=status_msg.message_id)
        await update.message.reply_text(f"⚠️ Lỗi nhận diện giọng nói: {e}")

async def handle_chat_text(update, context, text):
    if "#idea" in text.lower():
        await execute_idea(update.message.chat_id, context, text.lower().replace("#idea", "").strip())
        return

    try:
        ideas = load_json(IDEAS_FILE, {"ideas": []})
        recent_ideas = "\n".join([f"- {i['text']}" for i in ideas.get("ideas", [])[-5:]])
        ctx = f"GHI CHÚ HỆ THỐNG: Dưới đây là các ý tưởng sếp đã lưu gần đây:\n{recent_ideas}\n\n" if recent_ideas else ""
        
        prompt = ctx + text + "\n\n(Lưu ý: Trả lời ngắn gọn, TUYỆT ĐỐI KHÔNG dùng dấu ** hay ### hay #. Chỉ dùng văn bản thuần và emoji)."
        response = chat_session.send_message(prompt).text
        await update.message.reply_text(clean_for_telegram(response), parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"Lỗi: {e}")

async def handle_chat_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_chat_text(update, context, update.message.text)


# --- TIN TỨC & SÁCH (CHANNELS) ---
async def send_news_to_channel(context: ContextTypes.DEFAULT_TYPE):
    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    today_str = datetime.now(vn_tz).strftime("%Y-%m-%d")
    prompt = "Tóm tắt 1 tin cực ngắn về AI hoặc Design hôm nay. Chỉ 2 dòng. Tuyệt đối KHÔNG dùng ký tự markdown như ** hay #."
    try: intro = client.models.generate_content(model=GEMINI_MODEL, contents=prompt).text
    except: intro = "Chúc sếp một ngày mới tràn đầy năng lượng!"
    
    msg = f"🌅 <b>BẢN TIN SÁNG - {today_str}</b>\n\n{clean_for_telegram(intro)}\n\n<i>(Hệ thống đang cào và dịch tin chi tiết, sếp đợi 1 phút nhé...)</i>"
    await context.bot.send_message(chat_id=CHAT_ID_NEWS, text=msg, parse_mode=ParseMode.HTML)
    
    articles_sent = 0
    try:
        for title, url, tag in [("💡 UX/UI Design", RSS_FEEDS_DESIGN["💡 UX/UI Design"], "🎨 Design"), ("🤖 AI News", RSS_FEEDS_AI["🤖 AI News"], "🤖 AI")]:
            feed = feedparser.parse(url)
            if feed.entries:
                entry = feed.entries[0]
                downloaded = trafilatura.fetch_url(entry.link)
                if downloaded:
                    text_content = trafilatura.extract(downloaded)
                    if text_content:
                        trans_prompt = f"Dịch bài viết sang tiếng Việt. Trả về định dạng HTML cơ bản (chỉ dùng <h3>, <p>, <ul>, <li>, <b>, <i>). Nguồn:\n\n{text_content[:3000]}"
                        trans_html = client.models.generate_content(model=GEMINI_MODEL, contents=trans_prompt).text
                        trans_html = trans_html.replace("```html", "").replace("```", "").replace("<h1>", "<h3>").replace("<h2>", "<h3>")
                        response = telegraph.create_page(title=entry.title[:100], html_content=trans_html + f"<br><br><a href='{entry.link}'>Link bài viết gốc</a>")
                        await context.bot.send_message(chat_id=CHAT_ID_NEWS, text=f"{tag}: <a href='{response['url']}'>{entry.title}</a>", parse_mode=ParseMode.HTML)
                        articles_sent += 1
    except Exception as e: logger.error(f"Lỗi cào tin: {e}")
        
    if articles_sent > 0:
        keyboard = [[InlineKeyboardButton("👁️ Xác nhận đã đọc xong tin", callback_data=f"read_{today_str}")]]
        await context.bot.send_message(chat_id=CHAT_ID_NEWS, text="📡 <i>Đã dịch và cập nhật xong bản tin hôm nay!</i>", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

async def send_book_to_channel(context: ContextTypes.DEFAULT_TYPE):
    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    today_str = datetime.now(vn_tz).strftime("%Y-%m-%d")
    prompt = """Trích NGUYÊN VĂN 1 đoạn trích tinh hoa (300 chữ) từ 1 cuốn sách Tâm lý/Tiền bạc kinh điển. KHÔNG DÙNG Markdown (**, #, ###).
    [Emoji] Tên sách - Tác giả
    [Nội dung trích đoạn]
    💡 Suy ngẫm của quản gia: (1 câu đúc kết)"""
    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt).text
    keyboard = [[InlineKeyboardButton("📖 Đã đọc xong & Suy ngẫm", callback_data=f"book_read_{today_str}")]]
    await context.bot.send_message(chat_id=CHAT_ID_BOOKS, text=clean_for_telegram(response), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

async def manual_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Đang đẩy bài test ra các kênh...")
    await send_news_to_channel(context)
    await send_book_to_channel(context)

# --- DUMMY SERVER RENDER ---
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        msg = b"Life-OS Bot is running!"
        self.send_response(200)
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        self.wfile.write(msg)
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), DummyHandler).serve_forever()

# --- MAIN ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "timo_confirm":
        finance = load_json(FINANCE_FILE, {})
        finance["timo_confirmed"] = True
        save_json(FINANCE_FILE, finance)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Đã chia tiền thành công", callback_data="none")]]))
    elif query.data.startswith("book_read_"):
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Sếp đã đọc lúc {datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime('%H:%M')}", callback_data="none")]]))
    elif query.data.startswith("read_"):
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Sếp đã nắm bắt tin tức lúc {datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime('%H:%M')}", callback_data="none")]]))
    elif query.data.startswith("tododone_"):
        task_id = query.data.split("_")[1]
        todos = load_json(TODO_FILE, {"tasks": []})
        for t in todos.get("tasks", []):
            if t["id"] == task_id: t["status"] = "completed"
        save_json(TODO_FILE, todos)
        await tasks_command(update, context) # Re-render (simplified)

def main():
    threading.Thread(target=run_dummy_server, daemon=True).start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("salary", salary_command))
    app.add_handler(CommandHandler("budget", budget_command))
    app.add_handler(CommandHandler("spend", spend_command))
    app.add_handler(CommandHandler("goal", goal_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("todo", todo_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CommandHandler("push", manual_trigger))
    
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat_route))

    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    app.job_queue.run_daily(send_news_to_channel, time=time(hour=7, minute=0, tzinfo=vn_tz))
    app.job_queue.run_daily(send_book_to_channel, time=time(hour=20, minute=0, tzinfo=vn_tz)) 

    import time as sys_time
    logger.info("🤖 Quản Gia Life-OS đang khởi động...")
    
    # Loop chống lỗi Conflict khi deploy cuốn chiếu
    while True:
        try:
            app.run_polling(allowed_updates=Update.ALL_TYPES)
            break
        except Exception as e:
            logger.error(f"Lỗi Polling (chờ 5s thử lại): {e}")
            sys_time.sleep(5)

if __name__ == "__main__":
    main()
