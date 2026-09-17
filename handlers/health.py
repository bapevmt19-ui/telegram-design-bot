"""Health-OS: /healthsetup /food /cook + xử lý ảnh đồ ăn / ảnh chụp màn hình"""
import asyncio
import json
import logging
import os
from datetime import datetime

import pytz
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ai_client import call_gemini_async, clean_for_telegram, client
from storage import health_store, memory_store, nutrition_store
from telegram_helpers import safe_delete_message, send_chunked_message, unique_temp_path

logger = logging.getLogger(__name__)
VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")


async def healthsetup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "💪 Sếp vui lòng nhập thông tin. VD:\n"
            "`/healthsetup Tôi 25 tuổi, nam, cao 1m70, nặng 65kg, dân văn phòng ít vận động, muốn giảm mỡ`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    status_msg = None
    try:
        status_msg = await send_chunked_message(
            update.message.reply_text, "⚙️ <i>Đang tính toán phác đồ dinh dưỡng chuẩn y khoa...</i>"
        )
        prompt = f"""Trích xuất thông tin sức khoẻ từ câu sau: "{text}".
        Trả về ĐÚNG định dạng JSON (không markdown, không giải thích):
        {{"age": 25, "gender": "male", "height_cm": 170, "weight_kg": 65, "activity_level": 1.2, "goal": "loss"}}
        Ghi chú activity_level: 1.2 (ít vận động), 1.375 (nhẹ), 1.55 (vừa), 1.725 (nặng), 1.9 (rất nặng). Goal: loss (giảm), gain (tăng), maintain (giữ)."""

        res = await call_gemini_async(prompt, is_json=True)
        data = json.loads(res)

        if data["gender"] == "male":
            bmr = (10 * data["weight_kg"]) + (6.25 * data["height_cm"]) - (5 * data["age"]) + 5
        else:
            bmr = (10 * data["weight_kg"]) + (6.25 * data["height_cm"]) - (5 * data["age"]) - 161

        tdee = bmr * data["activity_level"]
        target_calories = tdee
        if data["goal"] == "loss":
            target_calories -= 500
        elif data["goal"] == "gain":
            target_calories += 500

        protein = (target_calories * 0.4) / 4
        carb = (target_calories * 0.3) / 4
        fat = (target_calories * 0.3) / 9

        profile = {
            "age": data["age"],
            "height_cm": data["height_cm"],
            "weight_kg": data["weight_kg"],
            "tdee": int(tdee),
            "target_calories": int(target_calories),
            "macros": {"protein": int(protein), "carb": int(carb), "fat": int(fat)},
        }
        await health_store.write(profile)

        msg = (
            "📊 <b>HỒ SƠ DINH DƯỠNG ĐÃ THIẾT LẬP</b>\n\n"
            f"🔥 <b>TDEE (Calo giữ cân):</b> {int(tdee)} kcal/ngày\n"
            f"🎯 <b>Calo mục tiêu ({data['goal']}):</b> {int(target_calories)} kcal/ngày\n\n"
            f"🥩 <b>Protein (Cơ bắp):</b> {int(protein)}g\n"
            f"🍚 <b>Carb (Năng lượng):</b> {int(carb)}g\n"
            f"🥑 <b>Fat (Nội tiết):</b> {int(fat)}g\n\n"
            "<i>(Giờ sếp cứ chụp ảnh bữa ăn hoặc cái cân gửi vào đây, em sẽ tự trừ vào quỹ Calo hôm nay nhé!)</i>"
        )
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await send_chunked_message(update.message.reply_text, msg)
    except Exception as e:
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await update.message.reply_text(f"Lỗi: Không nhận diện được dữ liệu. Sếp nhập lại rõ hơn nhé! ({e})")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = None
    file_path = None
    try:
        status_msg = await send_chunked_message(update.message.reply_text, "👁️ <i>Đang soi hình ảnh...</i>")

        photo_file = await update.message.photo[-1].get_file()
        # BUG FIX: tên file duy nhất theo từng request (xem giải thích
        # trong telegram_helpers.unique_temp_path).
        file_path = unique_temp_path("photo", ".jpg")
        await photo_file.download_to_drive(file_path)

        health = await health_store.read()
        target = health.get("target_calories", 2000)

        memory = await memory_store.read()
        memory_ctx = "\n".join(f"- {r}" for r in memory.get("rules", [])) or "Không có."

        caption = update.message.caption or ""

        # client.files.upload là hàm BLOCKING (đồng bộ) -> chạy trong
        # thread riêng để không đơ event loop trong lúc upload ảnh.
        img = await asyncio.to_thread(client.files.upload, file=file_path)
        prompt = f"""Phân tích hình ảnh này. Hình ảnh có thể là 1 trong 2 loại:
        LOẠI 1: Ảnh đồ ăn/thức uống/cái cân. -> Bạn đóng vai chuyên gia dinh dưỡng, ước lượng calo.
        LOẠI 2: Ảnh chụp màn hình bài viết (Facebook, báo chí), biểu đồ, tài liệu, v.v. -> Bạn đóng vai Quân sư chiến lược. Đọc nội dung trong ảnh và phân tích sâu sắc, đa chiều (kết hợp với yêu cầu thêm của người dùng nếu có: '{caption}').

        TRẢ VỀ ĐÚNG ĐỊNH DẠNG JSON DUY NHẤT DƯỚI ĐÂY (không bọc trong thẻ markdown):
        {{
            "image_type": "food" hoặc "general",
            "food_data": {{
                "food_name": "Tên món", "calories": 500, "protein": 30, "carb": 40, "fat": 15, "advice": "Nhận xét 1 câu"
            }},
            "general_response": "Bài phân tích chi tiết, sâu sắc (dùng thẻ <b>, <i> chuẩn HTML, tuyệt đối không dùng markdown # hay **). Luôn tuân thủ luật bộ nhớ lõi: {memory_ctx}"
        }}
        Lưu ý: Nếu là LOẠI 2, hãy để food_data là null. Mục tiêu calo 1 ngày là {target} kcal."""

        res = await call_gemini_async([img, prompt], is_json=True)
        data = json.loads(res)

        if data.get("image_type") == "food" and data.get("food_data"):
            food = data["food_data"]
            today_str = datetime.now(VN_TZ).strftime("%Y-%m-%d")

            def _mutate(nutri):
                day = nutri.setdefault(
                    today_str, {"consumed_calories": 0, "protein": 0, "carb": 0, "fat": 0, "logs": []}
                )
                day["consumed_calories"] += food["calories"]
                day["protein"] += food["protein"]
                day["carb"] += food["carb"]
                day["fat"] += food["fat"]
                day["logs"].append(f"{food['food_name']} ({food['calories']} kcal)")
                return nutri

            nutri = await nutrition_store.update(_mutate)
            today = nutri[today_str]
            remaining = target - today["consumed_calories"]

            msg = (
                f"🍽️ <b>{food['food_name'].upper()}</b>\n\n"
                f"🔥 <b>Năng lượng:</b> {food['calories']} kcal\n"
                f"💪 <b>P/C/F (g):</b> {food['protein']} / {food['carb']} / {food['fat']}\n\n"
                f"💡 <i>{food['advice']}</i>\n\n"
                f"📉 <b>Tổng đã nạp hôm nay:</b> {today['consumed_calories']} / {target} kcal\n"
                f"🎯 <b>Quỹ Calo còn lại:</b> {remaining} kcal"
            )
            await safe_delete_message(context, update.message.chat_id, status_msg)
            await send_chunked_message(update.message.reply_text, msg)
        else:
            await safe_delete_message(context, update.message.chat_id, status_msg)
            await send_chunked_message(
                update.message.reply_text,
                clean_for_telegram(data.get("general_response", "Không thể trích xuất nội dung.")),
            )
    except Exception as e:
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await update.message.reply_text(f"⚠️ Lỗi phân tích ảnh: {e}")
    finally:
        # BUG FIX: bản gốc không bao giờ dọn dẹp file tạm.
        if file_path and os.path.exists(file_path):
            os.remove(file_path)


async def cook_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "🧑‍🍳 Sếp vui lòng nhập nguyên liệu hiện có. VD: `/cook 3 lạng thịt bò, cà chua, hành tây`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    status_msg = None
    try:
        status_msg = await send_chunked_message(
            update.message.reply_text, "🧑‍🍳 <i>Đang lục lọi tủ lạnh và sáng tạo công thức...</i>"
        )

        today_str = datetime.now(VN_TZ).strftime("%Y-%m-%d")
        health = await health_store.read()
        nutrition = await nutrition_store.read()
        nutri = nutrition.get(today_str, {})

        target = health.get("target_calories", 2000)
        consumed = nutri.get("consumed_calories", 0)
        remaining = target - consumed

        prompt = f"""Đóng vai một Siêu đầu bếp và Chuyên gia dinh dưỡng. Người dùng đang có các nguyên liệu sau: "{text}".
        Quỹ Calo còn lại trong ngày của họ là: {remaining} kcal.
        Hãy sáng tạo ra 1 món ăn NGON, dễ làm, và TỐI ƯU cho quỹ calo còn lại (không được vượt quá).

        Trình bày ĐẸP, NGẮN GỌN bằng HTML (sử dụng <b>, <i>, không dùng markdown # hay **):
        🍲 <b>TÊN MÓN ĂN</b> (Kèm mô tả sự hấp dẫn 1 câu)

        🛒 <b>Nguyên liệu cần dùng:</b> (Liệt kê định lượng)
        🔥 <b>Cách chế biến:</b> (3-4 bước cực kỳ ngắn gọn, dễ hiểu)

        📊 <b>Macro dự kiến:</b> Calories / Protein / Carb / Fat
        💡 <b>Mẹo đầu bếp:</b> (1 mẹo nhỏ để món ăn ngon hơn hoặc healthy hơn)"""

        res = await call_gemini_async(prompt)
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await send_chunked_message(update.message.reply_text, clean_for_telegram(res))
    except Exception as e:
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await update.message.reply_text(f"Lỗi nhà bếp: {e}")


async def food_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "🍽️ Sếp vui lòng nhập món ăn. VD: `/food 3 quả trứng luộc và 1 cốc sữa`", parse_mode=ParseMode.MARKDOWN
        )
        return

    status_msg = None
    try:
        status_msg = await send_chunked_message(update.message.reply_text, "🔍 <i>Đang soi món ăn và tính Calo...</i>")
        health = await health_store.read()
        target = health.get("target_calories", 2000)

        prompt = f"""Bạn là một chuyên gia dinh dưỡng. Người dùng vừa nhập thực đơn: "{text}".
        Mục tiêu 1 ngày của người dùng là nạp {target} Calories.
        Hãy ước lượng khẩu phần và tính toán.
        Trả về ĐÚNG định dạng JSON sau (không chứa ký tự thừa):
        {{"food_name": "Tóm tắt tên món", "calories": 500, "protein": 30, "carb": 40, "fat": 15, "advice": "Nhận xét ngắn gọn 1 câu xem món này có tốt cho mục tiêu không (kèm emoji)"}}"""

        res = (await call_gemini_async(prompt)).strip()
        data = json.loads(res)

        today_str = datetime.now(VN_TZ).strftime("%Y-%m-%d")

        def _mutate(nutri):
            day = nutri.setdefault(today_str, {"consumed_calories": 0, "protein": 0, "carb": 0, "fat": 0, "logs": []})
            day["consumed_calories"] += data["calories"]
            day["protein"] += data["protein"]
            day["carb"] += data["carb"]
            day["fat"] += data["fat"]
            day["logs"].append(f"{data['food_name']} ({data['calories']} kcal)")
            return nutri

        nutrition = await nutrition_store.update(_mutate)
        today = nutrition[today_str]
        remaining = target - today["consumed_calories"]

        msg = (
            f"🍽️ <b>{data['food_name'].upper()}</b>\n\n"
            f"🔥 <b>Năng lượng:</b> {data['calories']} kcal\n"
            f"💪 <b>P/C/F (g):</b> {data['protein']} / {data['carb']} / {data['fat']}\n\n"
            f"💡 <i>{data['advice']}</i>\n\n"
            f"📉 <b>Tổng đã nạp hôm nay:</b> {today['consumed_calories']} / {target} kcal\n"
            f"🎯 <b>Quỹ Calo còn lại:</b> {remaining} kcal"
        )
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await send_chunked_message(update.message.reply_text, msg)
    except Exception as e:
        await safe_delete_message(context, update.message.chat_id, status_msg)
        await update.message.reply_text(f"Lỗi soi chiếu món ăn: {e}")
