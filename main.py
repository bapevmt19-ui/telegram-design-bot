"""Điểm khởi động của Quản Gia Life-OS."""
import asyncio
import time as sys_time
from datetime import datetime, time

import pytz
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from config import ALLOWED_CHAT_IDS, TELEGRAM_BOT_TOKEN, logger
from core_actions import load_pending_reminders
from handlers.ai_chat import deep_command, handle_chat_route, handle_voice, learn_command, pitch_command
from handlers.finance import budget_command, goal_command, report_command, salary_command, spend_command
from handlers.health import cook_command, food_command, handle_photo, healthsetup_command
from handlers.reminders import remind_command
from handlers.system import help_command, start_command
from handlers.todo import tasks_command, todo_command
from handlers.video import handle_video
from jobs import manual_trigger, send_book_to_channel, send_business_cheat, send_news_to_channel
from server import start_dummy_server
from storage import finance_store, migrate_legacy_json_if_needed, todo_store

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


async def guard_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Chặn truy cập từ chat_id lạ — HẠNG MỤC B.

    Bản gốc (và các bản refactor trước) đọc TELEGRAM_CHAT_ID từ .env
    nhưng KHÔNG DÙNG nó để chặn gì cả: bất kỳ ai tìm ra bot (VD thêm
    nhầm vào nhóm, hoặc đoán được username) đều thao tác được —
    xem/sửa dữ liệu tài chính-sức khoẻ riêng tư, tốn quota Gemini của
    sếp. Handler này đăng ký ở group=-1 (chạy TRƯỚC mọi handler khác,
    xem main()) và raise ApplicationHandlerStop để chặn update lan
    tiếp xuống các handler group sau, nếu chat_id không nằm trong
    config.ALLOWED_CHAT_IDS (chat riêng của sếp + 2 kênh broadcast +
    danh sách tuỳ chọn qua biến môi trường).

    Cố tình KHÔNG trả lời gì cho chat lạ (im lặng) — vừa tránh lộ
    thông tin bot còn sống/đang làm gì, vừa tránh bị lợi dụng để spam
    tin nhắn phản hồi tới người khác.
    """
    chat = update.effective_chat
    if chat is not None and chat.id not in ALLOWED_CHAT_IDS:
        logger.warning("🚫 Chặn truy cập từ chat_id lạ: %s (%s)", chat.id, chat.type)
        raise ApplicationHandlerStop


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
    thay vì gọi hàm đồng bộ giữa chừng main() như bản gốc.

    HẠNG MỤC A2 + C: migrate dữ liệu JSON cũ sang Postgres (nếu có
    DATABASE_URL và đây là lần đầu chuyển sang dùng Postgres), và đăng
    ký danh sách lệnh với Telegram để hiện gợi ý khi sếp gõ "/".

    Cố tình bọc try/except quanh migrate: nếu Postgres đang lỗi/chưa
    kết nối được (VD sai connection string, DB đang khởi động...),
    KHÔNG được để cả bot sập theo — thà bot vẫn chạy được các lệnh
    khác (và tự thử lại Postgres ở lần đọc/ghi dữ liệu kế tiếp) còn
    hơn treo luôn polling chỉ vì 1 bước migrate 1 lần lúc khởi động."""
    try:
        await migrate_legacy_json_if_needed()
    except Exception as e:
        logger.error(
            "⚠️ Không migrate được dữ liệu cũ sang Postgres lúc khởi động (bot vẫn tiếp tục chạy, "
            "sẽ tự thử lại Postgres ở lần đọc/ghi dữ liệu kế tiếp): %s",
            e,
        )
    await load_pending_reminders(app.job_queue)
    await app.bot.set_my_commands(
        [
            BotCommand("start", "Giới thiệu bot"),
            BotCommand("help", "Xem danh sách đầy đủ các lệnh"),
            BotCommand("salary", "Khai báo lương tháng"),
            BotCommand("budget", "Đặt ngân sách theo danh mục"),
            BotCommand("spend", "Ghi chi tiêu"),
            BotCommand("report", "Báo cáo chi tiêu tháng này"),
            BotCommand("goal", "Theo dõi mục tiêu tài chính"),
            BotCommand("todo", "Thêm việc cần làm"),
            BotCommand("tasks", "Xem danh sách việc"),
            BotCommand("remind", "Đặt nhắc nhở"),
            BotCommand("learn", "Học nhanh 1 chủ đề"),
            BotCommand("deep", "Hỏi sâu (model mạnh hơn)"),
            BotCommand("pitch", "Phản biện/góp ý ý tưởng"),
            BotCommand("healthsetup", "Khai báo thông tin sức khoẻ"),
            BotCommand("food", "Tra cứu dinh dưỡng"),
            BotCommand("cook", "Gợi ý món ăn"),
            BotCommand("push", "Kích hoạt thủ công bản tin định kỳ"),
        ]
    )


def main():
    start_dummy_server()

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        # HẠNG MỤC C: cho phép xử lý song song vài update cùng lúc
        # (VD sếp gửi ảnh trong lúc video trước đang phân tích) thay
        # vì xử lý tuần tự từng update một như mặc định. Giới hạn 8
        # (không dùng True = không giới hạn) để tránh dùng quá nhiều
        # quota Gemini cùng lúc trên gói free. An toàn với storage.py
        # vì mọi read-modify-write đều đã bọc asyncio.Lock theo key.
        .concurrent_updates(8)
        .build()
    )

    # HẠNG MỤC B: guard chạy TRƯỚC TIÊN (group=-1) cho MỌI loại update
    # (tin nhắn, callback query, ...) — chặn chat_id lạ trước khi tới
    # bất kỳ handler nghiệp vụ nào bên dưới.
    app.add_handler(TypeHandler(Update, guard_access), group=-1)

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
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
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
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
    #
    # BUG FIX (17/9, lần 3): app.run_polling() tự quản lý 1 event loop
    # asyncio và ĐÓNG nó lại khi thoát (kể cả khi thoát do lỗi) — gọi
    # lại app.run_polling() lần 2 trên cùng tiến trình mà không tạo
    # event loop mới sẽ luôn báo "Event loop is closed" và bot kẹt
    # vĩnh viễn ở trạng thái lỗi dù nguyên nhân gốc (VD Postgres tạm
    # mất kết nối) đã tự hết. Tạo event loop mới trước mỗi lần thử lại
    # để vòng lặp thực sự hồi phục được.
    backoff = 5
    while True:
        try:
            app.run_polling(allowed_updates=Update.ALL_TYPES)
            break
        except Exception as e:
            logger.error("Lỗi Polling (chờ %ss thử lại): %s", backoff, e)
            sys_time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            try:
                asyncio.set_event_loop(asyncio.new_event_loop())
            except Exception as loop_err:
                logger.error("Không tạo lại được event loop: %s", loop_err)


if __name__ == "__main__":
    main()
