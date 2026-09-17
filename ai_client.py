"""
Client Gemini + Telegraph dùng chung, và các hàm helper xử lý text.

QUAN TRỌNG: `call_gemini_robust` bên dưới giữ NGUYÊN 100% logic gốc
(cascade fallback: model chỉ định -> gemini-flash-latest ->
gemini-flash-lite-latest khi gặp lỗi 429/500/503, retry tối đa 3 lần).
Chỉ có 1 wrapper async mới (`call_gemini_async`) được thêm vào để
chạy hàm blocking này trong thread riêng, không chặn event loop của
bot — đây là hàm mà TOÀN BỘ handler nên dùng thay vì gọi thẳng
call_gemini_robust hay client.models.generate_content.
"""
import asyncio
import logging
import re
import time as sys_time

from google import genai
from telegraph import Telegraph

from config import GEMINI_API_KEY, GEMINI_MODEL
from storage import settings_store

logger = logging.getLogger(__name__)

client = genai.Client(api_key=GEMINI_API_KEY)

# BUG FIX (17/9, lần 7): bản trước gọi create_account() ngay ở đây,
# MỖI LẦN bot khởi động lại — Telegraph coi đó là 1 tài khoản MỚI, nên
# mất quyền sửa mọi trang đã tạo ở lần chạy trước (trang cũ vẫn đọc
# được bình thường, chỉ là không sửa lại được nữa). Giờ chỉ khởi tạo
# object rỗng ở đây (không gọi mạng lúc import module); việc đăng
# nhập/tạo account thật sự chuyển sang init_telegraph() bên dưới, gọi
# 1 lần trong post_init của main.py — cùng nhịp với
# migrate_legacy_json_if_needed()/load_pending_reminders().
telegraph_client = Telegraph()


async def init_telegraph():
    """Nạp lại access_token Telegraph đã lưu (nếu có) thay vì luôn tạo
    account mới — giữ được quyền sửa các trang đã đăng ở lần chạy
    trước qua mọi lần Render redeploy/restart.

    Cố tình SỬA TRỰC TIẾP `telegraph_client.access_token` thay vì gán
    lại biến `telegraph_client` bằng 1 object Telegraph() mới: các
    module khác (VD jobs.py) đã `from ai_client import telegraph_client`
    lúc import — nếu gán lại biến ở đây, tham chiếu bên jobs.py vẫn
    trỏ tới object CŨ (Python bind tên biến tại thời điểm import, không
    tự cập nhật theo). Sửa thuộc tính trên cùng 1 object thì mọi nơi
    đã import đều thấy thay đổi.
    """
    saved = await settings_store.read()
    token = saved.get("telegraph_access_token")
    if token:
        telegraph_client.access_token = token
        logger.info("Đã nạp lại access_token Telegraph cũ (giữ quyền sửa bài đã đăng).")
        return
    try:
        await asyncio.to_thread(
            telegraph_client.create_account, short_name="LifeOS", author_name="Quản Gia Life-OS"
        )
        new_token = telegraph_client.get_access_token()

        def _mutate(data):
            data["telegraph_access_token"] = new_token
            return data

        await settings_store.update(_mutate)
        logger.info("Đã tạo account Telegraph mới và lưu lại access_token cho các lần chạy sau.")
    except Exception as e:
        logger.error("Không tạo được account Telegraph (bài trích sách/tin tức có thể lỗi): %s", e)


def call_gemini_robust(client_instance, prompt, model=GEMINI_MODEL, is_json=False):
    """(GIỮ NGUYÊN logic gốc — Phân luồng fallback khi 429/500/503)"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if attempt == 0:
                current_model = model
            elif attempt == 1:
                current_model = "gemini-flash-latest"
            else:
                current_model = "gemini-flash-lite-latest"

            res = client_instance.models.generate_content(
                model=current_model, contents=prompt
            ).text.strip()
            if is_json:
                res = res.replace("```json", "").replace("```", "").strip()
            return res
        except Exception as api_e:
            err_str = str(api_e)
            # BUG FIX (17/9, lần 5): thêm "404" vào điều kiện fallback.
            # Trước đây chỉ bắt 429/500/503 -- khi Google ngừng cấp 1
            # model cụ thể (như gemini-2.5-pro vừa bị khai tử), lỗi trả
            # về là 404 NOT_FOUND, KHÔNG rơi vào nhánh retry/fallback
            # này -> mọi lệnh dùng model đó (VD /deep, /pitch dùng
            # MODEL_PRO) lập tức báo lỗi thẳng cho sếp dù bot vẫn còn
            # model khác dùng được. Giữ NGUYÊN thứ tự cascade gốc
            # (model chỉ định -> gemini-flash-latest ->
            # gemini-flash-lite-latest), chỉ mở rộng thêm điều kiện
            # kích hoạt để bot tự chống chịu khi Google đổi/khai tử
            # model trong tương lai.
            if "500" in err_str or "503" in err_str or "429" in err_str or "404" in err_str:
                if attempt < max_retries - 1:
                    sys_time.sleep(1)  # Fast switch to fallback model
                    continue
                raise
            raise


async def call_gemini_async(prompt, model=GEMINI_MODEL, is_json=False):
    """Wrapper async cho call_gemini_robust.

    Đây là chỗ SỬA QUAN TRỌNG NHẤT so với bản gốc: bản gốc gọi
    call_gemini_robust (hàm blocking, có thể sleep(1) x2 lần retry)
    trực tiếp trong handler async -> trong lúc chờ Gemini trả lời
    hoặc chờ retry, TOÀN BỘ bot bị đơ, không nhận được tin nhắn / nút
    bấm nào khác từ bất kỳ ai. asyncio.to_thread chạy nó trong 1
    thread riêng, trả quyền điều khiển lại cho event loop ngay lập
    tức để bot vẫn phản hồi được các sự kiện khác song song.
    """
    return await asyncio.to_thread(call_gemini_robust, client, prompt, model, is_json)


def clean_for_telegram(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"^#{1,3}\s+(.*)", r"<b>\1</b>", text, flags=re.MULTILINE)
    text = text.replace("<br>", "\n").replace("```", "")
    return text


def parse_amount(amount_str: str) -> int:
    amount_str = amount_str.lower().replace(",", "").replace(".", "").strip()
    if "k" in amount_str:
        return int(float(amount_str.replace("k", "")) * 1_000)
    if "m" in amount_str or "tr" in amount_str:
        return int(float(amount_str.replace("m", "").replace("tr", "")) * 1_000_000)
    return int(amount_str)
