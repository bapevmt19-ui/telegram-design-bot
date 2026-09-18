"""Cấu hình & hằng số tập trung cho Life-OS Bot."""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("lifeos_bot")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID_PRIVATE = os.getenv("TELEGRAM_CHAT_ID")
CHAT_ID_BOOKS = os.getenv("TELEGRAM_CHAT_ID_BOOKS", "-1004324433124")
CHAT_ID_NEWS = os.getenv("TELEGRAM_CHAT_ID_NEWS", "-1004430444714")
# Nâng cấp (17/9, lần 7): kênh riêng nhận file backup dữ liệu
# (/export_data thủ công + tự động hàng tuần) — tách riêng khỏi chat
# cá nhân để tránh loạn tin nhắn.
CHAT_ID_BACKUP = os.getenv("TELEGRAM_CHAT_ID_BACKUP", "-1004393711929")

if not GEMINI_API_KEY or not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "Thiếu GEMINI_API_KEY hoặc TELEGRAM_BOT_TOKEN trong file .env — "
        "bot không thể khởi động. Vui lòng kiểm tra lại file .env."
    )

if not CHAT_ID_PRIVATE:
    # Trước đây biến này được đọc nhưng KHÔNG dùng ở đâu để chặn người
    # lạ -> ai tìm ra bot đều thao tác được (xem dữ liệu tài
    # chính/sức khoẻ, gọi Gemini tốn quota của sếp...). Giờ đây nó là
    # điều kiện bắt buộc để bot biết "chủ nhân" là ai.
    raise RuntimeError(
        "Thiếu TELEGRAM_CHAT_ID trong .env — bot cần biết chat_id của sếp "
        "để chặn người lạ thao tác. Lấy chat_id bằng cách nhắn bot @userinfobot."
    )


def _parse_chat_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            logger.warning("Bỏ qua chat_id không hợp lệ trong ALLOWED_CHAT_IDS: %r", part)
    return ids


try:
    _core_ids = {int(CHAT_ID_PRIVATE), int(CHAT_ID_BOOKS), int(CHAT_ID_NEWS), int(CHAT_ID_BACKUP)}
except ValueError as e:
    raise RuntimeError(
        "TELEGRAM_CHAT_ID / TELEGRAM_CHAT_ID_BOOKS / TELEGRAM_CHAT_ID_NEWS / "
        "TELEGRAM_CHAT_ID_BACKUP phải là số nguyên."
    ) from e

# Danh sách chat_id được PHÉP dùng bot: chat riêng của sếp + 2 kênh
# broadcast (để nút bấm trong 2 kênh đó vẫn hoạt động). Có thể thêm
# chat_id khác (VD người thân) qua biến môi trường ALLOWED_CHAT_IDS,
# cách nhau bằng dấu phẩy.
ALLOWED_CHAT_IDS = _core_ids | _parse_chat_ids(os.getenv("ALLOWED_CHAT_IDS", ""))

# BUG FIX (17/9, lần 5): Google ngừng cấp "gemini-2.5-pro" cho user
# mới -- /deep và /pitch (2 lệnh duy nhất dùng MODEL_PRO) báo lỗi
# 404 NOT_FOUND. Đổi sang model Google chỉ định thay thế ngay trong
# chính thông báo lỗi ("Please update your code to use
# models/gemini-3.1-pro-preview"). Không phải lỗi do code hay do sếp
# thao tác -- Google tự đổi model available.
GEMINI_MODEL = "gemini-flash-latest"
MODEL_PRO = "gemini-3.1-pro-preview"

# Giữ nguyên tên file ở thư mục gốc như bản cũ — dùng làm nơi lưu dự
# phòng/để migrate dữ liệu cũ 1 lần khi chuyển sang Postgres (xem
# storage.py). Lưu ý: trên Render Free, các file này KHÔNG bền vững
# qua các lần redeploy/restart (ổ đĩa ephemeral).
FINANCE_FILE = "finance.json"
TODO_FILE = "todos.json"
IDEAS_FILE = "ideas.json"
REMINDERS_FILE = "reminders.json"
HEALTH_FILE = "health.json"
NUTRITION_FILE = "nutrition.json"
MEMORY_FILE = "memory.json"
# BUG FIX (17/9, lần 6): lưu lịch sử chủ đề "Bữa trưa doanh nhân" +
# tên sách "Trích sách tối" đã gửi gần đây -- trước đây jobs.py gọi
# Gemini với prompt y hệt mỗi ngày, không biết hôm qua đã gửi gì, nên
# dễ lặp lại chủ đề/cuốn sách sau vài ngày. Xem CONTENT_HISTORY_FILE
# dùng trong jobs.py.
CONTENT_HISTORY_FILE = "content_history.json"
# Nâng cấp (17/9, lần 7): lưu access_token Telegraph để không mất
# quyền sửa bài cũ mỗi lần bot restart (xem ai_client.py), và lưu các
# "nhắc lặp lại" (/remind_daily, /remind_every) để nạp lại đúng sau
# khi bot restart (xem handlers/reminders.py).
SETTINGS_FILE = "settings.json"
RECURRING_REMINDERS_FILE = "recurring_reminders.json"
# Nâng cấp (18/9, lần 11 — gói miễn phí):
# - CONVERSATION_FILE: lưu vài lượt hỏi-đáp gần nhất của chat tự do
#   theo từng chat_id, để bot "nhớ" đang nói chuyện gì giữa các tin
#   nhắn thay vì mỗi câu là 1 phiên hỏi Gemini hoàn toàn độc lập.
# - LAST_ACTION_FILE: lưu hành động ghi dữ liệu gần nhất (/spend hoặc
#   /todo) theo từng chat_id, để lệnh /undo biết chính xác cần hoàn
#   tác cái gì.
CONVERSATION_FILE = "conversation_history.json"
LAST_ACTION_FILE = "last_action.json"
# Số dòng hội thoại (user+bot tính chung) giữ lại làm ngữ cảnh cho chat
# tự do — 6 dòng = 3 lượt hỏi-đáp gần nhất, đủ để hiểu mạch chuyện mà
# không làm phình prompt quá nhiều.
CONVERSATION_KEEP_LINES = 6
# Nâng cấp (18/9, lần 11): trước đây chat tự do chỉ "nhìn thấy" 5 ý
# tưởng gần nhất trong Bộ Não Thứ 2 -> yêu cầu sửa/xoá 1 ý tưởng cũ hơn
# 5 cái gần nhất sẽ không tìm thấy id để áp dụng. Nâng lên 40 (Gemini
# Flash chịu được input lớn hơn thế rất nhiều, không tốn thêm chi phí,
# chỉ là nhiều chữ hơn trong 1 lần gọi) để phạm vi "nhớ" ý tưởng cũ rộng
# hơn hẳn mà không cần đổi hạ tầng gì (VD thêm CSDL vector).
IDEA_CONTEXT_LIMIT = 40
# Nếu sau ngần này phút kể từ lúc nhắc mà sếp chưa bấm "Đã xong", bot
# tự nhắc lại thêm 1 lần nữa cho các nhắc nhở có mốc thời gian cụ thể
# (/remind) — xem core_actions.py.
REMINDER_FOLLOWUP_MINUTES = 30

# Nếu đặt DATABASE_URL (VD connection string Supabase Postgres),
# storage.py sẽ tự động dùng Postgres làm nơi lưu bền vững thay vì
# file JSON cục bộ — dữ liệu sống sót qua mọi lần redeploy/restart.
# Không đặt thì bot vẫn chạy được với file JSON như trước (tiện cho
# chạy thử ở máy local), chỉ là dữ liệu không bền trên Render Free.
DATABASE_URL = os.getenv("DATABASE_URL")
# 'require' cho Supabase (bắt buộc SSL); đặt 'disable' nếu chạy
# Postgres local không có SSL.
DB_SSL = os.getenv("DB_SSL", "require")

RSS_FEEDS_DESIGN = {
    "💡 UX/UI Design": "https://uxdesign.cc/feed",
    "🎨 Web Design": "https://www.smashingmagazine.com/feed/",
}
RSS_FEEDS_AI = {"🤖 AI News": "https://www.artificialintelligence-news.com/feed/"}
