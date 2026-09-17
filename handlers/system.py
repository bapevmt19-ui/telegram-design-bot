"""Lệnh hệ thống: /start, /help.

Bản gốc không có 2 lệnh này — người dùng mới (hoặc chính sếp sau một
thời gian không dùng) mở chat với bot sẽ không biết bot làm được gì,
cũng không có gì hiện ra khi gõ "/" trong Telegram (vì chưa từng gọi
set_my_commands — xem post_init trong main.py).
"""
from telegram import Update
from telegram.ext import ContextTypes

HELP_TEXT = """🤖 <b>Quản Gia Life-OS — Danh sách lệnh</b>

💰 <b>Tài chính</b>
/salary &lt;số tiền&gt; — khai báo lương tháng
/budget &lt;tên&gt; &lt;số tiền&gt; — đặt ngân sách theo danh mục
/spend &lt;số tiền&gt; &lt;lý do&gt; — ghi chi tiêu (tự phân loại bằng AI)
/report — xem báo cáo chi tiêu tháng này
/goal — theo dõi mục tiêu tài chính

✅ <b>Công việc</b>
/todo &lt;việc cần làm&gt; — thêm việc
/tasks — xem danh sách việc
/remind &lt;thời gian&gt; &lt;nội dung&gt; — đặt nhắc nhở

🧠 <b>AI &amp; sức khoẻ</b>
/learn &lt;chủ đề&gt; — học nhanh 1 chủ đề
/deep &lt;câu hỏi&gt; — hỏi sâu, dùng model mạnh hơn
/pitch &lt;ý tưởng&gt; — phản biện/góp ý ý tưởng
/healthsetup — khai báo thông tin sức khoẻ
/food &lt;món ăn&gt; — tra cứu dinh dưỡng
/cook &lt;nguyên liệu&gt; — gợi ý món ăn

📎 <b>Khác</b>
Gửi ảnh/voice/video kèm caption — bot tự phân tích bằng Gemini.
/push — kích hoạt thủ công bản tin định kỳ (tin tức/cheat sheet/sách)
/start, /help — xem lại hướng dẫn này

<i>Chỉ chat_id đã được cấp phép mới dùng được bot (xem ALLOWED_CHAT_IDS).</i>"""


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào sếp! Em là Quản Gia Life-OS, sẵn sàng phục vụ.\n\n"
        "Gõ /help để xem đầy đủ danh sách lệnh.",
        parse_mode="HTML",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")
