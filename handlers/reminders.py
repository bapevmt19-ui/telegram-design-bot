"""Lệnh /remind"""
from datetime import datetime, timedelta

import pytz
from telegram import Update
from telegram.ext import ContextTypes

from core_actions import add_reminder
from telegram_helpers import send_chunked_message

VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        time_str = context.args[0]
        task_text = " ".join(context.args[1:])
        now = datetime.now(VN_TZ)

        hour, minute = map(int, time_str.split(":"))
        remind_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if remind_time < now:
            remind_time += timedelta(days=1)

        await add_reminder(context.application.job_queue, update.message.chat_id, remind_time, task_text)
        await send_chunked_message(
            update.message.reply_text,
            f"⏰ Đã hẹn giờ báo thức lúc <b>{remind_time.strftime('%H:%M %d/%m')}</b> cho việc:\n{task_text}",
        )
    except Exception:
        await update.message.reply_text("Lỗi cú pháp! Gõ: /remind HH:MM [Nội dung] (VD: /remind 15:30 Họp team)")
