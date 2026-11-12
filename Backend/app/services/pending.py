"""เก็บงานเขียนที่รอผู้ใช้ยืนยัน (ใน memory ปิดเซิร์ฟเวอร์แล้วหาย งานจริงย้ายไป Redis/DB)
- id เดาไม่ได้ ใช้ได้ครั้งเดียว หมดอายุใน 5 นาที ผูกกับผู้ใช้+client
- จำว่างานนี้เป็นของ sub agent ตัวไหน เพื่อให้ /confirm ส่งกลับไปทำที่ตัวเดิม"""
import secrets
import time
from dataclasses import dataclass

from app.services.turns import owner_of

TTL_SECONDS = 300


@dataclass
class PendingRecord:
    id: str
    agent: str
    tool: str
    args: dict
    summary: str
    risk: str
    tenant_id: str
    owner: str
    expires_at: float


_store: dict[str, PendingRecord] = {}


def _purge() -> None:
    now = time.time()
    for k in [k for k, v in _store.items() if v.expires_at < now]:
        del _store[k]


def create(agent: str, tool: str, args: dict, summary: str, risk: str,
           tenant_id: str, owner: str) -> PendingRecord:
    _purge()
    rec = PendingRecord(
        id=secrets.token_urlsafe(16), agent=agent,
        tool=tool, args=args, summary=summary, risk=risk,
        tenant_id=tenant_id, owner=owner,
        expires_at=time.time() + TTL_SECONDS,
    )
    _store[rec.id] = rec
    return rec


def take(action_id: str, tenant_id: str, user_token: str) -> PendingRecord | None:
    """ดึงงานออกมา (ใช้ได้ครั้งเดียว) ต้องเป็นเจ้าของและยังไม่หมดอายุ"""
    _purge()
    rec = _store.get(action_id)
    if rec is None:
        return None
    if not secrets.compare_digest(rec.owner, owner_of(tenant_id, user_token)):
        return None
    return _store.pop(action_id)
