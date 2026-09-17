"""Sao lưu dữ liệu: /export_data (thủ công) + weekly_backup_job (tự
động hàng tuần vào kênh riêng CHAT_ID_BACKUP).

Nâng cấp (17/9, lần 7): dữ liệu đã bền vững nhờ Postgres (A2), nhưng
vẫn nên có 1 lớp dự phòng nếu tài khoản Postgres gặp sự cố (xoá nhầm,
hết hạn, đổi provider...). Gộp toàn bộ các "kho" (store) hiện có thành
1 file JSON duy nhất, gửi dạng file đính kèm — không phải dữ liệu
sống, chỉ là ảnh chụp tại thời điểm export.
"""
import json
import logging
import os
from datetime import datetime

import pytz
from telegram import Update
from telegram.ext import ContextTypes

from config import CHAT_ID_BACKUP
from storage import (
    content_history_store,
    finance_store,
    health_store,
    ideas_store,
    memory_store,
    nutrition_store,
    reminders_store,
    todo_store,
)
from telegram_helpers import unique_temp_path

logger = logging.getLogger(__name__)
VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")

_EXPORT_STORES = {
    "finance": finance_store,
    "todos": todo_store,
    "ideas": ideas_store,
    "reminders": reminders_store,
    "health": health_store,
    "nutrition": nutrition_store,
    "memory": memory_store,
    "content_history": content_history_store,
}


async def _build_export_path() -> str:
    data = {}
    for key, store in _EXPORT_STORES.items():
        try:
            data[key] = await store.read()
        except Exception as e:
            logger.error("Lỗi đọc kho '%s' lúc export dữ liệu: %s", key, e)
            data[key] = {"_loi_khong_doc_duoc": str(e)}

    path = unique_temp_path("lifeos_backup", ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


async def export_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sao lưu thủ công — gửi ngay vào chat vừa gõ lệnh (không nhất
    thiết phải là kênh backup, để tiện xem nhanh khi cần)."""
    path = await _build_export_path()
    try:
        today_str = datetime.now(VN_TZ).strftime("%Y-%m-%d")
        with open(path, "rb") as f:
            await context.bot.send_document(
                chat_id=update.message.chat_id,
                document=f,
                filename=f"lifeos_backup_{today_str}.json",
                caption="📦 Bản sao lưu dữ liệu bot (thủ công).",
            )
    finally:
        if os.path.exists(path):
            os.remove(path)


async def weekly_backup_job(context: ContextTypes.DEFAULT_TYPE):
    """Tự động chạy hàng tuần (xem main.py) — gửi vào kênh riêng
    CHAT_ID_BACKUP, tách khỏi chat cá nhân để tránh loạn tin nhắn."""
    path = await _build_export_path()
    try:
        today_str = datetime.now(VN_TZ).strftime("%Y-%m-%d")
        with open(path, "rb") as f:
            await context.bot.send_document(
                chat_id=CHAT_ID_BACKUP,
                document=f,
                filename=f"lifeos_backup_{today_str}.json",
                caption="📦 Bản sao lưu dữ liệu tự động hàng tuần.",
            )
    except Exception as e:
        logger.error("Lỗi gửi backup tự động hàng tuần: %s", e)
    finally:
        if os.path.exists(path):
            os.remove(path)
