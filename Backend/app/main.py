"""Chat API: POST /chat, GET /health"""
import secrets

import anthropic
import openai
from fastapi import Depends, FastAPI, Header, HTTPException

from app.config import APP_API_KEY, LLM_PROVIDER
from app.core.assistant import chat
from app.schemas import ChatRequest, ChatResponse

app = FastAPI(title="University AI Assistant", version="0.1.0")


def verify_key(x_api_key: str = Header(default="")):
    ok = bool(APP_API_KEY) and secrets.compare_digest(
        x_api_key.encode("utf-8"), APP_API_KEY.encode("utf-8")
    )
    if not ok:
        raise HTTPException(status_code=401, detail="invalid api key")


@app.get("/health")
async def health():
    return {"status": "ok", "llm_provider": LLM_PROVIDER}


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest, _: None = Depends(verify_key)):
    try:
        return await chat(req)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e.args[0]))
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except anthropic.AuthenticationError:
        raise HTTPException(
            status_code=502,
            detail="ANTHROPIC_API_KEY ไม่ถูกต้อง ตรวจไฟล์ .env แล้วรีสตาร์ทเซิร์ฟเวอร์",
        )
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"เรียก Claude ไม่สำเร็จ: {type(e).__name__}")
    except openai.APIError as e:
        raise HTTPException(
            status_code=502,
            detail=f"เรียกโมเดลไม่สำเร็จ: {type(e).__name__} ตรวจ LLM_BASE_URL / LLM_MODEL ใน .env และเช็กว่า Ollama รันอยู่",
        )