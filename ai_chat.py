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
from core_actions import add_reminder, execute_idea, execute_spend, execute_todo
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
        recent_ideas = "\n".join(f"- {i['text']}" for i in ideas.get("ideas", [])[-5:])
        ctx = f"KHO Ý TƯỞNG CỦA NGƯỜI DÙNG:\n{recent_ideas}\n\n" if recent_ideas else ""

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

        system_suffix = (
            "\n\n(SYSTEM PROMPT TỐI CAO: Đóng vai một Quân sư cấp cao / Trợ lý tinh hoa. "
            "Suy nghĩ sâu sắc, lập luận đa chiều, đưa ra góc nhìn sắc bén và giải pháp đột phá. "
            "Không bao giờ nói chung chung hay sáo rỗng. Dài hay ngắn tuỳ vào mức độ phức tạp của câu hỏi, "
            "nhưng phải CHẤT LƯỢNG. KHÔNG dùng markdown # hay **, chỉ dùng thẻ <b>, <i> chuẩn HTML. "
            "Luôn xưng hô theo đúng luật trong Bộ Nhớ Lõi, nếu không có thì gọi là 'sếp' và xưng 'em')."
        )
        prompt = ctx + text + system_suffix

        response = await call_gemini_async(prompt)
        await send_chunked_message(update.message.reply_text, clean_for_telegram(response))
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
        prompt = ctx + text + "\n\n(Đóng vai Quân sư cấp cao. Suy luận sâu, đa chiều, chiến lược. Sử dụng thẻ <b>, <i> chuẩn HTML.)"

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

        prompt = f"""Đóng vai một 'Shark' (Nhà đầu tư) khắt khe và thực tế trên Shark Tank. Người dùng vừa trình bày ý tưởng kinh doanh sau: "{text}".
        Hãy phản biện và cố vấn. Trình bày rõ ràng theo cấu trúc:
        1. 🩸 Điểm chết (Chỉ ra 1-2 rủi ro chí mạng nhất của mô hình này).
        2. 💡 Lối thoát (Gợi ý chiến lược Go-to-Market hoặc cách pivot để kiếm được tiền).
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


async def handle_video(update, context):
    import os
    import asyncio
    from datetime import datetime
    
    
    
    
    status_msg = None
    file_path = None
    try:
        status_msg = await send_chunked_message(update.message.reply_text, "<i>Dang tai va phan tich video, doi xiu nhe...</i>")
        
        video_file = await context.bot.get_file(update.message.video.file_id)
        file_path = unique_temp_path("video", ".mp4")
        await video_file.download_to_drive(file_path)
        
        caption = update.message.caption or "Phan tich video nay."
        video_part = await asyncio.to_thread(client.files.upload, file=file_path)
        
        prompt = f"{caption}\n(Hay tra loi ngan gon, xuc tich. KHONG dung the HTML nhu h1-h6, chi dung the <b> hoac <i>)"
        
        res = await call_gemini_async([video_part, prompt], model=MODEL_PRO)
        
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await send_chunked_message(update.message.reply_text, clean_for_telegram(res))
    except Exception as e:
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await update.message.reply_text(f"Loi phan tich video: {e}")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

