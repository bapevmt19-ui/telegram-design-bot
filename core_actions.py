"""
Các "hành động lõi" (core actions) được dùng chung bởi CẢ lệnh gõ tay
(command handlers) VÀ lệnh bằng giọng nói (voice handler) — tránh lặp
code giữa 2 luồng nhập liệu (bản gốc từng lặp gần như y hệt logic
này ở cả /spend, /todo và trong handle_voice).
"""
import logging
import re
from datetime import datetime, timedelta

import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ai_client import call_gemini_async, clean_for_telegram
from config import REMINDER_FOLLOWUP_MINUTES
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


# Nâng cấp (17/9, lần 7): "nhắc việc nâng cao" — /todo giờ nhận thêm 2
# thẻ tuỳ chọn viết chèn trong nội dung, không cần đúng vị trí:
#   !gấp        -> đánh dấu việc ưu tiên cao, được nhắc dày hơn
#                  (mỗi 2 tiếng giờ hành chính thay vì 3 lần cố định/ngày).
#   hạn:DD/MM   -> gắn hạn chót, tự in đậm cảnh báo khi tới/quá hạn.
# VD: /todo Chuẩn bị hợp đồng hạn:20/09 !gấp
_URGENT_TAG = "!gấp"
_DEADLINE_TAG_RE = re.compile(r"hạn:(\d{1,2}/\d{1,2})")


def _parse_todo_tags(raw_text: str) -> tuple[str, bool, str | None]:
    """Tách thẻ !gấp / hạn:DD/MM khỏi nội dung việc cần làm, trả về
    (nội_dung_đã_làm_sạch, có_gấp, hạn_chót_hoặc_None)."""
    text = raw_text
    urgent = _URGENT_TAG in text
    if urgent:
        text = text.replace(_URGENT_TAG, "")

    deadline = None
    m = _DEADLINE_TAG_RE.search(text)
    if m:
        deadline = m.group(1)
        text = text.replace(m.group(0), "")

    text = re.sub(r"\s+", " ", text).strip()
    return text, urgent, deadline


def is_deadline_overdue(deadline_str: str | None) -> bool:
    """True nếu hạn:DD/MM đã tới hôm nay hoặc đã qua (so theo năm hiện
    tại). Dữ liệu sai định dạng/ngày không hợp lệ -> coi như chưa quá
    hạn (an toàn hơn là báo nhầm)."""
    if not deadline_str:
        return False
    try:
        day, month = map(int, deadline_str.split("/"))
        today = datetime.now(VN_TZ).date()
        deadline_date = today.replace(month=month, day=day)
        return deadline_date <= today
    except Exception:
        return False


def render_tasks_message(pending_tasks: list) -> tuple[str, list]:
    """Dựng (text, keyboard) hiển thị danh sách việc còn tồn đọng —
    dùng chung giữa lệnh /tasks gõ tay (handlers/todo.py) và các job tự
    động nhắc việc định kỳ (jobs.py), để 2 nơi không lặp lại logic định
    dạng/gắn nút. Mỗi việc luôn có nút "✅ Xong" RIÊNG gắn theo đúng
    task['id'] của nó — bấm xong việc nào chỉ đánh dấu đúng việc đó,
    các việc còn lại trong danh sách không hề bị ảnh hưởng."""
    today = datetime.now(VN_TZ).date()
    msg = "📝 <b>DANH SÁCH CÔNG VIỆC CHƯA LÀM:</b>\n\n"
    keyboard, row = [], []
    for i, t in enumerate(pending_tasks):
        line = f"<b>{i + 1}.</b> {t['text']}"

        tags = []
        if t.get("urgent"):
            tags.append("⚡ gấp")
        deadline = t.get("deadline")
        if deadline:
            tags.append(f"⚠️ QUÁ HẠN {deadline}" if is_deadline_overdue(deadline) else f"📅 hạn {deadline}")
        try:
            created = datetime.strptime(t.get("created", ""), "%Y-%m-%d").date()
            days_pending = (today - created).days
            if days_pending >= 3:
                tags.append(f"🕒 tồn {days_pending} ngày")
        except Exception:
            pass
        if tags:
            line += " (" + ", ".join(tags) + ")"

        msg += line + "\n"
        row.append(InlineKeyboardButton(f"✅ Xong {i + 1}", callback_data=f"tododone_{t['id']}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return msg, keyboard


async def execute_todo(chat_id, context, task_text):
    clean_text, urgent, deadline = _parse_todo_tags(task_text)
    task_id = str(int(datetime.now().timestamp()))

    def _mutate(data):
        data.setdefault("tasks", []).append(
            {
                "id": task_id,
                "text": clean_text,
                "status": "pending",
                "urgent": urgent,
                "deadline": deadline,
                "created": datetime.now(VN_TZ).strftime("%Y-%m-%d"),
            }
        )
        return data

    await todo_store.update(_mutate)

    tag_note = ""
    if urgent:
        tag_note += " ⚡ (gấp — nhắc mỗi 2 tiếng giờ hành chính)"
    if deadline:
        tag_note += f" 📅 (hạn {deadline})"

    async def _rep(t, parse_mode="HTML"):
        return await context.bot.send_message(chat_id=chat_id, text=t, parse_mode=parse_mode)

    await send_chunked_message(_rep, f"📝 Đã ghi nhận việc: <b>{clean_text}</b>{tag_note}")


async def execute_idea(chat_id, context, idea_text):
    # Nâng cấp (18/9, lần 9): gắn id riêng cho mỗi ý tưởng — cần thiết
    # để apply_idea_action() bên dưới biết chính xác ý tưởng nào cần
    # sửa/xoá khi handle_chat_text (handlers/ai_chat.py) phát hiện yêu
    # cầu sửa/xoá qua chat tự do.
    idea_id = str(int(datetime.now().timestamp() * 1000))

    def _mutate(data):
        data.setdefault("ideas", []).append(
            {"id": idea_id, "date": datetime.now().strftime("%Y-%m-%d"), "text": idea_text}
        )
        return data

    await ideas_store.update(_mutate)

    async def _rep(t, parse_mode="HTML"):
        return await context.bot.send_message(chat_id=chat_id, text=t, parse_mode=parse_mode)

    await send_chunked_message(
        _rep, "💡 <b>Đã cất ý tưởng này vào Bộ Não Thứ 2!</b>\n<i>(Sếp có thể hỏi lại bất cứ lúc nào)</i>"
    )


# Nâng cấp (18/9, lần 9): trước đây khi sếp chat tự do bảo "bỏ X đi",
# Gemini chỉ TRẢ LỜI như đã sửa xong (không hề có cơ chế nào thực sự
# chỉnh sửa ideas_store) — ý tưởng cũ vẫn nguyên vẹn, nên lần sau được
# nạp lại làm ngữ cảnh là nội dung "đã xoá" lại xuất hiện y như cũ.
# apply_idea_action() là hàm THỰC SỰ mutate dữ liệu, được gọi từ
# handle_chat_text sau khi phát hiện dòng lệnh ẩn "IDEA_ACTION|..."
# trong câu trả lời của Gemini (cùng kiểu marker-line như
# AUDIO_VOCAB|/TOPIC_NAME|/BOOK_TITLE| đã dùng ở jobs.py) — không cần
# thêm lệnh "/" nào, sếp vẫn gõ chat bình thường.
async def apply_idea_action(action: str, idea_id: str, new_text: str = "") -> bool:
    """Xoá hẳn (action="DELETE") hoặc thay toàn bộ nội dung
    (action="EDIT", cần new_text) của 1 ý tưởng theo đúng id. Trả về
    True nếu tìm thấy và áp dụng thành công; False nếu không khớp id
    nào (VD Gemini đoán nhầm/id đã bị xoá trước đó) — gọi nơi dùng tự
    quyết định có cần log cảnh báo hay không."""
    found = False

    def _mutate(data):
        nonlocal found
        ideas = data.get("ideas", [])
        if action == "DELETE":
            new_list = [i for i in ideas if i.get("id") != idea_id]
            found = len(new_list) != len(ideas)
            data["ideas"] = new_list
        elif action == "EDIT" and new_text:
            for i in ideas:
                if i.get("id") == idea_id:
                    i["text"] = new_text
                    found = True
                    break
        return data

    await ideas_store.update(_mutate)
    return found


# --- Hệ thống báo thức / nhắc nhở ---
# Nâng cấp (17/9, lần 7): trước đây tin nhắn nhắc nhở gửi xong là tự
# đánh dấu "done" ngay lập tức — không hề biết sếp có THỰC SỰ đọc/làm
# hay không, và im lặng luôn nếu sếp lỡ quên. Giờ trạng thái chuyển
# thành "sent" (không phải "done"), kèm nút "✅ Đã xong" để sếp tự xác
# nhận; nếu sau REMINDER_FOLLOWUP_MINUTES phút vẫn chưa bấm, bot tự
# nhắc lại thêm đúng 1 lần nữa (send_reminder_followup_job).
async def send_reminder_job(context):
    data = context.job.data
    task_id, chat_id, task_text = data["id"], data["chat_id"], data["text"]

    def _mutate(reminders):
        for r in reminders.get("reminders", []):
            if r["id"] == task_id:
                r["status"] = "sent"
        return reminders

    await reminders_store.update(_mutate)

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Đã xong", callback_data=f"remind_done_{task_id}")]])

    async def _rep(t, parse_mode="HTML"):
        return await context.bot.send_message(chat_id=chat_id, text=t, parse_mode=parse_mode, reply_markup=keyboard)

    await send_chunked_message(_rep, f"🔔 <b>BÁO THỨC / NHẮC NHỞ:</b>\nSếp ơi, đến giờ: <b>{task_text}</b>")

    context.job_queue.run_once(
        send_reminder_followup_job,
        when=timedelta(minutes=REMINDER_FOLLOWUP_MINUTES),
        data={"id": task_id, "chat_id": chat_id, "text": task_text},
        name=f"remind_followup_{task_id}",
    )


async def send_reminder_followup_job(context):
    """Nhắc lại ĐÚNG 1 LẦN nếu sau REMINDER_FOLLOWUP_MINUTES phút sếp
    vẫn chưa bấm "✅ Đã xong" (trạng thái vẫn còn "sent"). Nếu đã xác
    nhận xong rồi (status="done") thì im lặng, không làm phiền thêm."""
    data = context.job.data
    task_id, chat_id, task_text = data["id"], data["chat_id"], data["text"]

    reminders = await reminders_store.read()
    current = next((r for r in reminders.get("reminders", []) if r["id"] == task_id), None)
    if not current or current.get("status") != "sent":
        return

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Đã xong", callback_data=f"remind_done_{task_id}")]])

    async def _rep(t, parse_mode="HTML"):
        return await context.bot.send_message(chat_id=chat_id, text=t, parse_mode=parse_mode, reply_markup=keyboard)

    await send_chunked_message(
        _rep, f"🔁 <b>NHẮC LẠI:</b> Sếp vẫn chưa xác nhận xong việc:\n<b>{task_text}</b>"
    )


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
            elif r["status"] == "sent":
                # Bot đã gửi nhắc nhở này rồi nhưng restart trước khi
                # kịp bắn lần "nhắc lại" (job followup chỉ nằm trong bộ
                # nhớ, không bền qua restart như job_queue nói chung) —
                # đặt lại followup tính từ lúc bot vừa khởi động lại,
                # thay vì bỏ quên hẳn nhắc nhở này.
                job_queue.run_once(
                    send_reminder_followup_job,
                    when=timedelta(minutes=REMINDER_FOLLOWUP_MINUTES),
                    data={"id": r["id"], "chat_id": r["chat_id"], "text": r["text"]},
                    name=f"remind_followup_{r['id']}",
                )
        return data

    await reminders_store.update(_mutate)
