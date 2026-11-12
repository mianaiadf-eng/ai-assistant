"""แคตตาล็อก action จาก OpenAPI ของระบบหนึ่ง (ใช้โดย sub agent ที่มี openapi)
ไม่ผูกกับระบบใด และไม่รู้ว่าเรียก API ทางไหน (เบราว์เซอร์หรือเซิร์ฟเวอร์ ให้ AgentCtx ตัดสิน)"""
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote

from app.core.thai import TZ, normalize_dt, thai_datetime
from app.errors import UpstreamError
from app.openapi.search import ActionIndex
from app.openapi.spec import Action, build_actions, server_base_path

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
    def __init__(self, spec: dict, policy: dict | None = None, search_threshold: int = 40):
        self.base_path = server_base_path(spec)
        self.actions: dict[str, Action] = build_actions(spec, policy)
        self.title = spec.get("info", {}).get("title", "")
        self.index = ActionIndex(self.actions)
        # action มากเกิน: ไม่ใส่รายการทั้งหมดใน prompt ให้โมเดลค้นผ่าน search_actions แทน
        self.use_search = len(self.actions) > search_threshold
        # GET ที่ path เดียวกัน ใช้ดึงชื่อสิ่งที่จะถูกแก้/ลบ มาแสดงในข้อความยืนยัน
        self._getter_by_path = {a.path: a for a in self.actions.values() if a.method == "GET"}
        # รูปทรง path ไม่สนชื่อ placeholder เช่น /lists/{} ใช้หาชื่อรายการแม่
        self._getter_by_shape = {_PLACEHOLDER.sub("{}", p): a for p, a in self._getter_by_path.items()}

    # ------------------------------------------------------------ สำหรับโมเดล

    @staticmethod
    def line(a: Action) -> str:
        return f"- {a.id} [{a.risk}] {a.method} {a.path}: {a.label or a.summary}"

    def index_text(self) -> str:
        """รายการ action ทั้งหมด (ใช้เมื่อมีไม่มาก)"""
        return "\n".join(self.line(a) for a in
                         sorted(self.actions.values(), key=lambda a: (a.tags[:1], a.id)))

    def overview_text(self) -> str:
        """ภาพรวมสำหรับแคตตาล็อกใหญ่: หมวด + จุดเริ่มต้น (read ที่ไม่ต้องรู้ id ใด)"""
        tags: dict[str, int] = {}
        for a in self.actions.values():
            for t in a.tags[:1] or ["อื่น ๆ"]:
                tags[t] = tags.get(t, 0) + 1
        starts = [a for a in self.actions.values()
                  if a.risk == "read" and "{" not in a.path]
        lines = [f"มี action ทั้งหมด {len(self.actions)} รายการ แบ่งตามหมวด: "
                 + ", ".join(f"{t} ({n})" for t, n in sorted(tags.items()))]
        if starts:
            lines.append("จุดเริ่มต้น (อ่านได้โดยไม่ต้องรู้ id):")
            lines += [self.line(a) for a in sorted(starts, key=lambda a: a.id)]
        return "\n".join(lines)

    def search(self, query: str, limit: int = 8) -> list[dict]:
        return [{
            "action_id": a.id, "risk": a.risk, "method": a.method, "path": a.path,
            "summary": a.label or a.summary,
            # ชื่อพารามิเตอร์ (* = จำเป็น) ช่วยให้โมเดลไม่ต้องเรียก describe ถ้าไม่จำเป็น
            "params": [p.name + ("*" if p.required else "") for p in a.params],
        } for a in self.index.search(query, limit)]

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

    def request_parts(self, action: Action, args: dict):
        """คืน (path เทียบกับ base_url, query, body)"""
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
            raise UpstreamError(f"ขาดพารามิเตอร์ใน URL ของ {action.id}")
        has_body = action.method in ("POST", "PUT", "PATCH") or any(
            p.location == "body" for p in action.params)
        return f"{self.base_path}{path}", query, (body if has_body else None)

    async def call(self, action: Action, args: dict, ctx) -> tuple[int, object]:
        path, query, body = self.request_parts(action, args)
        return await ctx.http(action.method, path, query, body, action.body_format)

    async def target_name(self, action: Action, args: dict, ctx) -> str | None:
        """ดึงชื่อของสิ่งที่ action จะแก้/ลบ เช่น ชื่อการ์ด (ถ้ามี GET ที่ path เดียวกัน)"""
        if action.method == "POST":
            return None  # POST มักสร้างของใหม่ใน collection (GET path เดียวกันคือรายการ ไม่ใช่ตัวเป้าหมาย)
        getter = self._getter_by_path.get(action.path)
        if getter is None or "{" not in action.path or getter is action:
            return None
        path_args = {p.name: args.get(p.name) for p in getter.params if p.location == "path"}
        return await self._name_via(getter, path_args, ctx)

    async def container_name(self, action: Action, args: dict, ctx) -> str | None:
        """ชื่อของรายการแม่ เช่น POST /lists/{listId}/cards -> ชื่อลิสต์ (จาก GET /lists/{id})"""
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
            return await self._name_via(getter, dict(zip(names, values)), ctx)
        return None

    async def _name_via(self, getter: Action, path_args: dict, ctx) -> str | None:
        if not path_args or any(v in (None, "") for v in path_args.values()):
            return None
        status, data = await self.call(getter, path_args, ctx)
        if status == 404:
            raise UpstreamError("ไม่พบรายการที่ระบุ (id ไม่ถูกต้องหรือถูกลบไปแล้ว)")
        if status >= 400 or not isinstance(data, dict):
            return None
        item = data.get("item", data)
        if isinstance(item, dict):
            for k in _NAME_KEYS:
                if isinstance(item.get(k), str) and item[k].strip():
                    return item[k].strip()
        return None
