"""bridge แบบ HTTP: ให้ไคลเอนต์ที่ไม่มี WebSocket เป็นคนเรียก API ของระบบที่ฝัง widget

ทำไม: ระบบหลายตัว (เช่น Planka) ผูก token ของหน้าเว็บกับ cookie แบบ httpOnly
token จึงใช้ได้เฉพาะเมื่อส่งจากเบราว์เซอร์ในเว็บเดียวกัน และ AI ทำได้ไม่เกินสิทธิ์ของผู้ใช้คนนั้น

วิธีทำงาน: งาน (เช่นแชต 1 ข้อความ) รันเป็น task ค้างไว้ในหน่วยความจำ
เมื่อโค้ดต้องเรียก API (AgentCtx.http) จะส่ง "คำขอ" ออกมาเป็นคำตอบของ HTTP request
ไคลเอนต์เรียก API เอง แล้วส่งผลกลับที่ /turn/{turn_id} งานจึงทำต่อจากจุดเดิม
(widget รุ่นปัจจุบันใช้ WebSocket แทน ดู app/hub/ws.py)

ข้อจำกัด: เก็บในหน่วยความจำของ process เดียว (ถ้ารันหลาย instance ต้องใช้ sticky session หรือคิว)
"""
import asyncio
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field

from app.services import bridge

log = logging.getLogger("assistant")

CALL_TIMEOUT = 120      # วินาทีที่รอให้ไคลเอนต์ส่งผลการเรียก API กลับมา
EVENT_TIMEOUT = 300     # วินาทีที่ HTTP request หนึ่งรองานคืบหน้า (LLM อาจช้า)
TURN_TTL = 600


class TurnError(Exception):
    """turn ไม่มีอยู่/หมดอายุ/ไม่ใช่ของผู้ใช้นี้"""


def owner_of(tenant_id: str, user_token: str) -> str:
    """ตัวตนของผู้ใช้ใน assistant = client + token ของผู้ใช้ในหน้านั้น (ไม่เก็บ token ตรง ๆ)"""
    return hashlib.sha256(f"{tenant_id}:{user_token}".encode("utf-8")).hexdigest()


@dataclass
class Turn:
    id: str
    owner: str
    events: asyncio.Queue = field(default_factory=asyncio.Queue)
    waiting: dict = field(default_factory=dict)   # call_id -> Future
    task: asyncio.Task | None = None
    created: float = field(default_factory=time.time)

    async def http(self, method: str, path: str, query: dict, body,
                   body_format: str = "json") -> tuple[int, object]:
        call_id = secrets.token_urlsafe(8)
        fut = asyncio.get_running_loop().create_future()
        self.waiting[call_id] = fut
        await self.events.put(("call", {
            "call_id": call_id, "method": method, "path": path,
            "query": query or {}, "body": body, "format": body_format,
        }))
        try:
            return await asyncio.wait_for(fut, CALL_TIMEOUT)
        except asyncio.TimeoutError:
            raise TimeoutError("หน้าเว็บไม่ได้ส่งผลการเรียกระบบหลักกลับมา") from None
        finally:
            self.waiting.pop(call_id, None)

    async def emit(self, event: dict) -> None:
        # HTTP ส่งสถานะระหว่างทางไม่ได้ ให้ hub กระจายไปยังหน้าเว็บของผู้ใช้ที่ต่อ WebSocket อยู่ (ถ้ามี)
        from app.hub.ws import hub
        await hub.publish(self.owner, event)


_turns: dict[str, Turn] = {}


def _purge() -> None:
    now = time.time()
    for tid in [t for t, v in _turns.items() if now - v.created > TURN_TTL]:
        turn = _turns.pop(tid)
        if turn.task and not turn.task.done():
            turn.task.cancel()


async def _next(turn: Turn) -> dict:
    """รอเหตุการณ์ถัดไป: คำขอเรียก API -> {"turn_id","call"}; เสร็จ -> ผลลัพธ์; error -> raise"""
    try:
        kind, value = await asyncio.wait_for(turn.events.get(), EVENT_TIMEOUT)
    except asyncio.TimeoutError:
        _turns.pop(turn.id, None)
        if turn.task:
            turn.task.cancel()
        raise TimeoutError("ใช้เวลานานเกินไป ลองใหม่อีกครั้ง") from None
    if kind == "call":
        return {"turn_id": turn.id, "call": value}
    _turns.pop(turn.id, None)
    if kind == "error":
        raise value
    return value


async def start(coro_factory, tenant_id: str, user_token: str):
    """เริ่มงานที่อาจต้องให้ไคลเอนต์เรียก API (coro_factory: ฟังก์ชันที่คืน coroutine)"""
    _purge()
    turn = Turn(id=secrets.token_urlsafe(16), owner=owner_of(tenant_id, user_token))
    _turns[turn.id] = turn

    async def runner():
        bridge.use(turn)
        try:
            await turn.events.put(("done", await coro_factory()))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # ส่งต่อให้ endpoint แปลงเป็น HTTP error
            await turn.events.put(("error", e))

    turn.task = asyncio.create_task(runner())
    return await _next(turn)


async def resume(turn_id: str, tenant_id: str, user_token: str,
                 call_id: str, status: int, body) -> object:
    turn = _turns.get(turn_id)
    if turn is None or not secrets.compare_digest(turn.owner, owner_of(tenant_id, user_token)):
        raise TurnError("ไม่พบงานนี้ หรือหมดเวลาแล้ว กรุณาสั่งใหม่")
    fut = turn.waiting.get(call_id)
    if fut is None or fut.done():
        raise TurnError("ไม่พบคำขอนี้ในงาน")
    fut.set_result((int(status), body))
    return await _next(turn)
