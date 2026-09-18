"""AI-OS: chat tự do, /deep, /learn, /pitch, và xử lý giọng nói (voice)."""
import asyncio
import logging
import os
import re
from datetime import datetime

import pytz
import trafilatura
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ai_client import call_gemini_async, clean_for_telegram, client, parse_amount
from config import MODEL_PRO
from core_actions import add_reminder, apply_idea_action, execute_idea, execute_spend, execute_todo
from storage import health_store, ideas_store, memory_store, nutrition_store
from telegram_helpers import safe_delete_message, send_chunked_message, unique_temp_path

logger = logging.getLogger(__name__)
VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")


async def handle_chat_text(update, context, text):
    if "#idea" in text.lower():
        await execute_idea(update.message.chat_id, context, text.lower().replace("#idea", "").strip())
        return

    try:
        ideas = await ideas_store.read()
        # Nâng cấp (18/9, lần 9): kèm id ẩn của từng ý tưởng vào ngữ
        # cảnh — cần để Gemini tham chiếu ĐÚNG ý tưởng khi sếp yêu cầu
        # sửa/xoá (xem chỉ dẫn IDEA_ACTION| trong system_suffix bên
        # dưới, và cách parse ở cuối hàm này).
        recent_list = ideas.get("ideas", [])[-5:]
        recent_ideas = "\n".join(f"[id={i.get('id', '?')}] {i['text']}" for i in recent_list)
        ctx = f"KHO Ý TƯỞNG CỦA NGƯỜI DÙNG (mỗi dòng có id riêng):\n{recent_ideas}\n\n" if recent_ideas else ""

        today_str = datetime.now(VN_TZ).strftime("%Y-%m-%d")
        health = await health_store.read()
        nutrition = await nutrition_store.read()
        nutri = nutrition.get(today_str, {})
        if health and nutri:
            target = health.get("target_calories", 2000)
            consumed = nutri.get("consumed_calories", 0)
            logs = ", ".join(nutri.get("logs", []))
            ctx += (
                f"HỒ SƠ DINH DƯỠNG HÔM NAY ({today_str}): Mục tiêu {target} kcal. "
                f"Đã nạp {consumed} kcal. Các món đã ăn: {logs}. Calo còn lại: {target - consumed} kcal.\n\n"
            )

        url_match = re.search(r"(https?://\S+)", text)
        if url_match:
            url = url_match.group(0)
            status_msg = await send_chunked_message(
                update.message.reply_text, "🌐 <i>Đang cắm cáp truy cập link sếp gửi...</i>"
            )
            try:
                # trafilatura làm network I/O đồng bộ -> chạy trong
                # thread riêng để không đơ bot trong lúc tải trang.
                downloaded = await asyncio.to_thread(trafilatura.fetch_url, url)
                extracted = await asyncio.to_thread(trafilatura.extract, downloaded) if downloaded else None
                if extracted:
                    ctx += f"NỘI DUNG BÀI VIẾT TỪ LINK MÀ NGƯỜI DÙNG VỪA GỬI ({url}):\n{extracted[:6000]}\n\n"
                elif downloaded:
                    ctx += (
                        f"HỆ THỐNG GHI CHÚ: Trang web ({url}) này chặn bot hoặc yêu cầu đăng nhập "
                        "(như Facebook/Tiktok). Hãy báo cho người dùng biết bạn không thể đọc được bài viết này.\n\n"
                    )
                else:
                    ctx += f"HỆ THỐNG GHI CHÚ: Trang web ({url}) từ chối kết nối. Hãy báo cho người dùng biết.\n\n"
            except Exception as e:
                logger.warning("Lỗi đọc link %s: %s", url, e)
            finally:
                await safe_delete_message(context, update.message.chat_id, status_msg)

        memory = await memory_store.read()
        if memory.get("rules"):
            rules_str = "\n".join(f"- {r}" for r in memory["rules"])
            ctx += f"BỘ NHỚ LÕI (CÁC NGUYÊN TẮC BẠN PHẢI TUÂN THỦ TỪ NGƯỜI DÙNG):\n{rules_str}\n\n"

        # Nâng cấp (18/9): thêm chỉ dẫn cấm mào đầu/chào hỏi sáo rỗng —
        # trước đây prompt chỉ ghi chung "không sáo rỗng" nhưng không
        # cấm tường minh kiểu mở bài máy móc ("Chào sếp, đây là...",
        # "Dưới góc độ Quân sư, tôi xin phân tích...") mà Gemini hay
        # tự chèn vào. Theo góp ý sếp nhận được: ra lệnh tường minh thì
        # model tuân theo tốt hơn nhiều so với chỉ nói chung chung.
        system_suffix = (
            "\n\n(SYSTEM PROMPT TỐI CAO: Đóng vai một Quân sư cấp cao / Trợ lý tinh hoa. "
            "Suy nghĩ sâu sắc, lập luận đa chiều, đưa ra góc nhìn sắc bén và giải pháp đột phá. "
            "TUYỆT ĐỐI KHÔNG chào hỏi, không nhắc lại câu hỏi của người dùng, không giới thiệu vai trò trước "
            "khi vào nội dung (cấm mở đầu kiểu 'Chào sếp, đây là...' hay 'Dưới góc độ Quân sư, tôi xin phân "
            "tích...') — đi thẳng vào luận điểm cốt lõi ngay câu đầu tiên. "
            "Không bao giờ nói chung chung hay sáo rỗng. Dài hay ngắn tuỳ vào mức độ phức tạp của câu hỏi, "
            "nhưng phải CHẤT LƯỢNG. KHÔNG dùng markdown # hay **, chỉ dùng thẻ <b>, <i> chuẩn HTML. "
            "Luôn xưng hô theo đúng luật trong Bộ Nhớ Lõi, nếu không có thì gọi là 'sếp' và xưng 'em'. "
            # Nâng cấp (18/9, lần 9): trước đây khi sếp bảo "bỏ X đi",
            # bot chỉ NÓI đã sửa xong chứ không hề có cơ chế nào thực
            # sự chỉnh sửa ideas_store -> ý tưởng cũ vẫn còn nguyên,
            # lần sau nạp lại làm ngữ cảnh là nội dung "đã xoá" quay
            # lại y như cũ. Giờ nếu đúng là yêu cầu sửa/xoá 1 ý tưởng
            # có trong KHO Ý TƯỞNG ở trên, bắt Gemini chèn thêm 1 dòng
            # lệnh ẩn ở CUỐI câu trả lời để code phía dưới parse ra và
            # THỰC SỰ áp dụng lên ideas_store (người dùng không thấy
            # dòng này) — cùng kiểu marker-line như AUDIO_VOCAB|/
            # TOPIC_NAME|/BOOK_TITLE| đã dùng ở jobs.py.
            "NẾU người dùng đang yêu cầu SỬA hoặc XOÁ 1 ý tưởng CỤ THỂ đã có trong KHO Ý TƯỞNG ở trên "
            "(VD 'bỏ X đi', 'sửa ý tưởng Y thành...'), PHẢI thêm đúng 1 dòng ở CUỐI CÙNG câu trả lời theo cú "
            "pháp: xoá hẳn thì ghi IDEA_ACTION|DELETE|<id lấy đúng từ [id=...] tương ứng>, sửa nội dung thì ghi "
            "IDEA_ACTION|EDIT|<id đó>|<toàn bộ nội dung MỚI của ý tưởng, đã bỏ phần cần xoá>. Dùng ĐÚNG id có "
            "sẵn trong ngữ cảnh, KHÔNG tự bịa id. CHỈ chèn dòng này khi CHẮC CHẮN đúng là yêu cầu sửa/xoá 1 ý "
            "tưởng đã lưu — nếu không phải, TUYỆT ĐỐI không chèn dòng IDEA_ACTION nào cả)."
        )
        prompt = ctx + text + system_suffix

        response = await call_gemini_async(prompt)

        # Tách dòng lệnh ẩn IDEA_ACTION| (nếu có) ra khỏi nội dung hiển
        # thị cho sếp, rồi áp dụng thật lên ideas_store.
        visible_lines = []
        action_type, action_id, action_new_text = None, None, ""
        for line in response.split("\n"):
            if line.startswith("IDEA_ACTION|"):
                parts = line.split("|", 3)
                if len(parts) >= 3:
                    action_type = parts[1].strip().upper()
                    action_id = parts[2].strip()
                    action_new_text = parts[3].strip() if len(parts) > 3 else ""
            else:
                visible_lines.append(line)
        visible_response = "\n".join(visible_lines).strip()

        if action_type in ("DELETE", "EDIT") and action_id:
            applied = await apply_idea_action(action_type, action_id, action_new_text)
            if not applied:
                logger.warning(
                    "IDEA_ACTION %s cho id=%s không khớp ý tưởng nào (có thể Gemini đoán nhầm id).",
                    action_type,
                    action_id,
                )

        await send_chunked_message(update.message.reply_text, clean_for_telegram(visible_response))
    except Exception as e:
        await update.message.reply_text(f"⚠️ Lỗi Server AI: {e}")


async def handle_chat_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_chat_text(update, context, update.message.text)


async def deep_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "💡 Sếp vui lòng nhập câu hỏi cần suy luận sâu. VD: `/deep Lên kế hoạch 12 tháng...`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    status_msg = None
    try:
        status_msg = await send_chunked_message(
            update.message.reply_text, "🧠 <i>Đang kích hoạt Model Pro để suy luận chuyên sâu...</i>"
        )
        memory = await memory_store.read()
        rules_str = "\n".join(f"- {r}" for r in memory.get("rules", []))
        ctx = f"BỘ NHỚ QUY TẮC:\n{rules_str}\n\n"
        # Nâng cấp (18/9): thêm cấm mào đầu (như system_suffix ở
        # handle_chat_text) + ép khung 3 góc nhìn Lạc quan / Hoài
        # nghi-Triết học / Hành động thực tế — theo đúng góp ý sếp
        # nhận được, để /deep không chỉ "suy luận sâu" chung chung mà
        # có cấu trúc rõ ràng, mỗi góc đều phải có ví dụ/kịch bản cụ
        # thể chứ không dừng ở nguyên lý trừu tượng.
        # Nâng cấp (18/9, lần 10): sếp phản hồi cụ thể qua case
        # "/deep trật tự sinh ra từ hỗn loạn" — góc nhìn số 2 trước đây
        # chỉ ghi "Hoài nghi/Triết học" nên câu trả lời thiếu hẳn lăng
        # kính tâm lý học (VD: cơ chế nhận thức, thiên kiến, động lực
        # tâm lý đằng sau vấn đề) dù đây là góc quan trọng sếp muốn.
        # Sửa để góc nhìn số 2 LUÔN bắt buộc kết hợp cả triết học lẫn
        # tâm lý học, áp dụng cho MỌI chủ đề dùng /deep từ nay, không
        # riêng "trật tự sinh ra từ hỗn loạn".
        prompt = (
            ctx
            + text
            + "\n\n(Đóng vai Quân sư cấp cao, suy luận sâu, đa chiều, chiến lược. "
            "TUYỆT ĐỐI KHÔNG chào hỏi, không nhắc lại câu hỏi, không giới thiệu vai trò trước khi vào nội "
            "dung (cấm mở đầu kiểu 'Chào sếp...' hay 'Dưới góc độ Quân sư, tôi xin phân tích...') — đi thẳng "
            "vào luận điểm cốt lõi ngay câu đầu tiên. "
            "Trình bày theo đúng 3 góc nhìn sau (có thể đặt tiêu đề ngắn bằng <b>): "
            "1) Lạc quan — cơ hội/tiềm năng thực sự nếu mọi thứ thuận lợi; "
            "2) Hoài nghi — Triết học & Tâm lý học — BẮT BUỘC kết hợp cả hai lăng kính: về triết học (bản "
            "chất gốc rễ của vấn đề, nghịch lý, giả định nền tảng cần tự vấn) VÀ về tâm lý học (cơ chế nhận "
            "thức/hành vi, động lực thật sự, thiên kiến tâm lý chi phối), không chỉ liệt kê rủi ro logic bề "
            "mặt; nêu rõ ràng cả 2 khía cạnh, không được bỏ sót khía cạnh tâm lý học; "
            "3) Hành động thực tế — bước làm cụ thể, PHẢI có ví dụ/kịch bản thực tế minh hoạ, không dừng ở "
            "nguyên lý chung chung. "
            "Sử dụng thẻ <b>, <i> chuẩn HTML, KHÔNG dùng markdown # hay **.)"
        )

        res = await call_gemini_async(prompt, model=MODEL_PRO)
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await send_chunked_message(update.message.reply_text, clean_for_telegram(res))
    except Exception as e:
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await update.message.reply_text(f"Lỗi hệ thống Pro: {e}")


async def learn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "🧠 Sếp muốn em nhớ điều gì? VD: `/learn Từ nay gọi tôi là Chủ Tịch`", parse_mode=ParseMode.MARKDOWN
        )
        return
    try:
        def _mutate(data):
            data.setdefault("rules", []).append(text)
            return data

        await memory_store.update(_mutate)
        await update.message.reply_text(
            "🧠 Đã lưu vào bộ nhớ cốt lõi (Core Memory). Em sẽ luôn tuân thủ nguyên tắc này từ nay về sau!"
        )
    except Exception as e:
        await update.message.reply_text(f"Lỗi: {e}")


async def pitch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "🦈 Sếp hãy nhập ý tưởng kinh doanh. VD: `/pitch Mở quán cafe kết hợp xem bài Tarot`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Âm thầm lưu vào Second Brain (ideas.json)
    try:
        def _mutate(data):
            data.setdefault("ideas", []).append(
                {
                    "id": str(int(datetime.now().timestamp())),
                    "text": f"[Pitch Doanh nghiệp]: {text}",
                    "timestamp": datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M"),
                }
            )
            return data

        await ideas_store.update(_mutate)
    except Exception as e:
        logger.error("Lỗi lưu pitch: %s", e)

    status_msg = None
    try:
        status_msg = await send_chunked_message(update.message.reply_text, "🦈 <i>Shark Bot đang soi ý tưởng của sếp...</i>")

        memory = await memory_store.read()
        memory_ctx = ""
        if memory.get("rules"):
            memory_ctx = "\n\nTUÂN THỦ CÁC NGUYÊN TẮC SAU:\n" + "\n".join(f"- {r}" for r in memory["rules"])

        # Nâng cấp (18/9): thêm (a) cấm mào đầu/nhắc lại ý tưởng trước
        # khi vào phân tích, (b) ép steelman trước khi tìm điểm chết —
        # trước đây bot chỉ liệt kê rủi ro bề mặt (ai nhìn vào ý tưởng
        # cũng đoán được), giờ bắt buộc thử tìm lý do ý tưởng CÓ THỂ
        # thành công trước, rồi mới soi ra giả định ẩn/điểm mù thật sự
        # mà người đề xuất có thể chưa nhận ra — đúng tinh thần
        # "red-team trước khi khuyến nghị" trong góp ý sếp nhận được.
        prompt = f"""Đóng vai một 'Shark' (Nhà đầu tư) khắt khe và thực tế trên Shark Tank. Người dùng vừa trình bày ý tưởng kinh doanh sau: "{text}".
        TUYỆT ĐỐI KHÔNG chào hỏi hay nhắc lại nguyên văn ý tưởng của người dùng trước khi phân tích — đi thẳng vào mục 1.
        Trước khi chấm điểm, hãy tự steelman ý tưởng này trước (thử tìm lý do nó CÓ THỂ thành công), rồi mới xác định
        1-2 giả định ẩn/điểm mù mà chính người đề xuất có thể chưa nhận ra — không chỉ liệt kê rủi ro bề mặt ai cũng đoán được.
        Hãy phản biện và cố vấn. Trình bày rõ ràng theo cấu trúc:
        1. 🩸 Điểm chết (1-2 giả định ẩn/rủi ro chí mạng nhất — không phải rủi ro hiển nhiên bề mặt).
        2. 💡 Lối thoát (Gợi ý chiến lược Go-to-Market hoặc cách pivot để kiếm được tiền, có ví dụ/kịch bản cụ thể chứ không nói nguyên lý chung chung).
        3. 📚 Từ vựng thương trường (Liệt kê đúng 3 từ vựng Tiếng Anh chuyên ngành Kinh doanh/Khởi nghiệp đã được chèn khéo léo trong bài viết, kèm giải nghĩa ngắn).
        4. Đánh giá khả thi: X/10 điểm.
        Lưu ý: Giọng điệu gai góc, sắc sảo, thực tế. KHÔNG dùng markdown # hay **, chỉ dùng văn bản thường và emoji. Sử dụng <b> cho in đậm, <i> cho in nghiêng nếu cần (chuẩn HTML).{memory_ctx}"""

        res = await call_gemini_async(prompt, model=MODEL_PRO)
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await send_chunked_message(update.message.reply_text, clean_for_telegram(res))
    except Exception as e:
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await update.message.reply_text(f"Lỗi hệ thống Shark: {e}")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý giọng nói bằng Gemini"""
    status_msg = None
    file_path = None
    try:
        status_msg = await send_chunked_message(update.message.reply_text, "🎙️ <i>Đang nghe và phân tích giọng nói...</i>")

        voice_file = await context.bot.get_file(update.message.voice.file_id)
        file_path = unique_temp_path("voice", ".ogg")
        await voice_file.download_to_drive(file_path)

        now_str = datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M")

        audio = await asyncio.to_thread(client.files.upload, file=file_path)
        prompt = f"""Bây giờ là: {now_str}.
        Nghe file âm thanh và phân loại ý định của sếp. Chỉ trả về ĐÚNG 1 DÒNG DUY NHẤT theo chuẩn sau:
        1. Tiêu tiền: SPEND|<số_tiền_bằng_số>|<lý_do> (VD: SPEND|50000|ăn phở)
        2. Nhắc việc To-do: TODO|<nội_dung> (VD: TODO|chiều 3h họp team)
        3. Hẹn giờ báo thức: REMIND|YYYY-MM-DD HH:MM|<nội_dung> (VD: REMIND|2026-09-15 15:30|Họp team)
        4. Lưu ý tưởng: IDEA|<nội_dung_ý_tưởng>
        5. Hỏi đáp: CHAT|<câu_hỏi_của_người_dùng>"""

        # BUG FIX: bản gốc gọi client.models.generate_content trực
        # tiếp ở đây (không qua call_gemini_robust) -> mất hẳn cơ chế
        # retry/fallback 429 cho riêng luồng giọng nói. Sửa để nhất
        # quán với toàn bộ bot.
        res = await call_gemini_async([audio, prompt])
        await safe_delete_message(context, update.message.chat_id, status_msg)

        if res.startswith("SPEND|"):
            parts = res.split("|", 2)
            await execute_spend(update.message.chat_id, context, parse_amount(parts[1]), parts[2])
        elif res.startswith("TODO|"):
            await execute_todo(update.message.chat_id, context, res.split("|", 1)[1])
        elif res.startswith("REMIND|"):
            parts = res.split("|", 2)
            r_time = VN_TZ.localize(datetime.strptime(parts[1], "%Y-%m-%d %H:%M"))
            await add_reminder(context.application.job_queue, update.message.chat_id, r_time, parts[2])
            await send_chunked_message(
                update.message.reply_text,
                f"⏰ Đã hẹn báo thức lúc <b>{r_time.strftime('%H:%M %d/%m')}</b> cho việc:\n{parts[2]}",
            )
        elif res.startswith("IDEA|"):
            await execute_idea(update.message.chat_id, context, res.split("|", 1)[1])
        elif res.startswith("CHAT|"):
            await handle_chat_text(update, context, res.split("|", 1)[1])
        else:
            await update.message.reply_text(f"Không nhận diện được lệnh: {res}")
    except Exception as e:
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await update.message.reply_text(f"⚠️ Lỗi nhận diện giọng nói: {e}")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
