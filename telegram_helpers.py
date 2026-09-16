"""
Helper gửi tin nhắn Telegram: chống tràn ký tự (chunk) + xoá tin nhắn
"đang xử lý" 1 cách an toàn + đặt tên file tạm duy nhất cho mỗi request.
"""
import asyncio
import logging
import os
import uuid

logger = logging.getLogger(__name__)

MAX_LEN = 4000
TMP_DIR = "tmp"
os.makedirs(TMP_DIR, exist_ok=True)


async def send_chunked_message(reply_func, text: str, parse_mode="HTML"):
    """(GIỮ NGUYÊN cơ chế gốc — chống tràn giới hạn ~4096 ký tự/tin
    nhắn của Telegram bằng cách cắt tại dấu xuống dòng gần nhất).

    Chỉ sửa 1 lỗi: dùng `asyncio.sleep` thay vì `time.sleep` (bản gốc)
    giữa các lần gửi chunk — time.sleep là hàm đồng bộ, chặn cứng
    event loop, khiến cả bot bị đơ mỗi khi gửi 1 tin nhắn dài nhiều
    chunk (ví dụ các bài phân tích /deep, /pitch dài).
    """
    if len(text) <= MAX_LEN:
        return await reply_func(text, parse_mode=parse_mode)

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
        last_msg = await reply_func(part, parse_mode=parse_mode)
        await asyncio.sleep(0.5)  # BUG FIX: time.sleep -> asyncio.sleep
    return last_msg


async def safe_delete_message(context, chat_id, message):
    """Xoá tin nhắn 'đang xử lý' mà không văng lỗi nếu message=None
    (chưa kịp tạo do lỗi sớm hơn) hoặc tin đã bị xoá / Telegram lỗi
    tạm thời.

    Bản gốc gọi `context.bot.delete_message(message_id=status_msg.message_id)`
    thẳng trong khối except mà KHÔNG kiểm tra status_msg có tồn tại
    hay không. Nếu send_chunked_message ở trên đó tự nó ném lỗi
    (VD mất mạng khi gửi tin nhắn "đang xử lý"), status_msg chưa từng
    được gán -> NameError mới bị ném ra NGAY TRONG khối except, che
    mất lỗi gốc và khiến user không nhận được thông báo lỗi nào cả.
    """
    if message is None:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
    except Exception as e:
        logger.debug("Không xoá được message %s: %s", getattr(message, "message_id", "?"), e)


def unique_temp_path(prefix: str, suffix: str) -> str:
    """Tạo đường dẫn file tạm DUY NHẤT cho mỗi request.

    Bản gốc dùng tên cố định (temp_photo.jpg, temp_voice.ogg,
    chart.png, vocab.mp3) dùng chung cho MỌI request. Nếu 2 ảnh/voice
    được xử lý gần như đồng thời (2 người dùng, hoặc 1 người gửi 2
    ảnh liên tiếp trong lúc ảnh trước còn đang được AI phân tích),
    file sau có thể ghi đè lên file trước ngay khi nó đang được đọc
    -> phân tích sai/lẫn dữ liệu giữa các request. File cũng không
    bao giờ được các handler gốc dọn dẹp.
    """
    return os.path.join(TMP_DIR, f"{prefix}_{uuid.uuid4().hex}{suffix}")
