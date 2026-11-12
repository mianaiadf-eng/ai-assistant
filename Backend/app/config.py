"""ตั้งค่าระบบ: โหลด .env และ tenants.json

tenants.json เก็บ "ระบบที่ฝัง widget" (client) เท่านั้น เช่น key, origin, ที่อยู่ token ในหน้าเว็บ
ความรู้และวิธีทำงานกับแต่ละระบบอยู่ใน sub agent (โฟลเดอร์ agents/<ชื่อ>/)
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
AGENTS_DIR = BASE_DIR / "agents"

# override=True ให้ค่าใน .env ชนะค่าเก่าที่อาจค้างในเทอร์มินัล
load_dotenv(BASE_DIR / ".env", override=True)


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


APP_API_KEY = env("APP_API_KEY")
TIMEZONE = env("TIMEZONE", "Asia/Bangkok")

# เลือกสมอง: "openai" = API รูปแบบ OpenAI (ค่าเริ่มต้น ใช้ Typhoon) หรือ "claude" (มีค่าใช้จ่าย ไม่ใช้เป็นหลัก)
LLM_PROVIDER = env("LLM_PROVIDER", "openai").lower()

# โมเดลที่ใช้รูปแบบ OpenAI (Typhoon, Qwen ผ่าน Ollama, OpenRouter ฯลฯ)
LLM_BASE_URL = env("LLM_BASE_URL", "https://api.opentyphoon.ai/v1")
LLM_API_KEY = env("LLM_API_KEY")
LLM_MODEL = env("LLM_MODEL", "typhoon-v2.5-30b-a3b-instruct")

# Claude (ทางเลือก)
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", "claude-sonnet-5-5")

# CORS: ใส่โดเมนของหน้าเว็บ คั่นด้วยจุลภาค เช่น http://localhost:5500,http://localhost:3000
CORS_ORIGINS = [o.strip() for o in env("CORS_ORIGINS", "*").split(",") if o.strip()]

# timeout (วินาที)
LLM_TIMEOUT = float(env("LLM_TIMEOUT", "120") or 120)
HTTP_TIMEOUT = float(env("HTTP_TIMEOUT", "15") or 15)

# auth กลาง: token ของระบบที่ผู้ใช้ผูกไว้ หมดอายุหลังไม่ได้ใช้กี่วินาที
LINK_TTL = int(env("LINK_TTL", "28800") or 28800)


def _load_tenants() -> dict:
    path = BASE_DIR / "tenants.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


TENANTS: dict = _load_tenants()
