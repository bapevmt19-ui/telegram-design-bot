"""Lệnh nhắc nhở: /remind, /remind_daily, /remind_every, /remind_list,
/remind_stop.

Nâng cấp (17/9, lần 7):
- /remind giờ nhận thêm ngày cụ thể tuỳ chọn (DD/MM HH:MM) — trước đây
  chỉ có HH:MM nên không hẹn được một ngày xác định trong tương lai,
  luôn hiểu là "hôm nay hoặc ngày mai gần nhất".
- /remind_daily, /remind_every: việc KHÔNG gắn với 1 ngày cụ thể (VD
  uống thuốc, tập thể dục) — nhắc lặp lại liên tục theo giờ cố định
  mỗi ngày, hoặc theo khoảng cách N tiếng.
- Các "nhắc lặp lại" được lưu vào recurring_reminders_store để
  load_recurring_reminders() đăng ký lại đúng vào job_queue sau khi
  bot restart (job_queue của PTB chỉ nằm trong bộ nhớ, không tự bền
  vững qua redeploy như dữ liệu ở Postgres).
"""
from datetime import datetime, time, timedelta

import pytz
from telegram import Update
from telegram.ext import ContextTypes

from core_actions import add_reminder
from storage import recurring_reminders_store
from telegram_helpers import send_chunked_message

VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = context.args
        now = datetime.now(VN_TZ)

        # Có "/" ở tham số đầu -> hiểu là ngày cụ thể DD/MM HH:MM.
        # Không có -> giữ nguyên cách dùng cũ: HH:MM (tự hiểu hôm
        # nay/ngày mai gần nhất), không phá tương thích ngược.
        if "/" in args[0]:
            day, month = map(int, args[0].split("/"))
            hour, minute = map(int, args[1].split(":"))
            task_text = " ".join(args[2:])
            remind_time = VN_TZ.localize(datetime(now.year, month, day, hour, minute))
            if remind_time < now:
                remind_time = remind_time.replace(year=now.year + 1)
        else:
            hour, minute = map(int, args[0].split(":"))
            task_text = " ".join(args[1:])
            remind_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if remind_time < now:
                remind_time += timedelta(days=1)

        if not task_text:
            raise ValueError("thiếu nội dung")

        await add_reminder(context.application.job_queue, update.message.chat_id, remind_time, task_text)
        await send_chunked_message(
            update.message.reply_text,
            f"⏰ Đã hẹn giờ báo thức lúc <b>{remind_time.strftime('%H:%M %d/%m')}</b> cho việc:\n{task_text}",
        )
    except Exception:
        await update.message.reply_text(
            "Lỗi cú pháp! Gõ:\n"
            "/remind HH:MM [Nội dung] (VD: /remind 15:30 Họp team — hôm nay/mai gần nhất)\n"
            "/remind DD/MM HH:MM [Nội dung] (VD: /remind 25/09 15:00 Họp khách hàng — đúng ngày cụ thể)"
        )


async def send_recurring_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    await context.bot.send_message(
        chat_id=data["chat_id"], text=f"🔁 <b>NHẮC LẶP LẠI:</b>\n{data['text']}", parse_mode="HTML"
    )


async def remind_daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        hour, minute = map(int, context.args[0].split(":"))
        task_text = " ".join(context.args[1:])
        if not task_text:
            raise ValueError("thiếu nội dung")

        rec_id = str(int(datetime.now().timestamp() * 1000))
        chat_id = update.message.chat_id

        def _mutate(data):
            data.setdefault("items", []).append(
                {"id": rec_id, "chat_id": chat_id, "kind": "daily", "hour": hour, "minute": minute, "text": task_text}
            )
            return data

        await recurring_reminders_store.update(_mutate)
        context.application.job_queue.run_daily(
            send_recurring_reminder_job,
            time=time(hour=hour, minute=minute, tzinfo=VN_TZ),
            data={"chat_id": chat_id, "text": task_text},
            name=f"recur_{rec_id}",
        )
        await update.message.reply_text(
            f"🔁 Đã đặt nhắc lặp lại HÀNG NGÀY lúc {hour:02d}:{minute:02d} cho: {task_text}\n"
            "Gõ /remind_list để xem, /remind_stop [số] để tắt."
        )
    except Exception:
        await update.message.reply_text(
            "Lỗi cú pháp! Gõ: /remind_daily HH:MM [Nội dung] (VD: /remind_daily 07:00 Uống thuốc huyết áp)"
        )


async def remind_every_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        interval_hours = float(context.args[0].lower().rstrip("h"))
        if interval_hours <= 0:
            raise ValueError("khoảng giờ phải > 0")
        task_text = " ".join(context.args[1:])
        if not task_text:
            raise ValueError("thiếu nội dung")

        rec_id = str(int(datetime.now().timestamp() * 1000))
        chat_id = update.message.chat_id

        def _mutate(data):
            data.setdefault("items", []).append(
                {"id": rec_id, "chat_id": chat_id, "kind": "every", "interval_hours": interval_hours, "text": task_text}
            )
            return data

        await recurring_reminders_store.update(_mutate)
        context.application.job_queue.run_repeating(
            send_recurring_reminder_job,
            interval=timedelta(hours=interval_hours),
            first=timedelta(hours=interval_hours),
            data={"chat_id": chat_id, "text": task_text},
            name=f"recur_{rec_id}",
        )
        await update.message.reply_text(
            f"🔁 Đã đặt nhắc lặp lại MỖI {interval_hours:g} tiếng cho: {task_text}\n"
            "Gõ /remind_list để xem, /remind_stop [số] để tắt."
        )
    except Exception:
        await update.message.reply_text(
            "Lỗi cú pháp! Gõ: /remind_every [số]h [Nội dung] (VD: /remind_every 2h Uống nước)"
        )


async def remind_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = await recurring_reminders_store.read()
    items = data.get("items", [])
    if not items:
        await update.message.reply_text("Không có nhắc lặp lại nào đang chạy.")
        return

    lines = ["🔁 <b>DANH SÁCH NHẮC LẶP LẠI:</b>\n"]
    for i, item in enumerate(items):
        when = (
            f"hàng ngày {item['hour']:02d}:{item['minute']:02d}"
            if item["kind"] == "daily"
            else f"mỗi {item['interval_hours']:g}h"
        )
        lines.append(f"{i + 1}. [{when}] {item['text']}")
    lines.append("\nGõ /remind_stop [số] để tắt.")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def remind_stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        idx = int(context.args[0]) - 1
        data = await recurring_reminders_store.read()
        items = data.get("items", [])
        if idx < 0 or idx >= len(items):
            await update.message.reply_text("Số không hợp lệ, gõ /remind_list để xem lại danh sách.")
            return
        item = items[idx]

        for job in context.application.job_queue.get_jobs_by_name(f"recur_{item['id']}"):
            job.schedule_removal()

        def _mutate(d):
            d["items"] = [x for x in d.get("items", []) if x["id"] != item["id"]]
            return d

        await recurring_reminders_store.update(_mutate)
        await update.message.reply_text(f"✅ Đã tắt nhắc lặp lại: {item['text']}")
    except Exception:
        await update.message.reply_text("Lỗi cú pháp! Gõ: /remind_stop [số] (xem số bằng /remind_list)")


async def load_recurring_reminders(job_queue):
    """Đăng ký lại các nhắc lặp lại (/remind_daily, /remind_every) vào
    job_queue sau khi bot restart — gọi từ post_init trong main.py,
    cùng nhịp với load_pending_reminders()."""
    data = await recurring_reminders_store.read()
    for item in data.get("items", []):
        if item["kind"] == "daily":
            job_queue.run_daily(
                send_recurring_reminder_job,
                time=time(hour=item["hour"], minute=item["minute"], tzinfo=VN_TZ),
                data={"chat_id": item["chat_id"], "text": item["text"]},
                name=f"recur_{item['id']}",
            )
        elif item["kind"] == "every":
            job_queue.run_repeating(
                send_recurring_reminder_job,
                interval=timedelta(hours=item["interval_hours"]),
                first=timedelta(hours=item["interval_hours"]),
                data={"chat_id": item["chat_id"], "text": item["text"]},
                name=f"recur_{item['id']}",
            )
