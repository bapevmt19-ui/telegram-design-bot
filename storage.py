"""
Lớp lưu trữ JSON tập trung — thay thế load_json()/save_json() rải rác
khắp bản gốc.

Giải quyết 2 vấn đề chính khiến bot dễ mất dữ liệu khi chạy 24/7:

1. GHI KHÔNG ATOMIC: bản gốc `json.dump()` thẳng vào file đích. Nếu
   tiến trình bị kill (OOM, redeploy, crash) đúng lúc đang ghi, file
   JSON bị hỏng dở dang -> mất toàn bộ dữ liệu (không chỉ bản ghi mới).
   Ở đây ta ghi ra file tạm rồi `os.replace()` (atomic trên cả
   POSIX lẫn Windows) -> file đích luôn hoặc là bản cũ nguyên vẹn,
   hoặc là bản mới hoàn chỉnh, không bao giờ ở trạng thái dở dang.

2. KHÔNG CÓ LOCK: bản gốc đọc-sửa-ghi không khoá, nên 2 coroutine ghi
   gần như đồng thời (VD: lệnh gõ tay + voice cùng lúc) có thể làm
   mất cập nhật của nhau ("lost update"). Ở đây mỗi file có 1
   asyncio.Lock riêng, và `update()` bọc trọn chu trình đọc-sửa-ghi
   trong lock đó.

Toàn bộ I/O đĩa chạy trong thread riêng (asyncio.to_thread) để không
chặn event loop chính của bot.
"""
import asyncio
import json
import logging
import os
import tempfile
from typing import Any, Callable

from config import (
    FINANCE_FILE,
    HEALTH_FILE,
    IDEAS_FILE,
    MEMORY_FILE,
    NUTRITION_FILE,
    REMINDERS_FILE,
    TODO_FILE,
)

logger = logging.getLogger(__name__)


class JSONStore:
    # Registry lock theo đường dẫn file, dùng chung cho mọi instance
    # trỏ tới cùng 1 file.
    _locks: dict[str, asyncio.Lock] = {}

    def __init__(self, file_path: str, default_factory: Callable[[], Any]):
        self.file_path = file_path
        self.default_factory = default_factory

    def _get_lock(self) -> asyncio.Lock:
        lock = self._locks.get(self.file_path)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[self.file_path] = lock
        return lock

    def _read_sync(self) -> Any:
        if not os.path.exists(self.file_path):
            return self.default_factory()
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Không đọc được %s (%s) — dùng giá trị mặc định.", self.file_path, e)
            return self.default_factory()

    def _write_sync(self, data: Any) -> None:
        directory = os.path.dirname(self.file_path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.file_path)  # atomic
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    async def read(self) -> Any:
        return await asyncio.to_thread(self._read_sync)

    async def write(self, data: Any) -> None:
        await asyncio.to_thread(self._write_sync, data)

    async def update(self, mutate: Callable[[Any], Any]) -> Any:
        """Đọc - sửa - ghi trong 1 lock, tránh lost-update.

        `mutate` PHẢI là hàm đồng bộ thuần (không async def) — nó chỉ
        thao tác trên dict/list đã có sẵn trong bộ nhớ, không cần I/O.
        `mutate` có thể sửa data in-place và return chính nó, hoặc trả
        về data mới; nếu return None thì data (đã sửa in-place) được
        dùng làm kết quả.
        """
        async with self._get_lock():
            data = await self.read()
            result = mutate(data)
            new_data = data if result is None else result
            await self.write(new_data)
            return new_data


# --- Kho dữ liệu theo domain, dùng chung cho toàn bộ handlers ---
finance_store = JSONStore(
    FINANCE_FILE, lambda: {"salary": 0, "budgets": {}, "expenses": [], "timo_confirmed": False}
)
todo_store = JSONStore(TODO_FILE, lambda: {"tasks": []})
ideas_store = JSONStore(IDEAS_FILE, lambda: {"ideas": []})
reminders_store = JSONStore(REMINDERS_FILE, lambda: {"reminders": []})
health_store = JSONStore(HEALTH_FILE, lambda: {})
nutrition_store = JSONStore(NUTRITION_FILE, lambda: {})
memory_store = JSONStore(MEMORY_FILE, lambda: {"rules": []})
