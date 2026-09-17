import os
import re
import asyncio
from google import genai
from config import GEMINI_API_KEY, GEMINI_MODEL

client = genai.Client(api_key=GEMINI_API_KEY)

def call_gemini_robust(prompt, model=GEMINI_MODEL):
    import time
    for attempt in range(3):
        try:
            current_model = model
            if attempt == 1:
                current_model = "gemini-flash-latest"
            elif attempt == 2:
                current_model = "gemini-flash-lite-latest"
            
            res = client.models.generate_content(
                model=current_model,
                contents=prompt,
            )
            return res.text
        except Exception as e:
            if attempt == 2:
                raise e
            time.sleep(1)
    return ""

async def call_gemini_async(prompt, model=GEMINI_MODEL):
    return await asyncio.to_thread(call_gemini_robust, prompt, model)

def clean_for_telegram(text: str) -> str:
    text = re.sub(r"<h[1-6][^>]*>(.*?)</h[1-6]>", r"<b>\1</b>", text, flags=re.IGNORECASE|re.DOTALL)
    text = re.sub(r"</?(p|div|ul|ol|li|span|br)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"^#{1,6}\s+(.*)", r"<b>\1</b>", text, flags=re.MULTILINE)
    text = text.replace("```", "")
    return text.strip()

def parse_amount(amount_str: str) -> int:
    amount_str = amount_str.lower().replace(",", "").replace(".", "").strip()
    if "k" in amount_str:
        return int(float(amount_str.replace("k", "")) * 1_000)
    if "m" in amount_str or "tr" in amount_str:
        return int(float(amount_str.replace("m", "").replace("tr", "")) * 1_000_000)
    return int(amount_str)

from telegraph import Telegraph
telegraph_client = Telegraph()
try:
    telegraph_client.create_account(short_name='LifeOS')
except Exception:
    pass
