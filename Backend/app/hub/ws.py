"""WebSocket hub: ช่องทางแสดงผลแบบเรียลไทม์ไปยังหน้าเว็บของระบบ

ต่อที่  ws(s)://<assistant>/ws?tenant=<client>&key=<public_key>   (เบราว์เซอร์ส่ง Origin ให้เอง)

ข้อความจาก widget (ทุกข้อความใส่ req_id ได้ เพื่อจับคู่คำตอบ):
  {"type":"hello", "user_token"}                     ระบุตัวผู้ใช้ (ส่งใหม่ได้เมื่อ token เปลี่ยน)
  {"type":"chat", "message", "session_id"?}
  {"type":"confirm"|"cancel", "action_id"}
  {"type":"link", "agent", "username", "password"}   ผูกบัญชีระบบอื่น (auth กลาง)
  {"type":"unlink", "agent"}
  {"type":"call_result", "call_id", "status", "body"} ผลการเรียก API ที่เซิร์ฟเวอร์ขอ

ข้อความจากเซิร์ฟเวอร์:
  {"type":"ready", "agents":[...]}                   หลัง hello
  {"type":"status", "text", "agent"?}                 ความคืบหน้า เช่น "ส่งให้ผู้ช่วยของ Planka"
  {"type":"call", "call_id", "method", "path", "query", "body", "format"}
                                                      ขอให้หน้าเว็บเรียก API ระบบที่ฝัง widget (cookie ของผู้ใช้)
  {"type":"reply", ...ChatResponse}  {"type":"confirmed"|"cancelled"|"linked"|"unlinked", ...}
  {"type":"error", "status", "detail"}
"""
import asyncio
import logging
import secrets

from fastapi import WebSocket, WebSocketDisconnect

from app.auth import vault
from app.core import orchestrator
from app.errors import describe_error
from app.security import check_access
from app.services import bridge, pending
from app.services.turns import CALL_TIMEOUT, owner_of

log = logging.getLogger("assistant")


class Hub:
    """ทะเบียนการเชื่อมต่อของผู้ใช้แต่ละคน (เปิดหลายแท็บได้)"""

    def __init__(self):
        self._conns: dict[str, set["Connection"]] = {}

    def add(self, conn: "Connection") -> None:
        self._conns.setdefault(conn.owner, set()).add(conn)

    def remove(self, conn: "Connection") -> None:
        conns = self._conns.get(conn.owner)
        if conns:
            conns.discard(conn)
            if not conns:
                self._conns.pop(conn.owner, None)

    async def publish(self, owner: str, event: dict) -> None:
        """ส่งเหตุการณ์ไปทุกหน้าที่ผู้ใช้คนนี้เปิดอยู่ (เช่นงานที่เริ่มจาก HTTP API)"""
        for conn in list(self._conns.get(owner, ())):
            await conn.send(event)


hub = Hub()


class Connection:
    def __init__(self, ws: WebSocket, tenant_id: str):
        self.ws = ws
        self.tenant_id = tenant_id
        self.user_token = ""
        self.owner = ""
        self.job: asyncio.Task | None = None
        self.waiting: dict[str, asyncio.Future] = {}
        self._send_lock = asyncio.Lock()

    async def send(self, event: dict) -> None:
        async with self._send_lock:
            try:
                await self.ws.send_json(event)
            except Exception:  # หน้าเว็บปิดไปแล้ว
                pass

    # ---- Bridge (ดู app/services/bridge.py)
    async def http(self, method: str, path: str, query: dict, body,
                   body_format: str = "json") -> tuple[int, object]:
        call_id = secrets.token_urlsafe(8)
        fut = asyncio.get_running_loop().create_future()
        self.waiting[call_id] = fut
        await self.send({"type": "call", "call_id": call_id, "method": method, "path": path,
                         "query": query or {}, "body": body, "format": body_format})
        try:
            return await asyncio.wait_for(fut, CALL_TIMEOUT)
        except asyncio.TimeoutError:
            raise TimeoutError("หน้าเว็บไม่ได้ส่งผลการเรียกระบบหลักกลับมา") from None
        finally:
            self.waiting.pop(call_id, None)

    async def emit(self, event: dict) -> None:
        await self.send(event)

    # ---- งาน
    def _start(self, req_id, coro_factory) -> None:
        async def runner():
            bridge.use(self)
            try:
                await self.send({"req_id": req_id, **await coro_factory()})
            except asyncio.CancelledError:
                raise
            except Exception as e:
                status, detail = describe_error(e)
                await self.send({"type": "error", "req_id": req_id, "status": status, "detail": detail})
        self.job = asyncio.create_task(runner())

    async def handle(self, msg: dict) -> None:
        kind = msg.get("type")
        req_id = msg.get("req_id")

        if kind == "call_result":
            fut = self.waiting.get(str(msg.get("call_id")))
            if fut is not None and not fut.done():
                try:
                    fut.set_result((int(msg.get("status") or 0), msg.get("body")))
                except (TypeError, ValueError):
                    fut.set_result((502, {"message": "ผลการเรียกไม่ถูกต้อง"}))
            return

        if kind == "hello":
            token = str(msg.get("user_token") or "")
            if not token:
                await self.send({"type": "error", "req_id": req_id, "status": 400, "detail": "ไม่มี user_token"})
                return
            hub.remove(self)
            self.user_token, self.owner = token, owner_of(self.tenant_id, token)
            hub.add(self)
            agents = orchestrator.agents_status(self.tenant_id, token)
            await self.send({"type": "ready", "req_id": req_id,
                             "agents": [a.model_dump() for a in agents]})
            return

        if not self.user_token:
            await self.send({"type": "error", "req_id": req_id, "status": 401, "detail": "ต้องส่ง hello ก่อน"})
            return

        tenant, token = self.tenant_id, self.user_token

        if kind == "cancel":
            rec = pending.take(str(msg.get("action_id")), tenant, token)
            await self.send({"type": "cancelled", "req_id": req_id, "cancelled": rec is not None})
            return
        if kind == "unlink":
            removed = vault.remove(self.owner, str(msg.get("agent")))
            await self.send({"type": "unlinked", "req_id": req_id, "removed": removed})
            return

        if self.job is not None and not self.job.done():
            await self.send({"type": "error", "req_id": req_id, "status": 409,
                             "detail": "กำลังทำงานก่อนหน้าอยู่ กรุณารอสักครู่"})
            return

        if kind == "chat":
            message = str(msg.get("message") or "").strip()
            if not message:
                return

            async def do_chat():
                r = await orchestrator.chat(tenant, token, message, msg.get("session_id"))
                return {"type": "reply", **r.model_dump()}
            self._start(req_id, do_chat)
        elif kind == "confirm":
            action_id = str(msg.get("action_id"))
            rec = pending.take(action_id, tenant, token)
            if rec is None:
                await self.send({"type": "error", "req_id": req_id, "status": 404,
                                 "detail": "ไม่พบงานที่รอยืนยัน หรือหมดอายุแล้ว กรุณาสั่งใหม่"})
                return

            async def do_confirm():
                r = await orchestrator.confirm(rec, tenant, token)
                return {"type": "confirmed", "action_id": action_id, **r.model_dump()}
            self._start(req_id, do_confirm)
        elif kind == "link":
            async def do_link():
                info = await orchestrator.link(tenant, token, str(msg.get("agent")),
                                               str(msg.get("username") or ""), str(msg.get("password") or ""))
                agents = orchestrator.agents_status(tenant, token)
                return {"type": "linked", "agent": info.model_dump(),
                        "agents": [a.model_dump() for a in agents]}
            self._start(req_id, do_link)
        else:
            await self.send({"type": "error", "req_id": req_id, "status": 400, "detail": f"ไม่รู้จักคำสั่ง {kind}"})

    def close(self) -> None:
        hub.remove(self)
        if self.job is not None and not self.job.done():
            self.job.cancel()
        for fut in self.waiting.values():
            if not fut.done():
                fut.cancel()


async def serve(ws: WebSocket) -> None:
    tenant_id = ws.query_params.get("tenant", "")
    key = ws.query_params.get("key", "") or ws.headers.get("x-api-key", "")
    await ws.accept()
    try:
        check_access(key, ws.headers.get("origin", ""), tenant_id)
    except Exception as e:
        status, detail = describe_error(e)
        await ws.send_json({"type": "error", "status": status, "detail": detail})
        await ws.close(code=4000 + status)
        return

    conn = Connection(ws, tenant_id)
    try:
        while True:
            msg = await ws.receive_json()
            if isinstance(msg, dict):
                await conn.handle(msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("websocket error")
    finally:
        conn.close()
