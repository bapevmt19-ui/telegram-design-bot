"""Cấu hình & hằng số tập trung cho Life-OS Bot."""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID_PRIVATE = os.getenv("TELEGRAM_CHAT_ID")
# Trước đây 2 giá trị này hard-code thẳng trong source. Đưa ra .env để
# dễ đổi giữa các môi trường / không lộ ID nội bộ khi code lên repo,
# nhưng vẫn giữ giá trị cũ làm mặc định để không phá vỡ deploy hiện tại.
CHAT_ID_BOOKS = os.getenv("TELEGRAM_CHAT_ID_BOOKS", "-1004324433124")
CHAT_ID_NEWS = os.getenv("TELEGRAM_CHAT_ID_NEWS", "-1004430444714")

if not GEMINI_API_KEY or not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "Thiếu GEMINI_API_KEY hoặc TELEGRAM_BOT_TOKEN trong file .env — "
        "bot không thể khởi động. Vui lòng kiểm tra lại file .env."
    )

GEMINI_MODEL = "gemini-flash-latest"
MODEL_PRO = "gemini-2.5-pro"

# Giữ nguyên tên file ở thư mục gốc như bản cũ để không cần di chuyển
# dữ liệu hiện có khi nâng cấp lên bản refactor này.
FINANCE_FILE = "finance.json"
TODO_FILE = "todos.json"
IDEAS_FILE = "ideas.json"
REMINDERS_FILE = "reminders.json"
HEALTH_FILE = "health.json"
NUTRITION_FILE = "nutrition.json"
MEMORY_FILE = "memory.json"

RSS_FEEDS_DESIGN = {
    "💡 UX/UI Design": "https://uxdesign.cc/feed",
    "🎨 Web Design": "https://www.smashingmagazine.com/feed/",
}
RSS_FEEDS_AI = {"🤖 AI News": "https://www.artificialintelligence-news.com/feed/"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("lifeos_bot")
