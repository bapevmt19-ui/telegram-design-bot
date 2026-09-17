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
    _core_ids = {int(CHAT_ID_PRIVATE), int(CHAT_ID_BOOKS), int(CHAT_ID_NEWS)}
except ValueError as e:
    raise RuntimeError(
        "TELEGRAM_CHAT_ID / TELEGRAM_CHAT_ID_BOOKS / TELEGRAM_CHAT_ID_NEWS phải là số nguyên."
    ) from e

# Danh sách chat_id được PHÉP dùng bot: chat riêng của sếp + 2 kênh
# broadcast (để nút bấm trong 2 kênh đó vẫn hoạt động). Có thể thêm
# chat_id khác (VD người thân) qua biến môi trường ALLOWED_CHAT_IDS,
# cách nhau bằng dấu phẩy.
ALLOWED_CHAT_IDS = _core_ids | _parse_chat_ids(os.getenv("ALLOWED_CHAT_IDS", ""))

GEMINI_MODEL = "gemini-flash-latest"
MODEL_PRO = "gemini-2.5-pro"

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
