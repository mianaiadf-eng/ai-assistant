"""Sub agent: ผู้ช่วยเฉพาะของระบบรอบข้าง 1 ระบบ (1:1)

แต่ละระบบมีเงื่อนไขต่างกัน เราจึงเขียน sub agent เองทีละระบบ ในโฟลเดอร์ agents/<ชื่อ>/
ภายใน sub agent ประกอบจากความสามารถ 3 แบบ (ใช้แบบใดก็ได้ หรือผสมกัน):

1. skill.md        ความรู้ (symmetric function) ใส่ใน prompt: โครงสร้างข้อมูล ศัพท์ ขั้นตอนที่ควรทำ
2. functions       native function: โค้ด Python ตายตัว เหมาะกับ API ที่คงที่/ต้องแปลงข้อมูลเยอะ
3. openapi         เอกสาร OpenAPI ให้ AI เรียนรู้ action เอง ถ้ามีมาก จะค้นผ่าน search_actions
                   แทนการส่งรายการทั้งหมด (ประหยัด token)

กฎความปลอดภัยทั้งหมด (ยืนยันก่อนเขียน/ลบ, ห้ามเดา id ฯลฯ) อยู่ที่แกนกลาง sub agent ไม่ต้องเขียนเอง
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from app.config import BASE_DIR, HTTP_TIMEOUT
from app.errors import NotSupported, UpstreamError
from app.schemas import PendingAction
from app.services import bridge

log = logging.getLogger("assistant")

RISK_LEVELS = ("read", "write", "destructive")


@dataclass
class NativeFunction:
    """ฟังก์ชันที่เขียนด้วยโค้ด
    run(ctx, args) คืน str หรือข้อมูลที่แปลงเป็น JSON ได้
    risk = write/destructive: ไม่ถูกเรียกระหว่างแชต จะถูกเรียกหลังผู้ใช้กดยืนยันเท่านั้น
    summarize(args): ข้อความในกล่องยืนยัน (สร้างจากโค้ด ห้ามใช้ข้อความจากโมเดล)"""
    name: str
    description: str
    input_schema: dict
    run: Callable[["AgentCtx", dict], Awaitable[Any]]
    risk: str = "read"
    summarize: Callable[[dict], str] | None = None

    def __post_init__(self):
        if self.risk not in RISK_LEVELS:
            raise ValueError(f"risk ไม่ถูกต้อง: {self.name} -> {self.risk}")


@dataclass
class OpenAPI:
    """แหล่ง action จากเอกสาร OpenAPI 3 (JSON)
    spec: ชื่อไฟล์ในโฟลเดอร์ของ agent หรือ URL
    policy: blocked_tags / blocked / risk / labels / defaults (ดู app/openapi/spec.py)
    search_threshold: ถ้าจำนวน action มากกว่านี้ จะไม่ใส่รายการทั้งหมดใน prompt ให้โมเดลค้นด้วย search_actions"""
    spec: str
    policy: dict = field(default_factory=dict)
    search_threshold: int = 40


class SubAgent:
    def __init__(
        self,
        name: str,
        title: str,
        description: str,
        *,
        keywords: tuple[str, ...] | list[str] = (),
        base_url: str = "",
        auth: dict | None = None,
        login: dict | Callable[["SubAgent", str, str], Awaitable[str]] | None = None,
        functions: list[NativeFunction] | tuple = (),
        openapi: OpenAPI | None = None,
        requires_auth: bool | None = None,
        max_rounds: int = 8,
    ):
        self.name = name
        self.title = title
        # ใช้โดย agent หลักตอนเลือกว่าข้อความนี้เป็นงานของระบบไหน
        self.description = description
        self.keywords = tuple(keywords)
        self.base_url = base_url.rstrip("/")
        self.auth = auth or {"type": "bearer"}
        self.login_cfg = login
        self.functions: dict[str, NativeFunction] = {f.name: f for f in functions}
        self.openapi = openapi
        # ต้องมี token ของระบบนี้ก่อนใช้งาน (ค่าเริ่มต้น: มี openapi หรือมีวิธีล็อกอิน)
        self.requires_auth = (bool(openapi or login) if requires_auth is None else requires_auth)
        self.max_rounds = max_rounds
        self.folder: Path = BASE_DIR      # registry ตั้งค่าให้
        self.skill: str = ""              # เนื้อหา skill.md (registry โหลดให้)
        self.transport: httpx.AsyncBaseTransport | None = None  # ใส่ transport จำลองในเทสต์
        self._catalog = None
        self._spec: dict | None = None

    def __repr__(self) -> str:
        return f"SubAgent({self.name!r})"

    # ------------------------------------------------------------ openapi
    def load_spec(self, spec: dict) -> None:
        """ใส่ spec ตรง ๆ (ใช้ในเทสต์ หรือเมื่อ agent สร้าง spec เอง)"""
        self._spec = spec
        self._catalog = None

    @property
    def catalog(self):
        """แคตตาล็อก action จาก OpenAPI (None ถ้า agent นี้ไม่ใช้ openapi)"""
        if self.openapi is None:
            return None
        if self._catalog is None:
            from app.openapi.catalog import Catalog
            spec = self._spec if self._spec is not None else _load_spec(self.folder, self.openapi.spec)
            self._catalog = Catalog(spec, self.openapi.policy, self.openapi.search_threshold)
            log.info("CATALOG agent=%s actions=%d", self.name, len(self._catalog.actions))
        return self._catalog

    # ------------------------------------------------------------ เรียก API ระบบ (ฝั่งเซิร์ฟเวอร์)
    def headers(self, token: str) -> dict:
        if not token:
            return {}
        if self.auth.get("type") == "header":
            return {self.auth.get("name", "X-Api-Key"): token}
        return {"Authorization": f"Bearer {token}"}

    async def request(self, method: str, path: str, query: dict | None, body,
                      body_format: str, token: str) -> tuple[int, object]:
        if not self.base_url:
            raise UpstreamError(f"ยังไม่ได้ตั้งค่า base_url ของ {self.title}")
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, transport=self.transport) as client:
                r = await client.request(method, f"{self.base_url}{path}", params=query or None,
                                         headers=self.headers(token),
                                         **_body_kwargs(body_format, body))
        except httpx.HTTPError as e:
            raise UpstreamError(f"เชื่อมต่อ {self.title} ไม่ได้ ({type(e).__name__})") from e
        log.info("API[%s] %s %s -> %s", self.name, method, path, r.status_code)
        try:
            data = r.json() if r.content else {}
        except ValueError:
            data = {"text": r.text[:500]}
        return r.status_code, data

    async def login(self, username: str, password: str) -> str:
        """ล็อกอินระบบนี้ด้วยบัญชีของผู้ใช้ คืน token (ใช้ตอนผูกบัญชีกับ auth กลาง)"""
        if self.login_cfg is None:
            raise NotSupported(f"{self.title} ไม่รองรับการล็อกอินผ่านผู้ช่วย")
        if callable(self.login_cfg):
            return await self.login_cfg(self, username, password)
        cfg = self.login_cfg
        body = {k: v.replace("{username}", username).replace("{password}", password)
                if isinstance(v, str) else v
                for k, v in cfg.get("body", {}).items()}
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, transport=self.transport) as client:
                r = await client.post(f"{self.base_url}{cfg['path']}", json=body)
        except httpx.HTTPError as e:
            raise UpstreamError(f"เชื่อมต่อ {self.title} ไม่ได้ ({type(e).__name__})") from e
        if r.status_code >= 400:
            step = ""
            try:
                step = r.json().get("step") or ""
            except ValueError:
                pass
            if step:
                raise UpstreamError(f"ต้องทำขั้นตอน “{step}” ในหน้าเว็บของ {self.title} ก่อน แล้วค่อยล็อกอินใหม่")
            raise UpstreamError("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
        token = r.json().get(cfg.get("token_field", "token"))
        if not token:
            raise UpstreamError(f"ไม่ได้รับ token จาก {self.title}")
        return token


@dataclass
class AgentCtx:
    """บริบทของงานหนึ่งครั้งใน sub agent: ใครสั่ง ใช้ token อะไร และเรียก API ผ่านทางไหน"""
    agent: SubAgent
    tenant_id: str
    owner: str
    token: str = ""
    user_msg: str = ""
    # True = ระบบนี้คือระบบที่ฝัง widget อยู่ ให้หน้าเว็บเรียก API แทน (ใช้ cookie/session ของผู้ใช้)
    via_browser: bool = False
    pending: PendingAction | None = None

    async def http(self, method: str, path: str, query: dict | None = None, body=None,
                   body_format: str = "json") -> tuple[int, object]:
        """เรียก API ของระบบนี้ path เทียบกับ base_url ของ agent เช่น /api/boards/1"""
        b = bridge.current() if self.via_browser else None
        if b is not None:
            status, data = await b.http(method, path, query or {}, body, body_format)
            log.info("API(browser)[%s] %s %s -> %s", self.agent.name, method, path, status)
            return status, data
        return await self.agent.request(method, path, query, body, body_format, self.token)

    async def emit(self, text: str) -> None:
        """แสดงสถานะที่หน้าเว็บแบบเรียลไทม์ (ผ่าน WebSocket hub)"""
        await bridge.emit(self.owner, {"type": "status", "agent": self.agent.name, "text": text})


# ---------------------------------------------------------------- ตัวช่วย

def form_value(v) -> str:
    """ค่าในฟอร์มต้องเป็นข้อความ: bool -> true/false, object -> JSON"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _body_kwargs(fmt: str, body) -> dict:
    if body is None:
        return {}
    if fmt == "multipart":
        # (None, value) = ช่องข้อความใน multipart ไม่ใช่ไฟล์ (httpx ต้องมี files จึงส่งแบบ multipart)
        return {"files": {k: (None, form_value(v)) for k, v in body.items()}}
    if fmt == "form":
        return {"data": {k: form_value(v) for k, v in body.items()}}
    return {"json": body}


def _load_spec(folder: Path, source: str) -> dict:
    if source.startswith(("http://", "https://")):
        r = httpx.get(source, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json()
    with open(folder / source, encoding="utf-8") as f:
        return json.load(f)
