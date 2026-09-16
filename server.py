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

    def log_message(self, format, *args):  # tắt log request mặc định, đỡ nhiễu log chính
        pass


def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _HealthCheckHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info("Dummy health-check server đang chạy ở port %s", port)
