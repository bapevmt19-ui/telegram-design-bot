"""Phân tích video Telegram (video thường / video forward) bằng Gemini."""
import asyncio
import logging
import os
import time as sys_time

from telegram import Update
from telegram.ext import ContextTypes

from ai_client import call_gemini_async, clean_for_telegram, client
from storage import memory_store
from telegram_helpers import safe_delete_message, send_chunked_message, unique_temp_path

logger = logging.getLogger(__name__)

# Giới hạn tải file của Telegram Bot API (bot.getFile) là ~20MB — nếu
# video lớn hơn, download_to_drive sẽ lỗi. Chặn sớm để báo lỗi rõ
# ràng thay vì để crash giữa chừng.
MAX_VIDEO_BYTES = 20 * 1024 * 1024
# Video cần Gemini xử lý (encode) sau khi upload trước khi dùng được
# trong generate_content — khác với ảnh/audio thường ACTIVE ngay.
# Timeout để tránh treo vô hạn nếu video quá dài/nặng.
FILE_ACTIVE_TIMEOUT_SEC = 90


def _upload_and_wait_active(file_path: str):
    """Upload video lên Gemini Files API rồi CHỜ tới khi state=ACTIVE.

    Đây là hàm BLOCKING (đồng bộ) — luôn phải gọi qua
    asyncio.to_thread, không được gọi trực tiếp trong handler async.
    """
    uploaded = client.files.upload(file=file_path)
    start = sys_time.time()
    while uploaded.state.name == "PROCESSING":
        if sys_time.time() - start > FILE_ACTIVE_TIMEOUT_SEC:
            raise TimeoutError("Gemini xử lý video quá lâu (vượt timeout).")
        sys_time.sleep(2)
        uploaded = client.files.get(name=uploaded.name)
    if uploaded.state.name != "ACTIVE":
        raise RuntimeError(f"Video xử lý thất bại (trạng thái trả về: {uploaded.state.name}).")
    return uploaded


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    video = update.message.video
    if video is None and update.message.document is not None:
        # Một số video forward (VD từ TikTok qua bên thứ 3) đến dưới
        # dạng "document" có mime type video/*.
        doc = update.message.document
        if (doc.mime_type or "").startswith("video/"):
            video = doc
    if video is None:
        return

    status_msg = None
    file_path = None
    try:
        if video.file_size and video.file_size > MAX_VIDEO_BYTES:
            await update.message.reply_text(
                "⚠️ Video quá lớn (giới hạn tải của Telegram Bot API là ~20MB). "
                "Sếp thử nén nhỏ lại hoặc cắt ngắn video rồi gửi lại nhé."
            )
            return

        status_msg = await send_chunked_message(
            update.message.reply_text, "🎬 <i>Đang tải và phân tích video (có thể mất 30-60s)...</i>"
        )

        tg_file = await context.bot.get_file(video.file_id)
        file_path = unique_temp_path("video", ".mp4")
        await tg_file.download_to_drive(file_path)

        memory = await memory_store.read()
        memory_ctx = "\n".join(f"- {r}" for r in memory.get("rules", [])) or "Không có."

        # Quan trọng: nếu sếp gửi video kèm caption (thay vì gửi video
        # rồi nhắn tin riêng ngay sau đó), bot sẽ biết chính xác cần
        # phân tích theo yêu cầu nào. 2 tin nhắn tách rời (video không
        # caption + text "Phân tích video này" gửi sau) không liên kết
        # được với nhau ở phía Telegram.
        caption = (update.message.caption or "").strip() or "Tóm tắt và phân tích nội dung chính của video này"

        uploaded_video = await asyncio.to_thread(_upload_and_wait_active, file_path)

        prompt = f"""Xem kỹ video này và thực hiện yêu cầu sau của người dùng: "{caption}".
        Tóm tắt nội dung chính, các điểm đáng chú ý, và (nếu phù hợp) rút ra bài học/ứng dụng thực tế.
        Trình bày bằng HTML chuẩn Telegram: CHỈ được dùng <b> và <i>, TUYỆT ĐỐI KHÔNG dùng markdown (# hay **)
        và KHÔNG dùng các thẻ HTML khác như <h1>-<h6>, <ul>, <li>, <p>, <div>.
        Luôn tuân thủ bộ nhớ lõi sau nếu có liên quan: {memory_ctx}"""

        res = await call_gemini_async([uploaded_video, prompt])
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await send_chunked_message(update.message.reply_text, clean_for_telegram(res))
    except TimeoutError as e:
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await update.message.reply_text(f"⏱️ {e} Sếp thử lại với video ngắn hơn nhé.")
    except Exception as e:
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await update.message.reply_text(f"⚠️ Lỗi phân tích video: {e}")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
