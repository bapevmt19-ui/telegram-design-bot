"""To-do list: /todo /tasks"""
from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core_actions import execute_todo, render_tasks_message
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

    # Nâng cấp (17/9, lần 7): logic hiển thị (thẻ !gấp, hạn chót, số
    # ngày tồn đọng, nút "✅ Xong" riêng theo từng task) giờ dùng chung
    # với các job tự động nhắc việc 3x/ngày — xem render_tasks_message
    # trong core_actions.py.
    msg, keyboard = render_tasks_message(pending)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
