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
   mất cập nhật của nhau ("lost update"). Ở đây mỗi "kho" (file hoặc
   key Postgres) có 1 asyncio.Lock riêng, và `update()` bọc trọn chu
   trình đọc-sửa-ghi trong lock đó.

3. (Bản cập nhật A2) ĐĨA EPHEMERAL TRÊN RENDER FREE: file JSON cục bộ
   bị XOÁ SẠCH mỗi lần redeploy/restart/spin-down trên gói Free của
   Render — atomic write chỉ chống hỏng file giữa chừng, KHÔNG chống
   được việc cả file biến mất khi container bị thay mới. Giải pháp:
   nếu có biến môi trường DATABASE_URL (VD Postgres của Supabase),
   toàn bộ store tự động chuyển sang `PostgresJSONStore` — dữ liệu
   sống sót qua mọi lần redeploy/restart vì nằm ở dịch vụ Postgres
   bên ngoài, không nằm trên đĩa của Render. Không đặt DATABASE_URL
   thì bot vẫn chạy được với `JSONStore` (file cục bộ) như bản cũ,
   tiện cho chạy thử ở máy local.

Toàn bộ I/O (đĩa hoặc mạng) chạy ngoài event loop chính (asyncio.to_thread
cho file; asyncpg vốn đã async-native cho Postgres) để không chặn bot.
"""
import asyncio
import json
import logging
import os
import tempfile
from typing import Any, Callable

from config import (
    DATABASE_URL,
    DB_SSL,
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


class _PgBackend:
    """Pool asyncpg dùng chung cho mọi PostgresJSONStore trong tiến
    trình — tạo 1 lần (lazy, khi có store đầu tiên cần dùng), khởi tạo
    lại bảng nếu chưa có (idempotent, an toàn khi gọi nhiều lần)."""

    _pool = None
    _init_lock = asyncio.Lock()

    @classmethod
    async def get_pool(cls):
        if cls._pool is not None:
            return cls._pool
        async with cls._init_lock:
            if cls._pool is None:
                import asyncpg  # import trễ: chỉ cần khi thực sự dùng Postgres

                async def _register_jsonb(conn):
                    await conn.set_type_codec(
                        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
                    )

                ssl_mode = None if DB_SSL == "disable" else DB_SSL
                pool = await asyncpg.create_pool(
                    DATABASE_URL, min_size=1, max_size=5, init=_register_jsonb, ssl=ssl_mode
                )
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS lifeos_kv (
                            key TEXT PRIMARY KEY,
                            data JSONB NOT NULL
                        )
                        """
                    )
                cls._pool = pool
                logger.info("Đã kết nối Postgres (%s) — dữ liệu sẽ bền vững qua các lần redeploy.", "SSL=" + str(ssl_mode))
        return cls._pool


class PostgresJSONStore:
    """Cùng interface với JSONStore (read/write/update) nhưng lưu ở
    Postgres thay vì file cục bộ — để mọi call-site (core_actions.py,
    handlers/*.py) dùng được cả 2 loại store mà không cần sửa gì."""

    _locks: dict[str, asyncio.Lock] = {}

    def __init__(self, key: str, default_factory: Callable[[], Any]):
        self.key = key
        self.default_factory = default_factory

    def _get_lock(self) -> asyncio.Lock:
        lock = self._locks.get(self.key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[self.key] = lock
        return lock

    async def read(self) -> Any:
        pool = await _PgBackend.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT data FROM lifeos_kv WHERE key = $1", self.key)
        if row is None:
            return self.default_factory()
        return row["data"]

    async def write(self, data: Any) -> None:
        pool = await _PgBackend.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO lifeos_kv (key, data) VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data
                """,
                self.key,
                data,
            )

    async def update(self, mutate: Callable[[Any], Any]) -> Any:
        async with self._get_lock():
            data = await self.read()
            result = mutate(data)
            new_data = data if result is None else result
            await self.write(new_data)
            return new_data


def _make_store(key: str, file_path: str, default_factory: Callable[[], Any]):
    """Factory chọn backend: có DATABASE_URL -> Postgres (bền vững);
    không có -> JSONStore file cục bộ như bản cũ (chạy thử local)."""
    if DATABASE_URL:
        return PostgresJSONStore(key, default_factory)
    return JSONStore(file_path, default_factory)


# --- Kho dữ liệu theo domain, dùng chung cho toàn bộ handlers ---
finance_store = _make_store(
    "finance", FINANCE_FILE, lambda: {"salary": 0, "budgets": {}, "expenses": [], "timo_confirmed": False}
)
todo_store = _make_store("todos", TODO_FILE, lambda: {"tasks": []})
ideas_store = _make_store("ideas", IDEAS_FILE, lambda: {"ideas": []})
reminders_store = _make_store("reminders", REMINDERS_FILE, lambda: {"reminders": []})
health_store = _make_store("health", HEALTH_FILE, lambda: {})
nutrition_store = _make_store("nutrition", NUTRITION_FILE, lambda: {})
memory_store = _make_store("memory", MEMORY_FILE, lambda: {"rules": []})

# (key, file_path cũ, default_factory) — dùng cho migrate 1 lần bên dưới.
_ALL_STORES_META = [
    ("finance", FINANCE_FILE, lambda: {"salary": 0, "budgets": {}, "expenses": [], "timo_confirmed": False}),
    ("todos", TODO_FILE, lambda: {"tasks": []}),
    ("ideas", IDEAS_FILE, lambda: {"ideas": []}),
    ("reminders", REMINDERS_FILE, lambda: {"reminders": []}),
    ("health", HEALTH_FILE, lambda: {}),
    ("nutrition", NUTRITION_FILE, lambda: {}),
    ("memory", MEMORY_FILE, lambda: {"rules": []}),
]


async def migrate_legacy_json_if_needed() -> None:
    """Chạy 1 lần lúc khởi động (xem post_init trong main.py).

    Nếu đang dùng Postgres (có DATABASE_URL) VÀ tồn tại file JSON cũ
    trên đĩa (VD sếp có commit sẵn finance.json... vào repo GitHub, hoặc
    container chưa bị redeploy từ lúc còn dùng file cục bộ) VÀ Postgres
    CHƯA có dữ liệu cho key đó (tránh ghi đè dữ liệu mới hơn đã có),
    thì import dữ liệu cũ từ file sang Postgres đúng 1 lần.

    Không có DATABASE_URL -> không làm gì (bot vẫn dùng JSONStore).
    """
    if not DATABASE_URL:
        return

    pool = await _PgBackend.get_pool()
    for key, file_path, default_factory in _ALL_STORES_META:
        if not os.path.exists(file_path):
            continue
        async with pool.acquire() as conn:
            already_has_data = await conn.fetchval("SELECT 1 FROM lifeos_kv WHERE key = $1", key)
        if already_has_data:
            continue
        try:
            legacy_data = await asyncio.to_thread(JSONStore(file_path, default_factory)._read_sync)
        except Exception as e:
            logger.warning("Không đọc được %s để migrate sang Postgres: %s", file_path, e)
            continue
        store = PostgresJSONStore(key, default_factory)
        await store.write(legacy_data)
        logger.info("✅ Đã migrate dữ liệu cũ từ %s sang Postgres (key=%s).", file_path, key)
