"""ให้เบราว์เซอร์ (widget) เป็นคนเรียก API ของระบบหลัก

ทำไม: ระบบหลักหลายตัว (เช่น Planka) ผูก token ของหน้าเว็บกับ cookie แบบ httpOnly
token ที่ widget อ่านได้จึงใช้ได้เฉพาะเมื่อส่งจากเบราว์เซอร์ในเว็บเดียวกันเท่านั้น
และ AI ก็ทำได้ไม่เกินสิทธิ์ของผู้ใช้คนนั้นพอดี

วิธีทำงาน: งาน (เช่นแชต 1 ข้อความ) รันเป็น task ค้างไว้ในหน่วยความจำ
เมื่อโค้ดต้องเรียก API ระบบหลัก (Catalog.call) จะส่ง "คำขอ" ออกมาเป็นคำตอบของ HTTP request
widget เรียก API เอง แล้วส่งผลกลับที่ /turn/{turn_id} งานจึงทำต่อจากจุดเดิม
(การตรวจกฎทั้งหมด เช่น ห้ามเดา id และขั้นยืนยัน ยังอยู่ฝั่งเซิร์ฟเวอร์เหมือนเดิม)

ข้อจำกัด: เก็บในหน่วยความจำของ process เดียว (ถ้ารันหลาย instance ต้องย้ายไปใช้ sticky session หรือคิว)
"""
import asyncio
import contextvars
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field

log = logging.getLogger("assistant")

CALL_TIMEOUT = 120      # วินาทีที่รอให้ widget ส่งผลการเรียก API กลับมา
EVENT_TIMEOUT = 300     # วินาทีที่ HTTP request หนึ่งรองานคืบหน้า (LLM อาจช้า)
TURN_TTL = 600

_bridge: contextvars.ContextVar["Turn | None"] = contextvars.ContextVar("browser_bridge", default=None)


class TurnError(Exception):
    """turn ไม่มีอยู่/หมดอายุ/ไม่ใช่ของผู้ใช้นี้"""


def owner_of(tenant_id: str, user_token: str) -> str:
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
        """เรียกจาก Catalog.call: ขอให้ widget เรียก API แล้วรอผล"""
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


_turns: dict[str, Turn] = {}


def active_bridge() -> Turn | None:
    return _bridge.get()


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
    """เริ่มงานที่อาจต้องให้เบราว์เซอร์เรียก API (coro_factory: ฟังก์ชันที่คืน coroutine)"""
    _purge()
    turn = Turn(id=secrets.token_urlsafe(16), owner=owner_of(tenant_id, user_token))
    _turns[turn.id] = turn

    async def runner():
        _bridge.set(turn)
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
