"""
Các "hành động lõi" (core actions) được dùng chung bởi CẢ lệnh gõ tay
(command handlers) VÀ lệnh bằng giọng nói (voice handler) — tránh lặp
code giữa 2 luồng nhập liệu (bản gốc từng lặp gần như y hệt logic
này ở cả /spend, /todo và trong handle_voice).
"""
import logging
from datetime import datetime

import pytz

from ai_client import call_gemini_async, clean_for_telegram
from storage import finance_store, ideas_store, reminders_store, todo_store
from telegram_helpers import send_chunked_message

logger = logging.getLogger(__name__)
VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")


async def execute_spend(chat_id, context, amount, reason):
    finance = await finance_store.read()
    if not finance.get("timo_confirmed"):
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Sếp chưa bấm nút xác nhận chia tiền vào hũ Timo đầu tháng!",
        )
        return

    category = "Khac"
    budget_keys = list(finance.get("budgets", {}).keys())
    if budget_keys:
        prompt = f"""Phân loại chi tiêu: "{reason}".
        Hãy chọn 1 danh mục phù hợp nhất từ danh sách sau: {', '.join(budget_keys)}.
        Chỉ trả về ĐÚNG 1 từ là tên danh mục, không giải thích. Nếu không khớp cái nào, trả về Khac."""
        try:
            # BUG FIX: bản gốc gọi client.models.generate_content(...)
            # trực tiếp ở đây, KHÔNG qua call_gemini_robust -> việc
            # phân loại chi tiêu bằng AI không có cơ chế retry/fallback
            # 429 dù bot đã xây riêng cơ chế đó. Sửa để nhất quán.
            category = (await call_gemini_async(prompt)).strip()
            if category not in budget_keys:
                category = "Khac"
        except Exception as e:
            logger.warning("Không phân loại được chi tiêu bằng AI: %s", e)
            category = "Khac"

    def _mutate(data):
        data.setdefault("expenses", []).append(
            {
                "date": datetime.now(VN_TZ).strftime("%Y-%m-%d"),
                "amount": amount,
                "reason": reason,
                "category": category,
            }
        )
        return data

    # Đọc-sửa-ghi trong 1 lock: 2 khoản chi phát sinh gần như đồng
    # thời (VD: gõ lệnh + voice cùng lúc) sẽ không ghi đè mất nhau.
    finance = await finance_store.update(_mutate)

    current_month = datetime.now(VN_TZ).strftime("%Y-%m")
    month_expenses = [e for e in finance["expenses"] if e["date"].startswith(current_month)]
    total_spent = sum(e["amount"] for e in month_expenses)
    total_budget = sum(finance["budgets"].values()) if finance["budgets"] else finance["salary"]
    global_remaining = total_budget - total_spent

    msg = (
        f"💸 <b>ĐÃ TRỪ TIỀN:</b>\n▪️ Số tiền: {amount:,.0f} VNĐ\n"
        f"▪️ Mục đích: {reason}\n▪️ Phân loại AI: <b>{category}</b>\n\n"
    )

    if category != "Khac" and category in finance["budgets"]:
        cat_budget = finance["budgets"][category]
        cat_spent = sum(e["amount"] for e in month_expenses if e.get("category") == category)
        cat_remaining = cat_budget - cat_spent
        msg += f"📦 <b>Quỹ {category}:</b> Còn lại {cat_remaining:,.0f} / {cat_budget:,.0f} VNĐ\n"
        if cat_remaining < 0:
            msg += f"🚨 <b>CẢNH BÁO: SẾP ĐÃ TIÊU ÂM QUỸ {category.upper()}!</b>\n\n"

    msg += f"💰 <b>TỔNG TIỀN CÒN LẠI THÁNG NÀY:</b> {global_remaining:,.0f} VNĐ"
    if global_remaining < 0:
        msg += "\n\n💀 <b>BÁO ĐỘNG ĐỎ: SẾP ĐÃ TIÊU ÂM TOÀN BỘ NGÂN SÁCH!</b>"

    async def _rep(t, parse_mode="HTML"):
        return await context.bot.send_message(chat_id=chat_id, text=t, parse_mode=parse_mode)

    await send_chunked_message(_rep, clean_for_telegram(msg))


async def execute_todo(chat_id, context, task_text):
    task_id = str(int(datetime.now().timestamp()))

    def _mutate(data):
        data.setdefault("tasks", []).append({"id": task_id, "text": task_text, "status": "pending"})
        return data

    await todo_store.update(_mutate)

    async def _rep(t, parse_mode="HTML"):
        return await context.bot.send_message(chat_id=chat_id, text=t, parse_mode=parse_mode)

    await send_chunked_message(_rep, f"📝 Đã ghi nhận việc: <b>{task_text}</b>")


async def execute_idea(chat_id, context, idea_text):
    def _mutate(data):
        data.setdefault("ideas", []).append({"date": datetime.now().strftime("%Y-%m-%d"), "text": idea_text})
        return data

    await ideas_store.update(_mutate)

    async def _rep(t, parse_mode="HTML"):
        return await context.bot.send_message(chat_id=chat_id, text=t, parse_mode=parse_mode)

    await send_chunked_message(
        _rep, "💡 <b>Đã cất ý tưởng này vào Bộ Não Thứ 2!</b>\n<i>(Sếp có thể hỏi lại bất cứ lúc nào)</i>"
    )


# --- Hệ thống báo thức / nhắc nhở ---
async def send_reminder_job(context):
    data = context.job.data
    task_id, chat_id, task_text = data["id"], data["chat_id"], data["text"]

    def _mutate(reminders):
        for r in reminders.get("reminders", []):
            if r["id"] == task_id:
                r["status"] = "done"
        return reminders

    await reminders_store.update(_mutate)

    async def _rep(t, parse_mode="HTML"):
        return await context.bot.send_message(chat_id=chat_id, text=t, parse_mode=parse_mode)

    await send_chunked_message(_rep, f"🔔 <b>BÁO THỨC / NHẮC NHỞ:</b>\nSếp ơi, đến giờ: <b>{task_text}</b>")


async def add_reminder(job_queue, chat_id, remind_time: datetime, task_text: str):
    task_id = str(int(datetime.now().timestamp() * 1000))

    def _mutate(data):
        data.setdefault("reminders", []).append(
            {
                "id": task_id,
                "chat_id": chat_id,
                "time": remind_time.strftime("%Y-%m-%d %H:%M"),
                "text": task_text,
                "status": "pending",
            }
        )
        return data

    await reminders_store.update(_mutate)
    job_queue.run_once(
        send_reminder_job, when=remind_time, data={"id": task_id, "chat_id": chat_id, "text": task_text}
    )


async def load_pending_reminders(job_queue):
    """Nạp lại các reminder còn dang dở sau khi bot khởi động lại.

    Được gọi từ `post_init` của Application (xem main.py) — cách làm
    chuẩn của PTB v20, thay vì gọi hàm đồng bộ giữa chừng main() như
    bản gốc.
    """
    now = datetime.now(VN_TZ)

    def _mutate(data):
        for r in data.get("reminders", []):
            if r["status"] == "pending":
                try:
                    r_time = VN_TZ.localize(datetime.strptime(r["time"], "%Y-%m-%d %H:%M"))
                    if r_time > now:
                        job_queue.run_once(
                            send_reminder_job,
                            when=r_time,
                            data={"id": r["id"], "chat_id": r["chat_id"], "text": r["text"]},
                        )
                    else:
                        r["status"] = "missed"
                except Exception as e:
                    logger.warning("Reminder lỗi định dạng thời gian: %s", e)
        return data

    await reminders_store.update(_mutate)
