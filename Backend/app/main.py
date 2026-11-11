"""Chat API: POST /login, /chat, /confirm, /cancel, GET /health, /widget/config/{tenant}, /widget.js, /turn/{id}"""
import logging
from pathlib import Path

import anthropic
import openai
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.adapters.base import AdapterError, NotSupported
from app.adapters.registry import get_adapter
from app.catalog.catalog import get_catalog, is_catalog_tenant
from app.config import CORS_ORIGINS, LLM_PROVIDER
from app.core.assistant import chat
from app.core.tools import REGISTRY
from app.core.toolsets import CATALOG_TOOL, execute_confirmed
from app.security import authorize, widget_config
from app.schemas import (
    ChatRequest, ChatResponse, ConfirmRequest, ConfirmResponse,
    LoginRequest, LoginResponse, TurnCall, TurnResult,
)
from app.services import pending, turns
from app.services.turns import TurnError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("assistant")

app = FastAPI(title="University AI Assistant", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


_STATIC = Path(__file__).parent / "static"


@app.get("/widget.js", include_in_schema=False)
async def widget_js():
    return FileResponse(_STATIC / "widget.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/playground", include_in_schema=False)
async def playground():
    return FileResponse(_STATIC / "playground.html", headers={"Cache-Control": "no-cache"})


@app.get("/widget/config/{tenant_id}")
async def widget_config_endpoint(tenant_id: str, request: Request):
    authorize(request, tenant_id)
    return widget_config(tenant_id)


@app.get("/health")
async def health():
    return {"status": "ok", "llm_provider": LLM_PROVIDER}


@app.post("/login", response_model=LoginResponse)
async def login_endpoint(req: LoginRequest, request: Request):
    authorize(request, req.tenant_id)
    try:
        if is_catalog_tenant(req.tenant_id):
            token = await get_catalog(req.tenant_id).login(req.username, req.password)
        else:
            token = await get_adapter(req.tenant_id, "").login(req.username, req.password)
        return LoginResponse(token=token)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e.args[0]))
    except NotSupported as e:
        raise HTTPException(status_code=501, detail=str(e))
    except AdapterError as e:
        raise HTTPException(status_code=401, detail=str(e))


def _http_error(e: Exception) -> HTTPException:
    """แปลง exception จากงาน (แชต/ยืนยัน) เป็นข้อความที่ผู้ใช้อ่านเข้าใจ"""
    if isinstance(e, HTTPException):
        return e
    if isinstance(e, TurnError):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, KeyError):
        return HTTPException(status_code=404, detail=str(e.args[0]))
    if isinstance(e, NotSupported):
        return HTTPException(status_code=501, detail=str(e))
    if isinstance(e, AdapterError):
        return HTTPException(status_code=502, detail=str(e))
    if isinstance(e, TimeoutError):
        return HTTPException(status_code=504, detail=str(e) or "ใช้เวลานานเกินไป ลองใหม่อีกครั้ง")
    if isinstance(e, ValueError):
        return HTTPException(status_code=500, detail=str(e))
    if isinstance(e, anthropic.AuthenticationError):
        return HTTPException(status_code=502,
                             detail="ANTHROPIC_API_KEY ไม่ถูกต้อง ตรวจไฟล์ .env แล้วรีสตาร์ทเซิร์ฟเวอร์")
    if isinstance(e, (anthropic.APIConnectionError, openai.APIConnectionError)):
        return HTTPException(status_code=503, detail="เชื่อมต่อโมเดล AI ไม่ได้")
    if isinstance(e, (anthropic.APITimeoutError, openai.APITimeoutError)):
        return HTTPException(status_code=504, detail="โมเดล AI ตอบช้าเกินไป ลองใหม่อีกครั้ง")
    if isinstance(e, (anthropic.APIError, openai.APIError)):
        log.error("LLM error: %r", e)
        return HTTPException(status_code=502, detail=f"เรียกโมเดลไม่สำเร็จ: {type(e).__name__}")
    log.error("unexpected error", exc_info=e)
    return HTTPException(status_code=500, detail="เกิดข้อผิดพลาดภายในระบบ")


async def _run(coro_factory, tenant_id: str, user_token: str, client_exec: bool):
    """client_exec + tenant แบบ catalog = ให้ widget เรียก API ระบบหลักเอง
    คำตอบอาจเป็น {"turn_id","call"} (widget ต้องเรียก API แล้วส่งผลที่ /turn/{turn_id})"""
    try:
        if client_exec and is_catalog_tenant(tenant_id):
            return await turns.start(coro_factory, tenant_id, user_token)
        return await coro_factory()
    except Exception as e:
        raise _http_error(e) from e


@app.post("/chat", response_model=ChatResponse | TurnCall)
async def chat_endpoint(req: ChatRequest, request: Request):
    authorize(request, req.tenant_id)
    return await _run(lambda: chat(req), req.tenant_id, req.user_token, req.client_exec)


async def _confirm(rec, req: ConfirmRequest) -> ConfirmResponse:
    if rec.tool == CATALOG_TOOL:
        message = await execute_confirmed(
            get_catalog(req.tenant_id), rec.args, rec.summary, req.user_token
        )
    else:
        tool = REGISTRY.get(rec.tool)
        if tool is None:
            raise HTTPException(status_code=404, detail="ไม่รู้จักงานนี้")
        adapter = get_adapter(req.tenant_id, req.user_token)
        message = await tool.run(adapter, rec.args, {})
    log.info("CONFIRMED tool=%s risk=%s tenant=%s args=%s",
             rec.tool, rec.risk, rec.tenant_id, rec.args)  # ไม่ log token
    return ConfirmResponse(message=message)


@app.post("/confirm", response_model=ConfirmResponse | TurnCall)
async def confirm_endpoint(req: ConfirmRequest, request: Request):
    authorize(request, req.tenant_id)
    rec = pending.take(req.action_id, req.tenant_id, req.user_token)
    if rec is None:
        raise HTTPException(status_code=404, detail="ไม่พบงานที่รอยืนยัน หรือหมดอายุแล้ว กรุณาสั่งใหม่")
    return await _run(lambda: _confirm(rec, req), req.tenant_id, req.user_token, req.client_exec)


@app.post("/turn/{turn_id}", response_model=ChatResponse | ConfirmResponse | TurnCall)
async def turn_endpoint(turn_id: str, req: TurnResult, request: Request):
    """widget ส่งผลการเรียก API ระบบหลักกลับมา งานที่พักไว้ทำต่อ"""
    authorize(request, req.tenant_id)
    try:
        return await turns.resume(turn_id, req.tenant_id, req.user_token,
                                  req.call_id, req.status, req.body)
    except Exception as e:
        raise _http_error(e) from e


@app.post("/cancel")
async def cancel_endpoint(req: ConfirmRequest, request: Request):
    authorize(request, req.tenant_id)
    rec = pending.take(req.action_id, req.tenant_id, req.user_token)
    return {"cancelled": rec is not None}
