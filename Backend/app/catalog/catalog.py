"""แคตตาล็อก action ของแต่ละ tenant + ตัวเรียก API ระบบหลักแบบทั่วไป (ไม่ผูกกับระบบใด)

ตั้งค่าใน tenants.json เช่น
  "planka-api": {
    "base_url": "http://localhost:1337",
    "openapi": "specs/planka.json",            # path ในเครื่อง (เทียบกับโฟลเดอร์ Backend) หรือ URL
    "auth": {"type": "bearer"},                # หรือ {"type": "header", "name": "X-Api-Key"}
    "login": {"path": "/api/access-tokens",
              "body": {"emailOrUsername": "{username}", "password": "{password}"},
              "token_field": "item"},
    "policy": {"blocked_tags": [...], "blocked": [...], "risk": {...}, "labels": {...}}
  }
"""
import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from app.adapters.base import TZ, AdapterError, NotSupported, normalize_dt
from app.catalog.spec import Action, build_actions, server_base_path
from app.config import BASE_DIR, HTTP_TIMEOUT, TENANTS
from app.core.thai import thai_datetime
from app.services.turns import active_bridge

log = logging.getLogger("assistant")

MAX_RESULT_CHARS = 10000
_NAME_KEYS = ("name", "title", "username", "email", "text")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]00:?00)$")


def _local_time(value: str) -> str:
    """'2026-11-13T02:00:00.000Z' -> '2026-11-13T09:00+07:00 (ศุกร์ 13 พ.ย. 2569 เวลา 09:00)'"""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TZ)
    return f"{dt.strftime('%Y-%m-%dT%H:%M%z')[:-2]}:{dt.strftime('%z')[-2:]} ({thai_datetime(dt)})"


def to_utc(value: str) -> str:
    """เวลาที่โมเดลส่งมา: ไม่มีเขตเวลา = เวลาท้องถิ่น แปลงเป็น UTC ตามรูปแบบที่ API ส่วนใหญ่รับ"""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value  # ให้ระบบหลักตอบ error เอง
    return normalize_dt(dt).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


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


def _compact(value):
    """ตัดค่าว่างทิ้ง และแปลงเวลา UTC เป็นเวลาท้องถิ่น ก่อนส่งให้โมเดล"""
    if isinstance(value, dict):
        out = {k: _compact(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_compact(v) for v in value]
    if isinstance(value, str) and _UTC_RE.match(value):
        try:
            return _local_time(value)
        except ValueError:
            return value
    return value


def result_text(data) -> str:
    text = json.dumps(_compact(data), ensure_ascii=False, separators=(",", ":"))
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + " …(ตัดทอน ผลลัพธ์ยาวเกิน ให้ใช้ action ที่เจาะจงกว่านี้)"
    return text


class Catalog:
    def __init__(self, tenant_id: str, cfg: dict, spec: dict):
        self.tenant_id = tenant_id
        self.base_url = cfg["base_url"].rstrip("/")
        self.base_path = server_base_path(spec)
        self.auth = cfg.get("auth", {"type": "bearer"})
        self.login_cfg = cfg.get("login")
        self.actions: dict[str, Action] = build_actions(spec, cfg.get("policy"))
        self.title = cfg.get("title") or spec.get("info", {}).get("title", tenant_id)
        # ความรู้ที่เอกสาร API ไม่มี เช่น "การ์ดในบอร์ดตารางสอบคือการสอบ" (แอดมินเขียน)
        self.notes: str = cfg.get("notes", "")
        self.transport: httpx.AsyncBaseTransport | None = None  # ใช้ใส่ transport จำลองในเทสต์
        # GET ที่ path เดียวกัน ใช้ดึงชื่อสิ่งที่จะถูกแก้/ลบ มาแสดงในข้อความยืนยัน
        self._getter_by_path = {a.path: a for a in self.actions.values() if a.method == "GET"}
        # รูปทรง path ไม่สนชื่อ placeholder เช่น /lists/{} ใช้หาชื่อรายการแม่
        self._getter_by_shape = {_PLACEHOLDER.sub("{}", p): a for p, a in self._getter_by_path.items()}

    # ------------------------------------------------------------ สำหรับโมเดล

    def index_text(self) -> str:
        lines = []
        for a in sorted(self.actions.values(), key=lambda a: (a.tags[:1], a.id)):
            lines.append(f"- {a.id} [{a.risk}] {a.method} {a.path}: {a.summary}")
        return "\n".join(lines)

    def describe(self, action_id: str) -> dict:
        a = self.actions[action_id]
        return {
            "action_id": a.id,
            "summary": a.summary,
            "description": a.description,
            "risk": a.risk,
            "args_schema": a.input_schema(),
        }

    def validate(self, action: Action, args: dict) -> list[str]:
        errors = []
        known = {p.name: p for p in action.params}
        for k in args:
            if k not in known:
                errors.append(f"ไม่มีพารามิเตอร์ชื่อ {k}")
        for p in action.params:
            v = args.get(p.name, action.defaults.get(p.name))
            if p.required and v in (None, ""):
                errors.append(f"ขาดพารามิเตอร์ที่จำเป็น {p.name}")
            enum = p.schema.get("enum")
            if v is not None and enum and v not in enum:
                errors.append(f"{p.name} ต้องเป็นค่าใดค่าหนึ่งใน {enum}")
        return errors

    # ------------------------------------------------------------ เรียก API

    def _headers(self, user_token: str) -> dict:
        if self.auth.get("type") == "header":
            return {self.auth.get("name", "X-Api-Key"): user_token}
        return {"Authorization": f"Bearer {user_token}"}

    def _request_parts(self, action: Action, args: dict):
        args = {**action.defaults, **args}  # ค่าเริ่มต้นจาก policy (ช่องที่ spec บอกไม่ครบ)
        path = action.path
        query, body = {}, {}
        for p in action.params:
            if p.name not in args or args[p.name] is None:
                continue
            v = args[p.name]
            if p.schema.get("format") == "date-time" and isinstance(v, str):
                v = to_utc(v)
            if p.location == "path":
                # quote แบบ safe="" กันการแทรก ../ หรือ / เพื่อเปลี่ยน endpoint
                path = path.replace("{" + p.name + "}", quote(str(v), safe=""))
            elif p.location == "query":
                query[p.name] = v
            else:
                body[p.name] = v
        if "{" in path:
            raise AdapterError(f"ขาดพารามิเตอร์ใน URL ของ {action.id}")
        has_body = action.method in ("POST", "PUT", "PATCH") or any(
            p.location == "body" for p in action.params)
        return f"{self.base_url}{self.base_path}{path}", query, (body if has_body else None)

    async def call(self, action: Action, args: dict, user_token: str) -> tuple[int, object]:
        url, query, body = self._request_parts(action, args)

        bridge = active_bridge()
        if bridge is not None:
            # ให้ widget เรียกจากหน้าเว็บของระบบหลัก (ใช้ cookie/session ของผู้ใช้ที่เซิร์ฟเวอร์เข้าไม่ถึง)
            status, data = await bridge.http(action.method, url[len(self.base_url):], query, body,
                                             action.body_format)
            log.info("API(browser) %s %s -> %s", action.method, action.path, status)
            return status, data

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, transport=self.transport) as client:
                r = await client.request(action.method, url, params=query,
                                         headers=self._headers(user_token),
                                         **_body_kwargs(action.body_format, body))
        except httpx.HTTPError as e:
            raise AdapterError(f"เชื่อมต่อระบบหลักไม่ได้ ({type(e).__name__})") from e
        log.info("API %s %s -> %s", action.method, action.path, r.status_code)
        try:
            data = r.json() if r.content else {}
        except ValueError:
            data = {"text": r.text[:500]}
        return r.status_code, data

    async def target_name(self, action: Action, args: dict, user_token: str) -> str | None:
        """ดึงชื่อของสิ่งที่ action จะแก้/ลบ เช่น ชื่อการ์ด (ถ้ามี GET ที่ path เดียวกัน)"""
        if action.method == "POST":
            return None  # POST มักสร้างของใหม่ใน collection (GET path เดียวกันคือรายการ ไม่ใช่ตัวเป้าหมาย)
        getter = self._getter_by_path.get(action.path)
        if getter is None or "{" not in action.path or getter is action:
            return None
        path_args = {p.name: args.get(p.name) for p in getter.params if p.location == "path"}
        return await self._name_via(getter, path_args, user_token)

    async def container_name(self, action: Action, args: dict, user_token: str) -> str | None:
        """ชื่อของรายการแม่ เช่น POST /lists/{listId}/cards -> ชื่อลิสต์ (จาก GET /lists/{id})
        ใช้แสดงในป๊อปอัปว่าจะสร้าง/ทำในที่ไหน"""
        segs = action.path.split("/")
        for end in range(len(segs) - 1, 1, -1):
            if not _PLACEHOLDER.fullmatch(segs[end - 1]):
                continue
            prefix = "/".join(segs[:end])
            getter = self._getter_by_shape.get(_PLACEHOLDER.sub("{}", prefix))
            if getter is None:
                continue
            values = [args.get(n) for n in _PLACEHOLDER.findall(prefix)]
            names = _PLACEHOLDER.findall(getter.path)
            return await self._name_via(getter, dict(zip(names, values)), user_token)
        return None

    async def _name_via(self, getter: Action, path_args: dict, user_token: str) -> str | None:
        if not path_args or any(v in (None, "") for v in path_args.values()):
            return None
        status, data = await self.call(getter, path_args, user_token)
        if status == 404:
            raise AdapterError("ไม่พบรายการที่ระบุ (id ไม่ถูกต้องหรือถูกลบไปแล้ว)")
        if status >= 400 or not isinstance(data, dict):
            return None
        item = data.get("item", data)
        if isinstance(item, dict):
            for k in _NAME_KEYS:
                if isinstance(item.get(k), str) and item[k].strip():
                    return item[k].strip()
        return None

    async def login(self, username: str, password: str) -> str:
        if not self.login_cfg:
            raise NotSupported("ระบบนี้ไม่ได้ตั้งค่าการล็อกอินผ่านผู้ช่วย")
        body = {k: v.replace("{username}", username).replace("{password}", password)
                if isinstance(v, str) else v
                for k, v in self.login_cfg.get("body", {}).items()}
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, transport=self.transport) as client:
                r = await client.post(f"{self.base_url}{self.login_cfg['path']}", json=body)
        except httpx.HTTPError as e:
            raise AdapterError(f"เชื่อมต่อระบบหลักไม่ได้ ({type(e).__name__})") from e
        if r.status_code >= 400:
            step = ""
            try:
                step = r.json().get("step") or ""
            except ValueError:
                pass
            if step:
                raise AdapterError(f"ต้องทำขั้นตอน “{step}” ในหน้าเว็บของระบบหลักก่อน แล้วค่อยล็อกอินใหม่")
            raise AdapterError("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
        token = r.json().get(self.login_cfg.get("token_field", "token"))
        if not token:
            raise AdapterError("ไม่ได้รับ token จากระบบหลัก")
        return token


# ---------------------------------------------------------------- ทะเบียน

_cache: dict[str, Catalog] = {}


def is_catalog_tenant(tenant_id: str) -> bool:
    return bool(TENANTS.get(tenant_id, {}).get("openapi"))


def _load_spec(source: str) -> dict:
    if source.startswith(("http://", "https://")):
        r = httpx.get(source, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json()
    with open(BASE_DIR / source, encoding="utf-8") as f:
        return json.load(f)


def get_catalog(tenant_id: str) -> Catalog:
    if tenant_id in _cache:
        return _cache[tenant_id]
    cfg = TENANTS.get(tenant_id)
    if not cfg:
        raise KeyError(f"ไม่รู้จัก tenant: {tenant_id}")
    if not cfg.get("openapi"):
        raise KeyError(f"tenant {tenant_id} ไม่ได้ตั้งค่า openapi")
    catalog = Catalog(tenant_id, cfg, _load_spec(cfg["openapi"]))
    log.info("CATALOG tenant=%s actions=%d", tenant_id, len(catalog.actions))
    _cache[tenant_id] = catalog
    return catalog
