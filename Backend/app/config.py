"""ตั้งค่าระบบ: โหลด .env และ tenants.json"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# override=True ให้ค่าใน .env ชนะค่าเก่าที่อาจค้างในเทอร์มินัล
load_dotenv(BASE_DIR / ".env", override=True)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


APP_API_KEY = _env("APP_API_KEY")
TIMEZONE = _env("TIMEZONE", "Asia/Bangkok")

# เลือกสมอง: "claude" หรือ "openai"
LLM_PROVIDER = _env("LLM_PROVIDER", "claude").lower()

# Claude
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _env("ANTHROPIC_MODEL", "claude-sonnet-5-5")

# โมเดลที่ใช้รูปแบบ OpenAI (Qwen ผ่าน Ollama, OpenRouter ฯลฯ)
LLM_BASE_URL = _env("LLM_BASE_URL")
LLM_API_KEY = _env("LLM_API_KEY")
LLM_MODEL = _env("LLM_MODEL")

# CORS: ใส่โดเมนของหน้าเว็บ คั่นด้วยจุลภาค เช่น http://localhost:5500,http://localhost:3000
CORS_ORIGINS = [o.strip() for o in _env("CORS_ORIGINS", "*").split(",") if o.strip()]

# timeout (วินาที)
LLM_TIMEOUT = float(_env("LLM_TIMEOUT", "120") or 120)
HTTP_TIMEOUT = float(_env("HTTP_TIMEOUT", "15") or 15)
def _load_tenants() -> dict:
    path = BASE_DIR / "tenants.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


TENANTS: dict = _load_tenants()