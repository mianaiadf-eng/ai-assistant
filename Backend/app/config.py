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


def _load_tenants() -> dict:
    path = BASE_DIR / "tenants.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


TENANTS: dict = _load_tenants()