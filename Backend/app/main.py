"""API ของผู้ช่วย
- WebSocket /ws                       ช่องทางหลักของ widget (เรียลไทม์) ดู app/hub/ws.py
- HTTP /chat /confirm /cancel /turn    สำหรับสคริปต์/ไคลเอนต์ที่ไม่ใช้ WebSocket
- HTTP /auth/link /auth/unlink /agents auth กลาง: ผูกบัญชีระบบอื่น และดูสถานะ
- GET /health /widget.js /playground /widget/config/{tenant}"""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.auth import vault
from app.config import CORS_ORIGINS, LLM_MODEL, LLM_PROVIDER
from app.core import orchestrator
from app.errors import describe_error
from app.hub import ws as ws_hub
from app.schemas import (
    AgentInfo, ChatRequest, ChatResponse, ConfirmRequest, ConfirmResponse,
    LinkRequest, TurnCall, TurnResult, UnlinkRequest, UserRef,
)
from app.security import authorize, widget_config
from app.services import pending, turns
from app.services.turns import owner_of
from app.subagent import registry

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("assistant")

app = FastAPI(title="AI Assistant (Plug-in)", version="0.4.0")

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
    return {"status": "ok", "llm_provider": LLM_PROVIDER, "llm_model": LLM_MODEL,
            "agents": sorted(registry.all_agents())}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_hub.serve(ws)


def _http_error(e: Exception) -> HTTPException:
    status, detail = describe_error(e)
    return HTTPException(status_code=status, detail=detail)


async def _run(coro_factory, tenant_id: str, user_token: str, client_exec: bool):
    """client_exec = ให้ไคลเอนต์เรียก API ระบบที่ฝัง widget เอง
    คำตอบอาจเป็น {"turn_id","call"} (ไคลเอนต์ต้องเรียก API แล้วส่งผลที่ /turn/{turn_id})"""
    try:
        if client_exec:
            return await turns.start(coro_factory, tenant_id, user_token)
        return await coro_factory()
    except Exception as e:
        raise _http_error(e) from e


@app.post("/chat", response_model=ChatResponse | TurnCall)
async def chat_endpoint(req: ChatRequest, request: Request):
    authorize(request, req.tenant_id)
    return await _run(lambda: orchestrator.chat(req.tenant_id, req.user_token, req.message, req.session_id),
                      req.tenant_id, req.user_token, req.client_exec)


@app.post("/confirm", response_model=ConfirmResponse | TurnCall)
async def confirm_endpoint(req: ConfirmRequest, request: Request):
    authorize(request, req.tenant_id)
    rec = pending.take(req.action_id, req.tenant_id, req.user_token)
    if rec is None:
        raise HTTPException(status_code=404, detail="ไม่พบงานที่รอยืนยัน หรือหมดอายุแล้ว กรุณาสั่งใหม่")
    return await _run(lambda: orchestrator.confirm(rec, req.tenant_id, req.user_token),
                      req.tenant_id, req.user_token, req.client_exec)


@app.post("/turn/{turn_id}", response_model=ChatResponse | ConfirmResponse | TurnCall)
async def turn_endpoint(turn_id: str, req: TurnResult, request: Request):
    """ไคลเอนต์ส่งผลการเรียก API ระบบที่ฝัง widget กลับมา งานที่พักไว้ทำต่อ"""
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


# ------------------------------------------------------------ auth กลาง

@app.post("/auth/link", response_model=AgentInfo)
async def link_endpoint(req: LinkRequest, request: Request):
    """ผูกบัญชีระบบหนึ่ง: ล็อกอินด้วยบัญชีของผู้ใช้ แล้วเก็บ token ไว้ให้ sub agent ของระบบนั้น"""
    authorize(request, req.tenant_id)
    try:
        return await orchestrator.link(req.tenant_id, req.user_token, req.agent, req.username, req.password)
    except Exception as e:
        status, detail = describe_error(e)
        raise HTTPException(status_code=401 if status == 502 else status, detail=detail) from e


@app.post("/auth/unlink")
async def unlink_endpoint(req: UnlinkRequest, request: Request):
    authorize(request, req.tenant_id)
    return {"removed": vault.remove(owner_of(req.tenant_id, req.user_token), req.agent)}


@app.post("/agents", response_model=list[AgentInfo])
async def agents_endpoint(req: UserRef, request: Request):
    """รายการ sub agent ที่ client นี้ใช้ได้ พร้อมสถานะการผูกบัญชีของผู้ใช้"""
    authorize(request, req.tenant_id)
    try:
        return orchestrator.agents_status(req.tenant_id, req.user_token)
    except Exception as e:
        raise _http_error(e) from e
