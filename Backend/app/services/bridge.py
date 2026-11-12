"""ช่องทางกลับไปหาหน้าเว็บของผู้ใช้ ระหว่างที่งานหนึ่งกำลังทำอยู่

มีสองแบบที่ทำงานเหมือนกัน:
- WebSocket (app/hub/ws.py)       ใช้กับ widget รุ่นปัจจุบัน แสดงสถานะแบบเรียลไทม์ได้
- HTTP turn (app/services/turns.py) ใช้กับสคริปต์/ไคลเอนต์ที่ไม่มี WebSocket

ทั้งสองแบบทำได้สองอย่าง:
- http(...)  ขอให้หน้าเว็บเรียก API ของระบบที่ฝัง widget อยู่ ด้วย cookie/session ของผู้ใช้
- emit(...)  ส่งเหตุการณ์ (เช่น สถานะ "กำลังเรียก ...") ไปแสดงที่หน้าเว็บ
"""
import contextvars
from typing import Protocol


class Bridge(Protocol):
    owner: str

    async def http(self, method: str, path: str, query: dict, body,
                   body_format: str = "json") -> tuple[int, object]: ...

    async def emit(self, event: dict) -> None: ...


_current: contextvars.ContextVar[Bridge | None] = contextvars.ContextVar("bridge", default=None)


def current() -> Bridge | None:
    return _current.get()


def use(bridge: Bridge | None) -> None:
    """ตั้ง bridge ของงานปัจจุบัน (เรียกใน task ของงานนั้นเท่านั้น)"""
    _current.set(bridge)


async def emit(owner: str, event: dict) -> None:
    """ส่งเหตุการณ์ไปที่หน้าเว็บ: ผ่าน bridge ของงานนี้ หรือกระจายผ่าน hub ไปทุกหน้าของผู้ใช้"""
    b = current()
    if b is not None and hasattr(b, "emit"):
        await b.emit(event)
        return
    from app.hub.ws import hub  # import ช้า กันวงจร import
    await hub.publish(owner, event)
