# Life-OS Bot — bản refactor

## Cập nhật (18/9, lần 11): 6 nâng cấp KHÔNG tốn thêm chi phí

Toàn bộ mục dưới đây dùng lại đúng hạ tầng free hiện có (Neon Postgres, Gemini free tier) — không thêm biến môi trường, không thêm dịch vụ trả phí nào.

- **Trí nhớ hội thoại ngắn hạn cho chat tự do** (`handlers/ai_chat.py`, kho mới `conversation_history`): trước đây mỗi tin nhắn chat thường là 1 lần gọi Gemini hoàn toàn độc lập, bot không "nhớ" vừa nói gì ở tin trước. Giờ lưu lại `CONVERSATION_KEEP_LINES` (6 dòng ≈ 3 lượt hỏi-đáp) gần nhất theo từng chat_id, đưa vào ngữ cảnh mỗi lần hỏi tiếp.
- **Mở rộng phạm vi "nhớ" ý tưởng khi sửa/xoá qua chat** (`config.py: IDEA_CONTEXT_LIMIT`): nâng từ 5 lên 40 ý tưởng gần nhất được đưa vào ngữ cảnh cho Gemini nhận diện — giảm hẳn trường hợp "bảo xoá X mà không xoá được" vì ý tưởng đó nằm ngoài phạm vi nhìn thấy của bot (hạn chế đã ghi ở bản lần 9).
- **Cảnh báo ngân sách SỚM** (`core_actions.py: execute_spend`): trước đây chỉ cảnh báo sau khi đã tiêu ÂM quỹ. Giờ thêm mốc cảnh báo ở 80% (cả theo từng hũ ngân sách lẫn tổng ngân sách tháng), để biết trước khi âm chứ không phải sau.
- **Tổng kết chi tiêu + dinh dưỡng cuối tuần tự động** (`jobs.py: weekly_summary_job`): gửi vào chat riêng mỗi Chủ Nhật 21h (trước giờ backup 22h) — tổng chi tuần theo từng danh mục, và trung bình calo/ngày nếu có dùng `/healthsetup` + ghi món ăn. Thuần tính toán trên dữ liệu sẵn có, không gọi thêm Gemini.
- **Lệnh `/undo`** (`core_actions.py: execute_undo`, kho mới `last_action`): hoàn tác ĐÚNG 1 hành động `/spend` hoặc `/todo` gần nhất nếu lỡ tay gõ nhầm số tiền/nội dung — không hoàn tác được nhiều bước, chỉ bước cuối cùng.
- **Menu nút bấm nhanh** (`handlers/system.py: QUICK_KEYBOARD`): gõ `/start` sẽ hiện sẵn bàn phím nút bấm cho các lệnh hay dùng không cần tham số (`/tasks /report /remind_list /export_data /help`), đỡ phải nhớ/gõ tay.

**Không nằm trong file này (thiết lập bên ngoài, cũng miễn phí):** giám sát uptime thật sự (báo lỗi khi bot sập, khác với cron-job.org hiện tại chỉ ping giữ ấm) — khuyến nghị dùng UptimeRobot free, trỏ vào đúng URL Render của bot, bật cảnh báo qua Telegram/email khi ping thất bại.

## Cập nhật (18/9, lần 10): `/deep` bắt buộc kết hợp góc nhìn Tâm lý học

- Sếp phản hồi qua case thực tế `/deep trật tự sinh ra từ hỗn loạn`: góc nhìn số 2 của `/deep` trước đây chỉ ghi "Hoài nghi/Triết học" nên câu trả lời thiếu hẳn lăng kính tâm lý học (cơ chế nhận thức, thiên kiến, động lực tâm lý phía sau vấn đề).
- Sửa prompt `deep_command` (`handlers/ai_chat.py`): góc nhìn số 2 đổi thành **"Hoài nghi — Triết học & Tâm lý học"**, bắt buộc phải nêu rõ CẢ HAI khía cạnh (triết học: bản chất gốc rễ/nghịch lý/giả định nền tảng; tâm lý học: cơ chế nhận thức-hành vi/động lực thật sự/thiên kiến tâm lý) chứ không được chỉ dừng ở rủi ro logic bề mặt.
- Áp dụng cho **mọi chủ đề** dùng `/deep` từ nay về sau, không riêng gì "trật tự sinh ra từ hỗn loạn".

## Cập nhật (18/9, lần 9): sửa dịch tin bị thiếu + sửa/xoá ý tưởng qua chat tự do

- **Dịch tin tức bị thiếu so với bài gốc** (`jobs.py: send_news_to_channel`): nguyên nhân là code cắt cứng nội dung gốc chỉ lấy **3000 ký tự đầu** trước khi đưa Gemini dịch — bài báo dài hơn thế bị dịch thiếu hẳn phần sau, không phải do Gemini dịch sót. Nâng giới hạn lên 20000 ký tự (đủ cho gần như mọi bài báo trọn vẹn).
- **"Bỏ X đi" trong chat tự do không có tác dụng thật** (`handlers/ai_chat.py`, `core_actions.py`): trước đây khi sếp yêu cầu sửa/xoá 1 ý tưởng qua chat thường, Gemini chỉ TRẢ LỜI như đã làm xong — không hề có cơ chế nào thực sự sửa `ideas_store`, nên ý tưởng cũ vẫn còn nguyên và xuất hiện lại ở lần chat sau. Giờ mỗi ý tưởng có `id` riêng; khi Gemini nhận ra đúng là yêu cầu sửa/xoá 1 ý tưởng đã lưu, nó tự chèn 1 dòng lệnh ẩn `IDEA_ACTION|DELETE|<id>` hoặc `IDEA_ACTION|EDIT|<id>|<nội dung mới>` ở cuối câu trả lời (sếp không thấy dòng này) — code parse dòng đó và **thực sự** cập nhật `ideas_store` qua `apply_idea_action()`, cùng kiểu marker-line như `AUDIO_VOCAB|`/`TOPIC_NAME|`/`BOOK_TITLE|` đã dùng ở nơi khác. Không thêm lệnh `/` nào — vẫn gõ chat bình thường như "Bỏ ceresis.vn đi".
  - **Giới hạn cần biết**: chỉ hoạt động với ý tưởng nằm trong 5 ý tưởng gần nhất (phạm vi ngữ cảnh hiện có) và với ý tưởng có `id` (tạo từ lần cập nhật này trở đi, hoặc qua `/pitch` vốn đã có sẵn id). Vì dựa vào Gemini tự nhận diện đúng ý tưởng cần sửa thay vì chọn theo số thứ tự cố định, có xác suất nhỏ đoán nhầm nếu 2 ý tưởng gần đây nội dung khá giống nhau — đổi lại không cần thêm lệnh mới.

## Cập nhật (18/9, lần 8): tinh chỉnh prompt persona "Quân sư" (chat tự do, /deep, /pitch)

Theo góp ý sếp nhận được về giọng văn persona "Quân sư chiến lược" (`handlers/ai_chat.py`), không đổi kiến trúc gì (bot vốn đã gọi thẳng Gemini API, không qua UI đóng gói — đúng hướng được khuyên) — chỉ tinh chỉnh 3 system prompt:

- **Chat tự do + `/deep`**: thêm chỉ dẫn TƯỜNG MINH cấm mào đầu/chào hỏi/nhắc lại câu hỏi trước khi vào nội dung (trước đây chỉ ghi chung "không sáo rỗng", chưa đủ để chặn kiểu mở bài máy móc).
- **`/deep`**: thêm khung 3 góc nhìn bắt buộc — Lạc quan / Hoài nghi-Triết học / Hành động thực tế (góc thứ 3 bắt buộc phải có ví dụ/kịch bản cụ thể, không dừng ở nguyên lý chung chung).
- **`/pitch`**: thêm bước ép steelman ý tưởng trước khi tìm điểm chết, để bot soi ra giả định ẩn/điểm mù thật sự thay vì chỉ liệt kê rủi ro bề mặt ai cũng đoán được.

Không nâng cấp bộ nhớ dài hạn (Vector DB) trong lần này — bot đã có `/learn` (Bộ Nhớ Lõi, tự động chèn vào mọi prompt) đáp ứng phần lớn nhu cầu cá nhân hoá hiện tại; nâng lên Vector DB là đầu tư lớn hơn nhiều, để dành khi thực sự cần.

## Cập nhật (17/9, lần 7): sao lưu dữ liệu, báo cáo Excel, nhắc việc/nhắc nhở nâng cao, sửa Telegraph

**Cần làm thêm trên Render** (ngoài code): thêm biến môi trường mới `TELEGRAM_CHAT_ID_BACKUP` (kênh riêng nhận file backup — sếp đã tạo, chat_id `-1004393711929`, nhớ đã thêm bot vào làm admin của kênh đó). `requirements.txt` có thêm `openpyxl` — Render tự cài lại khi deploy, không cần làm gì thêm.

- **Sửa lỗi Telegraph mất quyền sửa bài cũ** (`ai_client.py`): trước đây mỗi lần bot restart là tạo account Telegraph MỚI, mất quyền sửa mọi trang đã đăng trước đó. Giờ `access_token` được lưu lại (Postgres, key `settings`) và nạp lại ở lần chạy sau — `init_telegraph()` gọi 1 lần trong `post_init`.
- **`/export_data`** (`handlers/backup.py`, mới): gửi ngay 1 file JSON gộp toàn bộ dữ liệu bot vào chat vừa gõ lệnh. Đồng thời tự động gửi bản backup vào kênh riêng (`TELEGRAM_CHAT_ID_BACKUP`) mỗi Chủ nhật 22h (`weekly_backup_job`) — tách khỏi chat cá nhân để tránh loạn tin nhắn.
- **Nhắc cập nhật chi tiêu cuối ngày** (`jobs.py: remind_expense_job`): 23h hàng ngày, chỉ nhắc nếu hôm đó chưa ghi khoản chi nào (`/spend`).
- **`/report_excel`** (`handlers/finance.py`): xuất chi tiêu tháng hiện tại ra file `.xlsx` dạng bảng (cột Ngày/Số tiền/Danh mục/Lý do, có dòng tổng, tự giãn độ rộng cột) — bổ sung bên cạnh `/report` (biểu đồ tròn), không thay thế.
- **`/remind` hỗ trợ ngày cụ thể**: `/remind DD/MM HH:MM [nội dung]` để hẹn đúng 1 ngày trong tương lai; `/remind HH:MM [nội dung]` (không ngày) vẫn hoạt động như cũ. Mỗi nhắc nhở giờ có nút **"✅ Đã xong"**; nếu sau 30 phút (`REMINDER_FOLLOWUP_MINUTES` trong `config.py`) sếp chưa bấm, bot tự nhắc lại thêm đúng 1 lần.
- **`/remind_daily HH:MM [nội dung]`**, **`/remind_every [số]h [nội dung]`** (mới, `handlers/reminders.py`): nhắc lặp lại hàng ngày / theo mỗi N giờ — dành cho việc không gắn với 1 ngày cụ thể (uống thuốc, uống nước...). `/remind_list` xem danh sách đang chạy, `/remind_stop [số]` để tắt. Được lưu lại (`recurring_reminders_store`) và tự đăng ký lại vào `job_queue` sau mỗi lần bot restart (`load_recurring_reminders`, gọi trong `post_init`).
- **"Nhắc việc nâng cao"** (`core_actions.py`, `jobs.py`, `handlers/todo.py`): `/todo` giờ nhận 2 thẻ tuỳ chọn chèn trong nội dung — `!gấp` (ưu tiên cao) và `hạn:DD/MM` (hạn chót). Việc thường được tự động đẩy lại danh sách còn tồn đọng vào 3 khung giờ hành chính cố định/ngày (9h00, 13h30, 17h00); việc `!gấp` hoặc đã tới/quá hạn được nhắc riêng, dày hơn (mỗi 2 tiếng, 8h-18h). Logic hiển thị (thẻ, số ngày tồn đọng, nút "✅ Xong" riêng theo từng việc) dùng chung giữa `/tasks` gõ tay và các job tự động (`render_tasks_message`) — bấm xong 1 việc không ảnh hưởng các việc còn lại.
- **`/help`**: thêm ví dụ gõ THẬT cho từng lệnh (thay vì chỉ ghi mẫu cú pháp trừu tượng) — xem lại bất cứ lúc nào khi quên cú pháp.

## Cập nhật (17/9, lần 6): chống lặp nội dung ở "Bữa trưa doanh nhân" + "Trích sách tối"

Trước đây `jobs.py` gọi Gemini với prompt **y hệt mỗi ngày** cho 2 job này — Gemini không có ký ức giữa các lần gọi API riêng biệt, nên sau một thời gian dễ chọn lại đúng chủ đề/cuốn sách đã dùng (đúng như sếp phản ánh "gửi bài viết giống nhau quá").

Đã thêm `content_history_store` (lưu tối đa 30 chủ đề/sách gần nhất) — mỗi lần chạy job, bot đọc lại lịch sử này, **chèn thẳng vào prompt** dạng "KHÔNG được chọn lại: ...", rồi sau khi Gemini trả lời xong mới lưu thêm mục vừa dùng vào lịch sử. Đây là cách thực tế nhất để giảm lặp khi mỗi lần gọi API là 1 phiên độc lập — không đảm bảo 100% không bao giờ trùng (Gemini vẫn có thể lệch hướng dẫn), nhưng giảm mạnh so với việc không có cơ chế gì như trước.

## Chạy thử

```bash
pip install -r requirements.txt
cp .env.example .env   # rồi điền GEMINI_API_KEY, TELEGRAM_BOT_TOKEN...
python main.py
```

Các file dữ liệu (`finance.json`, `todos.json`, ...) vẫn nằm ở thư mục
gốc như bản cũ — copy nguyên các file JSON hiện có của sếp vào cùng
thư mục với `main.py` là chạy tiếp được ngay, không cần migrate gì.

## Cấu trúc

| File | Vai trò |
|---|---|
| `config.py` | Đọc `.env`, hằng số, logging |
| `storage.py` | `JSONStore` — đọc/ghi JSON atomic + có lock, thay `load_json`/`save_json` |
| `ai_client.py` | Client Gemini + **`call_gemini_robust` giữ nguyên logic gốc** + wrapper async |
| `telegram_helpers.py` | **`send_chunked_message` giữ nguyên cơ chế gốc** (chỉ sửa sleep) + helper phụ |
| `core_actions.py` | Logic dùng chung giữa lệnh gõ tay & giọng nói (spend/todo/idea/reminder) |
| `handlers/*.py` | Các lệnh Telegram, chia theo domain |
| `jobs.py` | 3 job định kỳ (bản tin sáng, cheat sheet trưa, trích sách tối) |
| `server.py` | Health-check server cho Render/Railway |
| `main.py` | Đăng ký handler, khởi động bot |

## Cập nhật (17/9): sửa lỗi crash "unsupported start tag" + thêm phân tích video

- **`telegram_helpers.py`**: thêm `sanitize_telegram_html()` — lọc mọi thẻ HTML mà Telegram không hỗ trợ (`<h1-6>`, `<ul>`, `<li>`, `<p>`, `<div>`...) trước khi gửi, áp dụng tự động bên trong `send_chunked_message` cho MỌI tin nhắn HTML. Đây là nguyên nhân lỗi `Can't parse entities: unsupported start tag "h3"` sếp gặp khi Gemini tự chèn thẻ lạ vào câu trả lời. Có thêm lớp dự phòng: nếu Telegram vẫn từ chối, tự gửi lại dạng plain text thay vì để cả handler crash.
- **`handlers/video.py`** (mới) + đăng ký trong `main.py`: bot giờ thực sự xem được video Telegram (kể cả video forward) — tải về, upload lên Gemini Files API, **chờ xử lý xong (state ACTIVE)** rồi mới phân tích (video cần thời gian xử lý khác ảnh/audio). Giới hạn ~20MB theo giới hạn tải file của Telegram Bot API.
  - **Lưu ý cách dùng**: để bot hiểu đúng yêu cầu, hãy gõ câu hỏi/yêu cầu làm **caption của chính video đó** (gõ trước khi bấm gửi), thay vì gửi video xong rồi nhắn tin riêng ngay sau — Telegram không tự liên kết 2 tin nhắn đó lại với nhau, nên tin nhắn text sau sẽ bị xử lý như 1 câu hỏi chat độc lập, không liên quan đến video.

## Cập nhật (17/9, lần 2): fix crash khi deploy trên Render — sai version `python-telegram-bot`

Log deploy báo lỗi (KHÔNG liên quan gì tới code của bot, mà là do thư viện):

```
AttributeError: 'Updater' object has no attribute '_Updater__polling_cleanup_cb' and no __dict__ for setting new attributes
```

Đây là [lỗi đã biết của chính python-telegram-bot (issue #4127)](https://github.com/python-telegram-bot/python-telegram-bot/issues/4127): các bản 20.x xung đột với cách Python 3.13+ xử lý `__slots__`. Render đang chạy Python 3.14, còn `requirements.txt` trước đó ghim `>=20,<21` — đúng dải version dính bug. Đã sửa thành `python-telegram-bot[job-queue]==22.8` ([bản ổn định mới nhất](https://docs.python-telegram-bot.org/en/stable/changelog.html), đã vá lỗi này từ lâu). Chỉ cần thay `requirements.txt` rồi Render tự cài lại là xong, không cần sửa code Python nào khác.

## Cập nhật (17/9, lần 3): A2 lưu trữ bền vững + B chặn người lạ + C tiện ích vận hành

### A2 — Lưu trữ bền vững qua Postgres (Supabase free)

**Vấn đề**: Render Free có đĩa **ephemeral** — mọi file JSON (`finance.json`, `todos.json`...) bị xoá sạch mỗi lần redeploy/restart/spin-down. Bản vá atomic-write trước đây chỉ chống hỏng file giữa chừng, không chống được việc cả file biến mất.

**Cách sửa**: `storage.py` giờ có thêm `PostgresJSONStore` (cùng interface `read/write/update` với `JSONStore` cũ, nên toàn bộ `core_actions.py`/`handlers/*.py` không cần sửa gì). Có biến môi trường `DATABASE_URL` → tự dùng Postgres (bền vững); không có → vẫn dùng file JSON cục bộ như cũ (tiện chạy thử local). Lần đầu bật Postgres, nếu còn file JSON cũ nằm cùng thư mục, bot tự động import 1 lần sang Postgres (`migrate_legacy_json_if_needed()`, chạy trong `post_init`).

**Sếp cần làm** (1 lần):
1. Tạo project free tại [supabase.com](https://supabase.com).
2. Vào **Project Settings → Database → Connection string**, chọn tab **URI**, copy, thay `[YOUR-PASSWORD]` bằng mật khẩu DB đã đặt lúc tạo project.
3. Vào Render → service của bot → **Environment**, thêm biến `DATABASE_URL` = connection string vừa copy.
4. Deploy lại. Log sẽ báo `Đã kết nối Postgres...` nếu thành công.

### B — Chặn người lạ thao tác bot

**Vấn đề**: bot đọc `TELEGRAM_CHAT_ID` từ `.env` nhưng chưa từng dùng để **chặn** ai — bất kỳ ai tìm ra bot đều xem/sửa được dữ liệu tài chính-sức khoẻ riêng tư, tốn quota Gemini của sếp.

**Cách sửa**: `config.py` tính sẵn `ALLOWED_CHAT_IDS` (chat riêng của sếp + 2 kênh broadcast + tuỳ chọn thêm qua `ALLOWED_CHAT_IDS` trong `.env`). `main.py` đăng ký 1 `TypeHandler` ở group `-1` (chạy **trước tiên**, trước mọi handler khác) — chat lạ bị chặn im lặng (không phản hồi gì, tránh lộ thông tin/bị lợi dụng spam). **Do đó `TELEGRAM_CHAT_ID` trong `.env`/Render giờ là bắt buộc và phải đúng chat_id cá nhân của sếp** (lấy bằng cách nhắn `@userinfobot`) — nếu để trống hoặc sai, chính sếp cũng bị chặn.

### C — Tiện ích vận hành

- **`/start`, `/help`** (mới, `handlers/system.py`): giới thiệu bot + liệt kê đầy đủ lệnh.
- **`set_my_commands`**: gõ "/" trong Telegram giờ hiện gợi ý đầy đủ lệnh kèm mô tả (trước đây không có gì hiện ra).
- **`concurrent_updates(8)`**: bot xử lý được vài update cùng lúc (VD ảnh + video gửi liên tiếp) thay vì xử lý tuần tự — an toàn vì mọi thao tác đọc-sửa-ghi dữ liệu đã có `asyncio.Lock` theo từng kho từ bản refactor đầu.
- **`requirements.txt`**: thêm `asyncpg` (driver Postgres) + thêm cận dưới version cho các thư viện trước đây không ghim gì. **Lưu ý minh bạch**: môi trường build code này không truy cập được PyPI trực tiếp để tra số version mới nhất — nên chỉ ghim **cận dưới** (tránh bản quá cũ thiếu tính năng cần dùng), KHÔNG ghim cận trên đoán mò, để tránh lặp lại sự cố lần trước (ghim `python-telegram-bot<21` sai làm sập bot khi Render dùng Python 3.14). Nếu muốn chính xác tuyệt đối, sếp có thể chạy `pip install -r requirements.txt` rồi `pip freeze` để lấy version thật đang cài và ghim cứng lại.

## Những gì đã sửa so với bản gốc (tóm tắt — chi tiết xem trong chat)

- **Lỗi chặn bot**: SyntaxError f-string (Python <3.12), `/deep` chưa từng được đăng ký handler.
- **Chặn event loop**: mọi lời gọi Gemini/mạng/matplotlib/gTTS/telegraph giờ chạy qua `asyncio.to_thread`; `time.sleep` trong `send_chunked_message` và `call_gemini_robust` retry đổi thành non-blocking phía gọi.
- **An toàn dữ liệu**: ghi JSON atomic (temp file + `os.replace`), có `asyncio.Lock` theo từng file tránh lost-update.
- **Rò rỉ tài nguyên**: tên file tạm duy nhất theo từng request + tự xoá sau khi dùng; đóng `matplotlib` figure bằng `try/finally`; dùng `with open(...)` khi gửi ảnh/voice.
- **Nhất quán AI**: `execute_spend`, `handle_voice`, `send_book_to_channel` trước đây gọi thẳng Gemini không qua cơ chế fallback — giờ đều đi qua `call_gemini_async` (bọc `call_gemini_robust`).
- **UX**: bỏ `except: pass` im lặng ở `/goal`; thêm global error handler; backoff tăng dần cho vòng lặp `run_polling`.

## Cơ chế giữ nguyên 100% theo yêu cầu

- `call_gemini_robust` trong `ai_client.py`: y nguyên logic cascade 429/500/503.
- `send_chunked_message` trong `telegram_helpers.py`: y nguyên cách cắt chunk tại `\n` gần nhất, giới hạn 4000 ký tự.
