"""Lệnh hệ thống: /start, /help.

Bản gốc không có 2 lệnh này — người dùng mới (hoặc chính sếp sau một
thời gian không dùng) mở chat với bot sẽ không biết bot làm được gì,
cũng không có gì hiện ra khi gõ "/" trong Telegram (vì chưa từng gọi
set_my_commands — xem post_init trong main.py).
"""
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from core_actions import execute_undo

# Nâng cấp (18/9, lần 11 — gói miễn phí): menu nút bấm nhanh (persistent
# reply keyboard) cho các lệnh KHÔNG cần thêm tham số — bấm nút coi như
# gõ đúng lệnh đó rồi gửi, đỡ phải nhớ/gõ tay. Gửi kèm mỗi lần /start
# (Telegram tự giữ nguyên bàn phím này cho các tin nhắn sau, tới khi bị
# thay bằng bàn phím khác).
QUICK_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["/tasks", "/report", "/remind_list"],
        ["/export_data", "/help"],
    ],
    resize_keyboard=True,
)

# Nâng cấp (17/9, lần 7): thêm VÍ DỤ CỤ THỂ cho từng lệnh (theo yêu
# cầu của sếp) — trước đây chỉ ghi mẫu cú pháp trừu tượng
# (VD "/salary <số tiền>"), mỗi lần quên cú pháp thật vẫn phải hỏi lại.
# Giờ mỗi lệnh có 1 ví dụ gõ thật, xem lại bằng /help bất cứ lúc nào.
HELP_TEXT = """🤖 <b>Quản Gia Life-OS — Danh sách lệnh</b>

💰 <b>Tài chính</b>
/salary 20m — khai báo lương tháng (20m = 20 triệu, cũng ghi được 20000000)
/budget An_uong 3m — đặt ngân sách 3 triệu cho hũ "An uong"
/spend 50k Ăn trưa — ghi chi 50k, bot tự phân loại danh mục bằng AI
/report — xem biểu đồ tròn phân bổ chi tiêu tháng này
/report_excel — xuất chi tiêu tháng này ra file Excel dạng bảng (có cột Ngày/Số tiền/Danh mục/Lý do + dòng tổng)
/goal Mua xe 100m — ước tính còn bao lâu gom đủ 100 triệu cho mục tiêu "Mua xe"

✅ <b>Công việc</b>
/todo Chuẩn bị hợp đồng hạn:20/09 !gấp — thêm việc; 2 thẻ hạn:DD/MM và !gấp đều TUỲ CHỌN, gõ chèn ở đâu trong câu cũng được
/tasks — xem danh sách việc còn tồn đọng, mỗi việc có nút "✅ Xong" riêng
<i>(việc gắn !gấp hoặc đã tới/quá hạn được tự nhắc mỗi 2 tiếng giờ hành chính 8h-18h; việc thường được nhắc 3 lần/ngày lúc 9h00, 13h30, 17h00)</i>

⏰ <b>Nhắc nhở</b>
/remind 15:30 Họp team — nhắc 1 lần lúc 15:30 (hôm nay, hoặc mai nếu đã qua giờ đó)
/remind 25/09 15:00 Họp khách hàng — nhắc 1 lần đúng ngày 25/09 lúc 15:00
/remind_daily 07:00 Uống thuốc huyết áp — nhắc lặp lại HÀNG NGÀY lúc 7h00
/remind_every 2h Uống nước — nhắc lặp lại MỖI 2 tiếng
/remind_list — xem các nhắc lặp lại đang chạy (kèm số thứ tự)
/remind_stop 1 — tắt nhắc lặp lại số 1 trong danh sách /remind_list
<i>(mỗi lần nhắc đều có nút "✅ Đã xong"; riêng /remind nếu 30 phút sau vẫn chưa bấm sẽ tự nhắc lại thêm 1 lần)</i>

🧠 <b>AI &amp; sức khoẻ</b>
/learn Lãi kép — học nhanh 1 chủ đề
/deep Có nên đầu tư crypto lúc này? — hỏi sâu, dùng model AI mạnh hơn
/pitch Ý tưởng mở quán cafe sách — nhờ AI phản biện/góp ý 1 ý tưởng
/healthsetup — khai báo cân nặng/chiều cao/mục tiêu sức khoẻ (bot hỏi thêm chi tiết)
/food Phở bò — tra cứu thông tin dinh dưỡng của món ăn
/cook Trứng, cà chua, thịt băm — gợi ý món ăn từ nguyên liệu đang có

📎 <b>Khác</b>
Gửi ảnh/voice/video kèm caption — bot tự phân tích bằng Gemini (gõ câu hỏi làm CAPTION của ảnh/video TRƯỚC khi bấm gửi, không nhắn tin riêng sau)
/undo — hoàn tác NGAY hành động /spend hoặc /todo gần nhất (lỡ tay gõ nhầm số tiền/nội dung)
/export_data — tải ngay file sao lưu toàn bộ dữ liệu bot (cũng tự động gửi vào kênh riêng mỗi Chủ nhật 22h; 21h Chủ nhật hàng tuần còn có tin tổng kết chi tiêu + dinh dưỡng cả tuần)
/push — kích hoạt thủ công bản tin định kỳ (tin tức/cheat sheet/sách) để test thử
/start, /help — xem lại hướng dẫn này bất cứ lúc nào (gõ /start cũng hiện lại menu nút bấm nhanh)

<i>Chỉ chat_id đã được cấp phép mới dùng được bot (xem ALLOWED_CHAT_IDS). Chat tự do giờ có nhớ vài lượt hỏi-đáp gần nhất để hiểu mạch chuyện hơn.</i>"""


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào sếp! Em là Quản Gia Life-OS, sẵn sàng phục vụ.\n\n"
        "Gõ /help để xem đầy đủ danh sách lệnh. Em vừa để sẵn menu nút bấm nhanh bên dưới cho các lệnh hay dùng.",
        parse_mode="HTML",
        reply_markup=QUICK_KEYBOARD,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await execute_undo(update.message.chat_id, context)
