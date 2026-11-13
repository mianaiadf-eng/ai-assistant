"""จำกัดความถี่การเรียก (ในหน่วยความจำ ใช้กับ process เดียว)"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException

MAX_MESSAGE_CHARS = 2000

_hits: dict[str, deque] = defaultdict(deque)


def _cleanup(now: float) -> None:
    for k in [k for k, q in _hits.items() if not q or now - q[-1] > 3600]:
        del _hits[k]


def allow(key: str, limit: int, window: int) -> bool:
    """True = ผ่าน (นับเป็น 1 ครั้ง) / False = เกินกำหนด"""
    now = time.time()
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    if len(_hits) > 10000:
        _cleanup(now)
    return True


def enforce(key: str, limit: int, window: int) -> None:
    if not allow(key, limit, window):
        raise HTTPException(status_code=429, detail="ลองบ่อยเกินไป กรุณารอสักครู่แล้วลองใหม่")