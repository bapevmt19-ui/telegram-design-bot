"""
Telegram Life-OS Bot - Design, AI, Books, Finance, Todo, Voice & Chart
"""
import os
import json
import logging
import asyncio
import re
from datetime import datetime, time, timedelta
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

GEMINI_MODEL = "gemini-flash-latest"
FINANCE_FILE = "finance.json"
TODO_FILE = "todos.json"
IDEAS_FILE = "ideas.json"
REMINDERS_FILE = "reminders.json"
HEALTH_FILE = "health.json"
NUTRITION_FILE = "nutrition.json"
MEMORY_FILE = "memory.json"

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

    # Auto-categorize using Gemini based on existing budgets
    category = "Khac"
    if finance.get("budgets"):
        budget_keys = list(finance["budgets"].keys())
        prompt = f"""Phân loại chi tiêu: "{reason}". 
        Hãy chọn 1 danh mục phù hợp nhất từ danh sách sau: {', '.join(budget_keys)}. 
        Chỉ trả về ĐÚNG 1 từ là tên danh mục, không giải thích. Nếu không khớp cái nào, trả về Khac."""
        try:
            category = client.models.generate_content(model=GEMINI_MODEL, contents=prompt).text.strip()
            if category not in budget_keys:
                category = "Khac"
        except:
            category = "Khac"
            
    finance["expenses"].append({
        "date": datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime("%Y-%m-%d"), 
        "amount": amount, 
        "reason": reason,
        "category": category
    })
    save_json(FINANCE_FILE, finance)
    
    current_month = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime("%Y-%m")
    month_expenses = [item for item in finance["expenses"] if item["date"].startswith(current_month)]
    
    total_spent = sum(item["amount"] for item in month_expenses)
    total_budget = sum(finance["budgets"].values()) if finance["budgets"] else finance["salary"]
    global_remaining = total_budget - total_spent
    
    msg = f"💸 <b>ĐÃ TRỪ TIỀN:</b>\n▪️ Số tiền: {amount:,.0f} VNĐ\n▪️ Mục đích: {reason}\n▪️ Phân loại AI: <b>{category}</b>\n\n"
    
    # Check specific category budget
    if category != "Khac" and category in finance["budgets"]:
        cat_budget = finance["budgets"][category]
        cat_spent = sum(item["amount"] for item in month_expenses if item.get("category") == category)
        cat_remaining = cat_budget - cat_spent
        msg += f"📦 <b>Quỹ {category}:</b> Còn lại {cat_remaining:,.0f} / {cat_budget:,.0f} VNĐ\n"
        if cat_remaining < 0:
            msg += f"🚨 <b>CẢNH BÁO: SẾP ĐÃ TIÊU ÂM QUỸ {category.upper()}!</b>\n\n"

    msg += f"💰 <b>TỔNG TIỀN CÒN LẠI THÁNG NÀY:</b> {global_remaining:,.0f} VNĐ"
    if global_remaining < 0: 
        msg += "\n\n💀 <b>BÁO ĐỘNG ĐỎ: SẾP ĐÃ TIÊU ÂM TOÀN BỘ NGÂN SÁCH!</b>"
        
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
        # Nhóm theo phân loại AI, nếu không có thì lấy từ đầu tiên
        cat = exp.get('category', exp['reason'].split()[0].title())
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

# --- HỆ THỐNG BÁO THỨC / NHẮC NHỞ ---
async def send_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    task_id, chat_id, task_text = data["id"], data["chat_id"], data["text"]
    
    reminders = load_json(REMINDERS_FILE, {"reminders": []})
    for r in reminders["reminders"]:
        if r["id"] == task_id: r["status"] = "done"
    save_json(REMINDERS_FILE, reminders)
    
    await context.bot.send_message(chat_id=chat_id, text=f"🔔 <b>BÁO THỨC / NHẮC NHỞ:</b>\nSếp ơi, đến giờ: <b>{task_text}</b>", parse_mode=ParseMode.HTML)

def add_reminder(job_queue, chat_id, remind_time: datetime, task_text: str):
    task_id = str(int(datetime.now().timestamp() * 1000))
    reminders = load_json(REMINDERS_FILE, {"reminders": []})
    reminders["reminders"].append({
        "id": task_id, "chat_id": chat_id, "time": remind_time.strftime("%Y-%m-%d %H:%M"),
        "text": task_text, "status": "pending"
    })
    save_json(REMINDERS_FILE, reminders)
    job_queue.run_once(send_reminder_job, when=remind_time, data={"id": task_id, "chat_id": chat_id, "text": task_text})

def load_pending_reminders(job_queue):
    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    reminders = load_json(REMINDERS_FILE, {"reminders": []})
    now = datetime.now(vn_tz)
    for r in reminders["reminders"]:
        if r["status"] == "pending":
            try:
                r_time = vn_tz.localize(datetime.strptime(r["time"], "%Y-%m-%d %H:%M"))
                if r_time > now:
                    job_queue.run_once(send_reminder_job, when=r_time, data={"id": r["id"], "chat_id": r["chat_id"], "text": r["text"]})
                else:
                    r["status"] = "missed"
            except Exception: pass
    save_json(REMINDERS_FILE, reminders)

async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        time_str = context.args[0]
        task_text = " ".join(context.args[1:])
        vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        now = datetime.now(vn_tz)
        
        hour, minute = map(int, time_str.split(":"))
        remind_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if remind_time < now: remind_time += timedelta(days=1)
            
        add_reminder(context.application.job_queue, update.message.chat_id, remind_time, task_text)
        await update.message.reply_text(f"⏰ Đã hẹn giờ báo thức lúc <b>{remind_time.strftime('%H:%M %d/%m')}</b> cho việc:\n{task_text}", parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text("Lỗi cú pháp! Gõ: /remind HH:MM [Nội dung] (VD: /remind 15:30 Họp team)")

# --- HEALTH-OS (DINH DƯỠNG & SỨC KHOẺ) ---
async def healthsetup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("💪 Sếp vui lòng nhập thông tin. VD:\n`/healthsetup Tôi 25 tuổi, nam, cao 1m70, nặng 65kg, dân văn phòng ít vận động, muốn giảm mỡ`", parse_mode=ParseMode.MARKDOWN)
        return
    
    status_msg = await update.message.reply_text("⚙️ <i>Đang tính toán phác đồ dinh dưỡng chuẩn y khoa...</i>", parse_mode=ParseMode.HTML)
    prompt = f"""Trích xuất thông tin sức khoẻ từ câu sau: "{text}".
    Trả về ĐÚNG định dạng JSON (không markdown, không giải thích):
    {{"age": 25, "gender": "male", "height_cm": 170, "weight_kg": 65, "activity_level": 1.2, "goal": "loss"}}
    Ghi chú activity_level: 1.2 (ít vận động), 1.375 (nhẹ), 1.55 (vừa), 1.725 (nặng), 1.9 (rất nặng). Goal: loss (giảm), gain (tăng), maintain (giữ)."""
    
    try:
        res = client.models.generate_content(model=GEMINI_MODEL, contents=prompt).text
        data = json.loads(res.replace("```json", "").replace("```", "").strip())
        
        if data['gender'] == 'male':
            bmr = (10 * data['weight_kg']) + (6.25 * data['height_cm']) - (5 * data['age']) + 5
        else:
            bmr = (10 * data['weight_kg']) + (6.25 * data['height_cm']) - (5 * data['age']) - 161
            
        tdee = bmr * data['activity_level']
        target_calories = tdee
        if data['goal'] == 'loss': target_calories -= 500
        elif data['goal'] == 'gain': target_calories += 500
        
        protein = (target_calories * 0.4) / 4
        carb = (target_calories * 0.3) / 4
        fat = (target_calories * 0.3) / 9
        
        profile = {
            "age": data['age'], "height_cm": data['height_cm'], "weight_kg": data['weight_kg'],
            "tdee": int(tdee), "target_calories": int(target_calories),
            "macros": {"protein": int(protein), "carb": int(carb), "fat": int(fat)}
        }
        save_json(HEALTH_FILE, profile)
        
        msg = f"📊 <b>HỒ SƠ DINH DƯỠNG ĐÃ THIẾT LẬP</b>\n\n"
        msg += f"🔥 <b>TDEE (Calo giữ cân):</b> {int(tdee)} kcal/ngày\n"
        msg += f"🎯 <b>Calo mục tiêu ({data['goal']}):</b> {int(target_calories)} kcal/ngày\n\n"
        msg += f"🥩 <b>Protein (Cơ bắp):</b> {int(protein)}g\n"
        msg += f"🍚 <b>Carb (Năng lượng):</b> {int(carb)}g\n"
        msg += f"🥑 <b>Fat (Nội tiết):</b> {int(fat)}g\n\n"
        msg += f"<i>(Giờ sếp cứ chụp ảnh bữa ăn hoặc cái cân gửi vào đây, em sẽ tự trừ vào quỹ Calo hôm nay nhé!)</i>"
        
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=status_msg.message_id)
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=status_msg.message_id)
        await update.message.reply_text(f"Lỗi: Không nhận diện được dữ liệu. Sếp nhập lại rõ hơn nhé! ({e})")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("👁️ <i>Đang soi hình ảnh...</i>", parse_mode=ParseMode.HTML)
    try:
        photo_file = await update.message.photo[-1].get_file()
        file_path = "temp_photo.jpg"
        await photo_file.download_to_drive(file_path)
        
        health = load_json(HEALTH_FILE, {})
        target = health.get("target_calories", 2000)
        
        # Lấy Core Memory để prompt phân tích chung sắc bén hơn
        memory = load_json(MEMORY_FILE, {"rules": []})
        memory_ctx = "\n".join([f"- {r}" for r in memory["rules"]]) if memory.get("rules") else "Không có."
        
        # Check if caption exists to give context to screenshot
        caption = update.message.caption or ""
        
        img = client.files.upload(file=file_path)
        prompt = f"""Phân tích hình ảnh này. Hình ảnh có thể là 1 trong 2 loại:
        LOẠI 1: Ảnh đồ ăn/thức uống/cái cân. -> Bạn đóng vai chuyên gia dinh dưỡng, ước lượng calo.
        LOẠI 2: Ảnh chụp màn hình bài viết (Facebook, báo chí), biểu đồ, tài liệu, v.v. -> Bạn đóng vai Quân sư chiến lược. Đọc nội dung trong ảnh và phân tích sâu sắc, đa chiều (kết hợp với yêu cầu thêm của người dùng nếu có: '{caption}').
        
        TRẢ VỀ ĐÚNG ĐỊNH DẠNG JSON DUY NHẤT DƯỚI ĐÂY (không bọc trong thẻ markdown):
        {{
            "image_type": "food" hoặc "general",
            "food_data": {{
                "food_name": "Tên món", "calories": 500, "protein": 30, "carb": 40, "fat": 15, "advice": "Nhận xét 1 câu"
            }},
            "general_response": "Bài phân tích chi tiết, sâu sắc (dùng thẻ <b>, <i> chuẩn HTML, tuyệt đối không dùng markdown # hay **). Luôn tuân thủ luật bộ nhớ lõi: {memory_ctx}"
        }}
        Lưu ý: Nếu là LOẠI 2, hãy để food_data là null. Mục tiêu calo 1 ngày là {target} kcal."""
        
        import time as sys_time
        import random
        max_retries = 4
        res = None
        for attempt in range(max_retries):
            try:
                if attempt >= 2:
                    res = client.models.generate_content(model="gemini-flash-lite-latest", contents=[img, prompt]).text.strip()
                else:
                    res = client.models.generate_content(model=GEMINI_MODEL, contents=[img, prompt]).text.strip()
                break
            except Exception as api_e:
                if ("500" in str(api_e) or "503" in str(api_e) or "429" in str(api_e)) and attempt < max_retries - 1:
                    sleep_time = (2 ** attempt) + random.uniform(0, 1)
                    sys_time.sleep(sleep_time)
                else:
                    raise api_e
                    
        data = json.loads(res.replace("```json", "").replace("```", "").strip())
        
        if data.get("image_type") == "food" and data.get("food_data"):
            food = data["food_data"]
            vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
            today_str = datetime.now(vn_tz).strftime("%Y-%m-%d")
            nutri = load_json(NUTRITION_FILE, {})
            if today_str not in nutri:
                nutri[today_str] = {"consumed_calories": 0, "protein": 0, "carb": 0, "fat": 0, "logs": []}
                
            nutri[today_str]["consumed_calories"] += food["calories"]
            nutri[today_str]["protein"] += food["protein"]
            nutri[today_str]["carb"] += food["carb"]
            nutri[today_str]["fat"] += food["fat"]
            nutri[today_str]["logs"].append(f"{food['food_name']} ({food['calories']} kcal)")
            save_json(NUTRITION_FILE, nutri)
            
            remaining = target - nutri[today_str]["consumed_calories"]
            
            msg = f"🍽️ <b>{food['food_name'].upper()}</b>\n\n"
            msg += f"🔥 <b>Năng lượng:</b> {food['calories']} kcal\n"
            msg += f"💪 <b>P/C/F (g):</b> {food['protein']} / {food['carb']} / {food['fat']}\n\n"
            msg += f"💡 <i>{food['advice']}</i>\n\n"
            msg += f"📉 <b>Tổng đã nạp hôm nay:</b> {nutri[today_str]['consumed_calories']} / {target} kcal\n"
            msg += f"🎯 <b>Quỹ Calo còn lại:</b> {remaining} kcal"
            
            await context.bot.delete_message(chat_id=update.message.chat_id, message_id=status_msg.message_id)
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
            
        else:
            # General image
            await context.bot.delete_message(chat_id=update.message.chat_id, message_id=status_msg.message_id)
            await update.message.reply_text(clean_for_telegram(data.get("general_response", "Không thể trích xuất nội dung.")), parse_mode=ParseMode.HTML)
            
    except Exception as e:
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=status_msg.message_id)
        await update.message.reply_text(f"⚠️ Lỗi phân tích ảnh: {e}")

# --- VOICE OS & CHATBOT ---
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý giọng nói bằng Gemini"""
    status_msg = await update.message.reply_text("🎙️ <i>Đang nghe và phân tích giọng nói...</i>", parse_mode=ParseMode.HTML)
    try:
        voice_file = await context.bot.get_file(update.message.voice.file_id)
        file_path = "temp_voice.ogg"
        await voice_file.download_to_drive(file_path)
        
        vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        now_str = datetime.now(vn_tz).strftime("%Y-%m-%d %H:%M")
        
        audio = client.files.upload(file=file_path)
        prompt = f"""Bây giờ là: {now_str}.
        Nghe file âm thanh và phân loại ý định của sếp. Chỉ trả về ĐÚNG 1 DÒNG DUY NHẤT theo chuẩn sau:
        1. Tiêu tiền: SPEND|<số_tiền_bằng_số>|<lý_do> (VD: SPEND|50000|ăn phở)
        2. Nhắc việc To-do: TODO|<nội_dung> (VD: TODO|chiều 3h họp team)
        3. Hẹn giờ báo thức: REMIND|YYYY-MM-DD HH:MM|<nội_dung> (VD: REMIND|2026-09-15 15:30|Họp team)
        4. Lưu ý tưởng: IDEA|<nội_dung_ý_tưởng>
        5. Hỏi đáp: CHAT|<câu_hỏi_của_người_dùng>"""
        
        res = client.models.generate_content(model=GEMINI_MODEL, contents=[audio, prompt]).text.strip()
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=status_msg.message_id)
        
        if res.startswith("SPEND|"):
            parts = res.split("|", 2)
            await execute_spend(update.message.chat_id, context, parse_amount(parts[1]), parts[2])
        elif res.startswith("TODO|"):
            await execute_todo(update.message.chat_id, context, res.split("|", 1)[1])
        elif res.startswith("REMIND|"):
            parts = res.split("|", 2)
            r_time = vn_tz.localize(datetime.strptime(parts[1], "%Y-%m-%d %H:%M"))
            add_reminder(context.application.job_queue, update.message.chat_id, r_time, parts[2])
            await update.message.reply_text(f"⏰ Đã hẹn báo thức lúc <b>{r_time.strftime('%H:%M %d/%m')}</b> cho việc:\n{parts[2]}", parse_mode=ParseMode.HTML)
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

async def cook_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("🧑‍🍳 Sếp vui lòng nhập nguyên liệu hiện có. VD: `/cook 3 lạng thịt bò, cà chua, hành tây`", parse_mode=ParseMode.MARKDOWN)
        return
    
    status_msg = await update.message.reply_text("🧑‍🍳 <i>Đang lục lọi tủ lạnh và sáng tạo công thức...</i>", parse_mode=ParseMode.HTML)
    try:
        vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        today_str = datetime.now(vn_tz).strftime("%Y-%m-%d")
        health = load_json(HEALTH_FILE, {})
        nutri = load_json(NUTRITION_FILE, {}).get(today_str, {})
        
        target = health.get("target_calories", 2000)
        consumed = nutri.get("consumed_calories", 0)
        remaining = target - consumed
        
        prompt = f"""Đóng vai một Siêu đầu bếp và Chuyên gia dinh dưỡng. Người dùng đang có các nguyên liệu sau: "{text}".
        Quỹ Calo còn lại trong ngày của họ là: {remaining} kcal.
        Hãy sáng tạo ra 1 món ăn NGON, dễ làm, và TỐI ƯU cho quỹ calo còn lại (không được vượt quá).
        
        Trình bày ĐẸP, NGẮN GỌN bằng HTML (sử dụng <b>, <i>, không dùng markdown # hay **):
        🍲 <b>TÊN MÓN ĂN</b> (Kèm mô tả sự hấp dẫn 1 câu)
        
        🛒 <b>Nguyên liệu cần dùng:</b> (Liệt kê định lượng)
        🔥 <b>Cách chế biến:</b> (3-4 bước cực kỳ ngắn gọn, dễ hiểu)
        
        📊 <b>Macro dự kiến:</b> Calories / Protein / Carb / Fat
        💡 <b>Mẹo đầu bếp:</b> (1 mẹo nhỏ để món ăn ngon hơn hoặc healthy hơn)"""
        
        res = client.models.generate_content(model=GEMINI_MODEL, contents=prompt).text
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=status_msg.message_id)
        await update.message.reply_text(clean_for_telegram(res), parse_mode=ParseMode.HTML)
    except Exception as e:
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=status_msg.message_id)
        await update.message.reply_text(f"Lỗi nhà bếp: {e}")

async def food_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("🍽️ Sếp vui lòng nhập món ăn. VD: `/food 3 quả trứng luộc và 1 cốc sữa`", parse_mode=ParseMode.MARKDOWN)
        return
    
    status_msg = await update.message.reply_text("🔍 <i>Đang soi món ăn và tính Calo...</i>", parse_mode=ParseMode.HTML)
    try:
        health = load_json(HEALTH_FILE, {})
        target = health.get("target_calories", 2000)
        
        prompt = f"""Bạn là một chuyên gia dinh dưỡng. Người dùng vừa nhập thực đơn: "{text}".
        Mục tiêu 1 ngày của người dùng là nạp {target} Calories.
        Hãy ước lượng khẩu phần và tính toán.
        Trả về ĐÚNG định dạng JSON sau (không chứa ký tự thừa):
        {{"food_name": "Tóm tắt tên món", "calories": 500, "protein": 30, "carb": 40, "fat": 15, "advice": "Nhận xét ngắn gọn 1 câu xem món này có tốt cho mục tiêu không (kèm emoji)"}}"""
        
        res = client.models.generate_content(model=GEMINI_MODEL, contents=prompt).text.strip()
        data = json.loads(res.replace("```json", "").replace("```", "").strip())
        
        vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        today_str = datetime.now(vn_tz).strftime("%Y-%m-%d")
        nutri = load_json(NUTRITION_FILE, {})
        if today_str not in nutri:
            nutri[today_str] = {"consumed_calories": 0, "protein": 0, "carb": 0, "fat": 0, "logs": []}
            
        nutri[today_str]["consumed_calories"] += data["calories"]
        nutri[today_str]["protein"] += data["protein"]
        nutri[today_str]["carb"] += data["carb"]
        nutri[today_str]["fat"] += data["fat"]
        nutri[today_str]["logs"].append(f"{data['food_name']} ({data['calories']} kcal)")
        save_json(NUTRITION_FILE, nutri)
        
        remaining = target - nutri[today_str]["consumed_calories"]
        
        msg = f"🍽️ <b>{data['food_name'].upper()}</b>\n\n"
        msg += f"🔥 <b>Năng lượng:</b> {data['calories']} kcal\n"
        msg += f"💪 <b>P/C/F (g):</b> {data['protein']} / {data['carb']} / {data['fat']}\n\n"
        msg += f"💡 <i>{data['advice']}</i>\n\n"
        msg += f"📉 <b>Tổng đã nạp hôm nay:</b> {nutri[today_str]['consumed_calories']} / {target} kcal\n"
        msg += f"🎯 <b>Quỹ Calo còn lại:</b> {remaining} kcal"
        
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=status_msg.message_id)
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=status_msg.message_id)
        await update.message.reply_text(f"Lỗi soi chiếu món ăn: {e}")

async def learn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("🧠 Sếp muốn em nhớ điều gì? VD: `/learn Từ nay gọi tôi là Chủ Tịch`", parse_mode=ParseMode.MARKDOWN)
        return
    
    try:
        memory = load_json(MEMORY_FILE, {"rules": []})
        memory["rules"].append(text)
        save_json(MEMORY_FILE, memory)
        await update.message.reply_text("🧠 Đã lưu vào bộ nhớ cốt lõi (Core Memory). Em sẽ luôn tuân thủ nguyên tắc này từ nay về sau!")
    except Exception as e:
        await update.message.reply_text(f"Lỗi: {e}")

async def handle_chat_text(update, context, text):
    if "#idea" in text.lower():
        await execute_idea(update.message.chat_id, context, text.lower().replace("#idea", "").strip())
        return

    try:
        ideas = load_json(IDEAS_FILE, {"ideas": []})
        recent_ideas = "\n".join([f"- {i['text']}" for i in ideas.get("ideas", [])[-5:]])
        ctx = f"KHO Ý TƯỞNG CỦA NGƯỜI DÙNG:\n{recent_ideas}\n\n" if recent_ideas else ""
        
        # Inject Nutrition Context
        vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        today_str = datetime.now(vn_tz).strftime("%Y-%m-%d")
        health = load_json(HEALTH_FILE, {})
        nutri = load_json(NUTRITION_FILE, {}).get(today_str, {})
        if health and nutri:
            target = health.get('target_calories', 2000)
            consumed = nutri.get('consumed_calories', 0)
            logs = ", ".join(nutri.get('logs', []))
            ctx += f"HỒ SƠ DINH DƯỠNG HÔM NAY ({today_str}): Mục tiêu {target} kcal. Đã nạp {consumed} kcal. Các món đã ăn: {logs}. Calo còn lại: {target - consumed} kcal.\n\n"
            
        # Tự động đọc Link (URL) nếu có
        url_match = re.search(r'(https?://[^\s]+)', text)
        if url_match:
            url = url_match.group(0)
            status_msg = await update.message.reply_text("🌐 <i>Đang cắm cáp truy cập link sếp gửi...</i>", parse_mode=ParseMode.HTML)
            try:
                import trafilatura
                downloaded = trafilatura.fetch_url(url)
                if downloaded:
                    extracted = trafilatura.extract(downloaded)
                    if extracted:
                        ctx += f"NỘI DUNG BÀI VIẾT TỪ LINK MÀ NGƯỜI DÙNG VỪA GỬI ({url}):\n{extracted[:6000]}\n\n"
                    else:
                        ctx += f"HỆ THỐNG GHI CHÚ: Trang web ({url}) này chặn bot hoặc yêu cầu đăng nhập (như Facebook/Tiktok). Hãy báo cho người dùng biết bạn không thể đọc được bài viết này.\n\n"
                else:
                    ctx += f"HỆ THỐNG GHI CHÚ: Trang web ({url}) từ chối kết nối. Hãy báo cho người dùng biết.\n\n"
            except Exception as e:
                pass
            await context.bot.delete_message(chat_id=update.message.chat_id, message_id=status_msg.message_id)
            
        # Inject Core Memory
        memory = load_json(MEMORY_FILE, {"rules": []})
        if memory.get("rules"):
            rules_str = "\n".join([f"- {r}" for r in memory["rules"]])
            ctx += f"BỘ NHỚ LÕI (CÁC NGUYÊN TẮC BẠN PHẢI TUÂN THỦ TỪ NGƯỜI DÙNG):\n{rules_str}\n\n"
        
        prompt = ctx + text + "\n\n(SYSTEM PROMPT TỐI CAO: Đóng vai một Quân sư cấp cao / Trợ lý tinh hoa. Suy nghĩ sâu sắc, lập luận đa chiều, đưa ra góc nhìn sắc bén và giải pháp đột phá. Không bao giờ nói chung chung hay sáo rỗng. Dài hay ngắn tuỳ vào mức độ phức tạp của câu hỏi, nhưng phải CHẤT LƯỢNG. KHÔNG dùng markdown # hay **, chỉ dùng thẻ <b>, <i> chuẩn HTML. Luôn xưng hô theo đúng luật trong Bộ Nhớ Lõi, nếu không có thì gọi là 'sếp' và xưng 'em')."
        
        # Thử gọi API, nếu gặp lỗi 500 (Google Server quá tải) thì tự động thử lại 1 lần
        import time as sys_time
        import random
        max_retries = 4
        response = None
        for attempt in range(max_retries):
            try:
                # Nếu đã fail 2 lần (attempt >= 2), dùng mô hình dự phòng (Lite)
                if attempt >= 2:
                    response = client.models.generate_content(
                        model="gemini-flash-lite-latest",
                        contents=prompt
                    ).text
                else:
                    response = chat_session.send_message(prompt).text
                break
            except Exception as api_e:
                if ("500" in str(api_e) or "503" in str(api_e) or "429" in str(api_e)) and attempt < max_retries - 1:
                    sleep_time = (2 ** attempt) + random.uniform(0, 1)
                    sys_time.sleep(sleep_time)
                else:
                    raise api_e
                
        await update.message.reply_text(clean_for_telegram(response), parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Lỗi Server AI: {e}")

async def handle_chat_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_chat_text(update, context, update.message.text)


# --- MENTOR-OS (BUSINESS & ENGLISH) ---
async def pitch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("🦈 Sếp hãy nhập ý tưởng kinh doanh. VD: `/pitch Mở quán cafe kết hợp xem bài Tarot`", parse_mode=ParseMode.MARKDOWN)
        return
    
    # Âm thầm lưu vào Second Brain (ideas.json)
    try:
        import time as sys_time
        ideas = load_json(IDEAS_FILE, {"ideas": []})
        ideas["ideas"].append({
            "id": str(int(sys_time.time())),
            "text": f"[Pitch Doanh nghiệp]: {text}",
            "timestamp": datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime("%Y-%m-%d %H:%M")
        })
        save_json(IDEAS_FILE, ideas)
    except Exception as e:
        logger.error(f"Lỗi lưu pitch: {e}")

    status_msg = await update.message.reply_text("🦈 <i>Shark Bot đang soi ý tưởng của sếp...</i>", parse_mode=ParseMode.HTML)
    
    memory_ctx = ""
    memory = load_json(MEMORY_FILE, {"rules": []})
    if memory.get("rules"):
        memory_ctx = "\n\nTUÂN THỦ CÁC NGUYÊN TẮC SAU:\n" + "\n".join([f"- {r}" for r in memory["rules"]])
        
    prompt = f"""Đóng vai một 'Shark' (Nhà đầu tư) khắt khe và thực tế trên Shark Tank. Người dùng vừa trình bày ý tưởng kinh doanh sau: "{text}".
    Hãy phản biện và cố vấn. Trình bày rõ ràng theo cấu trúc:
    1. 🩸 Điểm chết (Chỉ ra 1-2 rủi ro chí mạng nhất của mô hình này).
    2. 💡 Lối thoát (Gợi ý chiến lược Go-to-Market hoặc cách pivot để kiếm được tiền).
    3. 📚 Từ vựng thương trường (Liệt kê đúng 3 từ vựng Tiếng Anh chuyên ngành Kinh doanh/Khởi nghiệp đã được chèn khéo léo trong bài viết, kèm giải nghĩa ngắn).
    4. Đánh giá khả thi: X/10 điểm.
    Lưu ý: Giọng điệu gai góc, sắc sảo, thực tế. KHÔNG dùng markdown # hay **, chỉ dùng văn bản thường và emoji. Sử dụng <b> cho in đậm, <i> cho in nghiêng nếu cần (chuẩn HTML).{memory_ctx}"""
    
    try:
        res = client.models.generate_content(model=GEMINI_MODEL, contents=prompt).text
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=status_msg.message_id)
        await update.message.reply_text(clean_for_telegram(res), parse_mode=ParseMode.HTML)
    except Exception as e:
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=status_msg.message_id)
        await update.message.reply_text(f"Lỗi hệ thống Shark: {e}")

from gtts import gTTS

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
        res = client.models.generate_content(model=GEMINI_MODEL, contents=prompt).text
        
        text_parts = []
        vocab_for_audio = ""
        for line in res.split('\n'):
            if line.startswith("AUDIO_VOCAB|"):
                vocab_for_audio = line.split("|")[1]
            else:
                text_parts.append(line)
                
        msg = f"🍱 <b>BỮA TRƯA DOANH NHÂN</b>\n\n{clean_for_telegram('\n'.join(text_parts))}"
        await context.bot.send_message(chat_id=CHAT_ID_BOOKS, text=msg, parse_mode=ParseMode.HTML)
        
        if vocab_for_audio:
            tts = gTTS(text=vocab_for_audio, lang='en')
            tts.save("vocab.mp3")
            await context.bot.send_voice(chat_id=CHAT_ID_BOOKS, voice=open("vocab.mp3", "rb"))
            
    except Exception as e:
        logger.error(f"Lỗi gửi Business Cheat: {e}")

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
    await send_business_cheat(context)
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
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(CommandHandler("healthsetup", healthsetup_command))
    app.add_handler(CommandHandler("food", food_command))
    app.add_handler(CommandHandler("cook", cook_command))
    app.add_handler(CommandHandler("pitch", pitch_command))
    app.add_handler(CommandHandler("learn", learn_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CommandHandler("push", manual_trigger))
    
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat_route))

    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    app.job_queue.run_daily(send_news_to_channel, time=time(hour=7, minute=0, tzinfo=vn_tz))
    app.job_queue.run_daily(send_business_cheat, time=time(hour=12, minute=0, tzinfo=vn_tz))
    app.job_queue.run_daily(send_book_to_channel, time=time(hour=20, minute=0, tzinfo=vn_tz)) 
    
    load_pending_reminders(app.job_queue)

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
