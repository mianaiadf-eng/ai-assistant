"""Chat API: POST /login, POST /chat, GET /health"""
import logging
import secrets

import anthropic
import openai
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.adapters.base import AdapterError, NotSupported
from app.adapters.registry import get_adapter
from app.config import APP_API_KEY, CORS_ORIGINS, LLM_PROVIDER
from app.core.assistant import chat
from app.schemas import ChatRequest, ChatResponse, LoginRequest, LoginResponse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("assistant")

app = FastAPI(title="University AI Assistant", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


def verify_key(x_api_key: str = Header(default="")):
    ok = bool(APP_API_KEY) and secrets.compare_digest(
        x_api_key.encode("utf-8"), APP_API_KEY.encode("utf-8")
    )
    if not ok:
        raise HTTPException(status_code=401, detail="invalid api key")


@app.get("/health")
async def health():
    return {"status": "ok", "llm_provider": LLM_PROVIDER}


@app.post("/login", response_model=LoginResponse)
async def login_endpoint(req: LoginRequest, _: None = Depends(verify_key)):
    try:
        adapter = get_adapter(req.tenant_id, "")
        token = await adapter.login(req.username, req.password)
        return LoginResponse(token=token)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e.args[0]))
    except NotSupported as e:
        raise HTTPException(status_code=501, detail=str(e))
    except AdapterError as e:
        raise HTTPException(status_code=401, detail=str(e))


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
    except (anthropic.APIConnectionError, openai.APIConnectionError):
        raise HTTPException(status_code=503, detail="เชื่อมต่อโมเดล AI ไม่ได้ ตรวจว่า Ollama รันอยู่")
    except (anthropic.APITimeoutError, openai.APITimeoutError):
        raise HTTPException(status_code=504, detail="โมเดล AI ตอบช้าเกินไป ลองใหม่อีกครั้ง")
    except (anthropic.APIError, openai.APIError) as e:
        log.exception("LLM error")
        raise HTTPException(status_code=502, detail=f"เรียกโมเดลไม่สำเร็จ: {type(e).__name__}")
    except Exception:
        log.exception("unexpected error")
        raise HTTPException(status_code=500, detail="เกิดข้อผิดพลาดภายในระบบ")