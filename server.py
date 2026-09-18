"""HTTP server 'giả' để các nền tảng free-tier (Render, Railway...)
health-check được, giữ tiến trình không bị coi là 'sleep'."""
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger(__name__)


class _HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        msg = b"Life-OS Bot is running!"
        self.send_response(200)
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        self.wfile.write(msg)

    # BUG FIX (18/9, lần 12): trước đây chỉ định nghĩa do_GET, KHÔNG có
    # do_HEAD -> BaseHTTPRequestHandler của Python tự động trả về "501
    # Not Implemented" cho MỌI request kiểu HEAD (hành vi mặc định khi
    # không thấy hàm do_HEAD nào được định nghĩa). Nhiều công cụ giám
    # sát uptime (UptimeRobot mặc định là 1 ví dụ) gửi HEAD thay vì GET
    # để tiết kiệm băng thông -> UptimeRobot báo "Ongoing incident / 501
    # Not Implemented" dù bot Telegram vẫn chạy hoàn toàn bình thường
    # (đây chỉ là trang health-check phụ giữ Render không ngủ, không
    # phải bản thân bot). Thêm do_HEAD trả lời giống hệt do_GET, chỉ
    # khác là không kèm phần thân (đúng chuẩn HTTP cho HEAD).
    def do_HEAD(self):
        msg = b"Life-OS Bot is running!"
        self.send_response(200)
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()

    def log_message(self, format, *args):  # tắt log request mặc định, đỡ nhiễu log chính
        pass


def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _HealthCheckHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info("Dummy health-check server đang chạy ở port %s", port)
