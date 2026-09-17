"""
Helper gửi tin nhắn Telegram: chống tràn ký tự (chunk) + xoá tin nhắn
"đang xử lý" 1 cách an toàn + đặt tên file tạm duy nhất cho mỗi request
+ sát trùng HTML để không bao giờ bị Telegram từ chối tin nhắn.
"""
import asyncio
import logging
import os
import re
import uuid

from telegram.error import BadRequest

logger = logging.getLogger(__name__)

MAX_LEN = 4000
TMP_DIR = "tmp"
os.makedirs(TMP_DIR, exist_ok=True)

# --- Sát trùng HTML cho Telegram ---
# Telegram Bot API (parse_mode='HTML') CHỈ hỗ trợ 1 tập thẻ rất hẹp.
# Gemini đôi khi phớt lờ chỉ dẫn trong prompt và tự chèn <h3>, <ul>,
# <li>, <p>... (hay gặp khi trả lời có cấu trúc, VD phân tích
# video/bài viết) -> Telegram từ chối thẳng cả tin nhắn với lỗi
# "Can't parse entities: unsupported start tag ...". Đây chính là lỗi
# sếp gặp phải. clean_for_telegram (ai_client.py) chỉ đổi markdown
# (**, #) sang HTML, KHÔNG lọc thẻ HTML lạ -> không đủ để chặn lỗi
# này. sanitize_telegram_html() dưới đây là lớp phòng thủ cuối cùng,
# áp dụng tự động bên trong send_chunked_message cho MỌI tin nhắn
# HTML, nên không phụ thuộc việc từng nơi gọi có nhớ "làm sạch" text
# trước hay không.
_ALLOWED_HTML_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "code", "pre", "a", "tg-spoiler", "tg-emoji", "blockquote",
}
_TAG_RE = re.compile(r"</?\s*([a-zA-Z][a-zA-Z0-9-]*)\b[^>]*>")
_ANY_TAG_RE = re.compile(r"<[^>]+>")


def sanitize_telegram_html(text: str) -> str:
    """Chuyển các thẻ HTML phổ biến mà Gemini hay 'lỡ' dùng về dạng
    Telegram chấp nhận được (giữ tối đa cấu trúc), sau đó XOÁ SẠCH bất
    kỳ thẻ nào còn lại không nằm trong whitelist — đảm bảo tin nhắn
    luôn gửi được, bất kể Gemini trả về thẻ gì đi nữa."""
    # 1) Ánh xạ các thẻ hay gặp sang định dạng tương đương Telegram hiểu
    text = re.sub(r"<h[1-6][^>]*>", "<b>", text, flags=re.IGNORECASE)
    text = re.sub(r"</h[1-6]>", "</b>\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "• ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(ul|ol)[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?div[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?span[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(table|tr|td|th|thead|tbody)[^>]*>", "", text, flags=re.IGNORECASE)

    # 2) Lưới an toàn cuối cùng: bất kỳ thẻ nào KHÔNG nằm trong
    #    whitelist đều bị xoá (giữ nguyên nội dung bên trong).
    def _strip_disallowed(m: re.Match) -> str:
        tag = m.group(1).lower()
        return m.group(0) if tag in _ALLOWED_HTML_TAGS else ""

    return _TAG_RE.sub(_strip_disallowed, text)


def strip_all_tags(text: str) -> str:
    """Bỏ hoàn toàn mọi thẻ HTML — dùng làm phương án dự phòng cuối
    cùng khi Telegram vẫn từ chối dù đã sanitize (VD thẻ mở/đóng lệch
    nhau khiến parser lỗi kiểu khác)."""
    return _ANY_TAG_RE.sub("", text)


async def _safe_send(reply_func, text: str, parse_mode):
    """Gửi 1 tin nhắn, có phương án dự phòng: nếu Telegram vẫn từ
    chối vì lỗi parse HTML (trường hợp hiếm, sau khi đã sanitize),
    gửi lại dưới dạng plain text thay vì để cả handler crash và hiện
    'Lỗi Server AI' cho sếp."""
    try:
        return await reply_func(text, parse_mode=parse_mode)
    except BadRequest as e:
        if parse_mode and "parse entities" in str(e).lower():
            logger.warning("Telegram từ chối HTML (%s) — gửi lại dạng plain text.", e)
            return await reply_func(strip_all_tags(text), parse_mode=None)
        raise


async def send_chunked_message(reply_func, text: str, parse_mode="HTML"):
    """(GIỮ NGUYÊN cơ chế gốc — chống tràn giới hạn ~4096 ký tự/tin
    nhắn của Telegram bằng cách cắt tại dấu xuống dòng gần nhất).

    So với bản trước, thêm 2 lớp an toàn khi parse_mode='HTML':
    1. sanitize_telegram_html() lọc thẻ lạ TRƯỚC khi cắt chunk (sửa
       đúng lỗi "unsupported start tag" sếp gặp).
    2. _safe_send() có phương án dự phòng gửi plain text nếu vẫn lỗi.

    Vẫn dùng asyncio.sleep (không phải time.sleep) giữa các chunk như
    bản đã sửa trước đó.
    """
    if parse_mode == "HTML":
        text = sanitize_telegram_html(text)

    if len(text) <= MAX_LEN:
        return await _safe_send(reply_func, text, parse_mode)

    parts = []
    remaining = text
    while remaining:
        if len(remaining) <= MAX_LEN:
            parts.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, MAX_LEN)
        if split_at == -1:
            split_at = MAX_LEN
        parts.append(remaining[:split_at])
        remaining = remaining[split_at:]

    last_msg = None
    for part in parts:
        last_msg = await _safe_send(reply_func, part, parse_mode)
        await asyncio.sleep(0.5)  # asyncio.sleep, không phải time.sleep
    return last_msg


async def safe_delete_message(context, chat_id, message):
    """Xoá tin nhắn 'đang xử lý' mà không văng lỗi nếu message=None
    hoặc tin đã bị xoá / Telegram lỗi tạm thời."""
    if message is None:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
    except Exception as e:
        logger.debug("Không xoá được message %s: %s", getattr(message, "message_id", "?"), e)


def unique_temp_path(prefix: str, suffix: str) -> str:
    """Tạo đường dẫn file tạm DUY NHẤT cho mỗi request, tránh 2
    request xử lý gần như đồng thời ghi đè file của nhau."""
    return os.path.join(TMP_DIR, f"{prefix}_{uuid.uuid4().hex}{suffix}")
