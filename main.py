"""Điểm khởi động của Quản Gia Life-OS."""
import time as sys_time
from datetime import datetime, time

import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import TELEGRAM_BOT_TOKEN, logger
from core_actions import load_pending_reminders
from handlers.ai_chat import deep_command, handle_chat_route, handle_voice, learn_command, pitch_command, handle_video
from handlers.finance import budget_command, goal_command, report_command, salary_command, spend_command
from handlers.health import cook_command, food_command, handle_photo, healthsetup_command
from handlers.reminders import remind_command
from handlers.todo import tasks_command, todo_command
from jobs import manual_trigger, send_book_to_channel, send_business_cheat, send_news_to_channel
from server import start_dummy_server
from storage import finance_store, todo_store

VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "timo_confirm":
        def _mutate(data):
            data["timo_confirmed"] = True
            return data

        await finance_store.update(_mutate)
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Đã chia tiền thành công", callback_data="none")]])
        )
    elif query.data.startswith("book_read_"):
        now_str = datetime.now(VN_TZ).strftime("%H:%M")
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Sếp đã đọc lúc {now_str}", callback_data="none")]])
        )
    elif query.data.startswith("read_"):
        now_str = datetime.now(VN_TZ).strftime("%H:%M")
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(f"✅ Sếp đã nắm bắt tin tức lúc {now_str}", callback_data="none")]]
            )
        )
    elif query.data.startswith("tododone_"):
        task_id = query.data.split("_", 1)[1]

        def _mutate(data):
            for t in data.get("tasks", []):
                if t["id"] == task_id:
                    t["status"] = "completed"
            return data

        await todo_store.update(_mutate)
        await tasks_command(update, context)


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler — bản gốc KHÔNG có cái này, nên lỗi phát
    sinh ngoài các khối try/except thủ công (VD trong button_callback,
    hoặc trong 1 job định kỳ nếu có exception không lường trước) chỉ
    bị PTB log lại một cách rời rạc, không có chỗ tập trung để theo
    dõi/alert."""
    logger.error("Update %s gây lỗi: %s", update, context.error, exc_info=context.error)


async def post_init(app: Application):
    """Chạy 1 lần sau khi Application dựng xong, trước khi polling bắt
    đầu — cách làm chuẩn của PTB v20 để nạp lại reminder còn dang dở,
    thay vì gọi hàm đồng bộ giữa chừng main() như bản gốc."""
    await load_pending_reminders(app.job_queue)


def main():
    start_dummy_server()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

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
    # BUG FIX: bản gốc định nghĩa deep_command nhưng KHÔNG BAO GIỜ
    # đăng ký handler cho nó -> lệnh /deep chưa từng hoạt động.
    app.add_handler(CommandHandler("deep", deep_command))
    app.add_handler(CommandHandler("push", manual_trigger))

    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat_route))

    app.add_error_handler(on_error)

    app.job_queue.run_daily(send_news_to_channel, time=time(hour=7, minute=0, tzinfo=VN_TZ))
    app.job_queue.run_daily(send_business_cheat, time=time(hour=12, minute=0, tzinfo=VN_TZ))
    app.job_queue.run_daily(send_book_to_channel, time=time(hour=20, minute=0, tzinfo=VN_TZ))

    logger.info("🤖 Quản Gia Life-OS đang khởi động...")

    # Vòng lặp chống lỗi "Conflict" (409) khi deploy cuốn chiếu (bản
    # cũ + bản mới cùng poll trong vài giây). Thêm backoff tăng dần
    # (5s -> 10s -> ... -> tối đa 60s) so với bản gốc (luôn sleep cố
    # định 5s), để tránh spam Telegram API nếu lỗi kéo dài do nguyên
    # nhân không tự khỏi (VD sai token/cấu hình).
    backoff = 5
    while True:
        try:
            app.run_polling(allowed_updates=Update.ALL_TYPES)
            break
        except Exception as e:
            logger.error("Lỗi Polling (chờ %ss thử lại): %s", backoff, e)
            sys_time.sleep(backoff)
            backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    main()

