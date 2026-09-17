"""To-do list: /todo /tasks"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core_actions import execute_todo
from storage import todo_store


async def todo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task_text = " ".join(context.args)
    await execute_todo(update.message.chat_id, context, task_text)


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    todos = await todo_store.read()
    pending = [t for t in todos.get("tasks", []) if t["status"] == "pending"]
    if not pending:
        await update.message.reply_text("🎉 Không còn công việc nào tồn đọng.")
        return

    msg = "📝 <b>DANH SÁCH CÔNG VIỆC CHƯA LÀM:</b>\n\n"
    keyboard, row = [], []
    for i, t in enumerate(pending):
        msg += f"<b>{i + 1}.</b> {t['text']}\n"
        row.append(InlineKeyboardButton(f"✅ Xong {i + 1}", callback_data=f"tododone_{t['id']}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
