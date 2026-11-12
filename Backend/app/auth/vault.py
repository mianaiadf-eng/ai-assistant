"""auth กลาง: ตัวกลางเก็บ token ของแต่ละระบบให้ผู้ใช้ เพื่อให้ sub agent เข้าถึงระบบนั้นได้

ผู้ใช้หนึ่งคน (owner = client + token ของหน้าที่ฝัง widget) ผูกบัญชีได้หลายระบบ
- ระบบที่ฝัง widget อยู่ (host): ใช้ token/cookie ของหน้าเว็บนั้นเลย ไม่ต้องเก็บที่นี่
- ระบบอื่น: ผู้ใช้ล็อกอินผ่าน widget หนึ่งครั้ง (/auth/link) แล้ว token เก็บไว้ที่นี่
  sub agent ของระบบนั้นเรียก API จากเซิร์ฟเวอร์ด้วย token นี้ (ได้สิทธิ์เท่าผู้ใช้คนนั้นพอดี)

ข้อจำกัด (รุ่นแรก):
- เก็บในหน่วยความจำ รีสตาร์ทแล้วต้องผูกใหม่ งานจริงควรย้ายไปที่เก็บที่เข้ารหัส (เช่น Redis + KMS)
- ถ้าผู้ใช้ล็อกอินระบบ host ใหม่ (token เปลี่ยน) owner จะเปลี่ยน ต้องผูกใหม่
- อนาคต: แทนด้วย SSO / OAuth2 token exchange เมื่อระบบรอบข้างรองรับ (เปลี่ยนแค่ไฟล์นี้)
"""
import time
from dataclasses import dataclass

from app.config import LINK_TTL


@dataclass
class _Link:
    token: str
    last_used: float


_links: dict[tuple[str, str], _Link] = {}


def _purge() -> None:
    now = time.time()
    for k in [k for k, v in _links.items() if now - v.last_used > LINK_TTL]:
        del _links[k]


def put(owner: str, agent: str, token: str) -> None:
    _purge()
    _links[(owner, agent)] = _Link(token=token, last_used=time.time())


def get(owner: str, agent: str) -> str | None:
    _purge()
    link = _links.get((owner, agent))
    if link is None:
        return None
    link.last_used = time.time()
    return link.token


def remove(owner: str, agent: str) -> bool:
    return _links.pop((owner, agent), None) is not None


def linked(owner: str) -> set[str]:
    _purge()
    return {a for (o, a) in _links if o == owner}
