"""อ่าน OpenAPI 3 แล้วแปลงเป็นรายการ Action

ระดับความเสี่ยงกำหนดด้วยโค้ดจาก HTTP method (โมเดลเปลี่ยนไม่ได้):
  GET -> read, POST/PUT/PATCH -> write, DELETE -> destructive
tenant ปรับได้ผ่าน policy: risk (รายตัว), blocked / blocked_tags (ซ่อนและเรียกไม่ได้), labels (ชื่อไทย),
defaults (ค่าที่ใส่ให้เองเมื่อโมเดลไม่ส่ง สำหรับ spec ที่ไม่ตรงกับพฤติกรรมจริง)
"""
from dataclasses import dataclass, field
from urllib.parse import urlparse

METHOD_RISK = {
    "get": "read",
    "post": "write",
    "put": "write",
    "patch": "write",
    "delete": "destructive",
}
RISK_LEVELS = ("read", "write", "destructive")
_FORM_TYPES = ("multipart/form-data", "application/x-www-form-urlencoded")


def _is_file(schema: dict) -> bool:
    s = schema.get("items", schema) if schema.get("type") == "array" else schema
    return s.get("format") in ("binary", "base64") or s.get("type") == "file"

# คีย์ใน schema ที่ไม่ช่วยโมเดลตัดสินใจ ตัดทิ้งเพื่อประหยัด token
_DROP_SCHEMA_KEYS = {"example", "examples", "readOnly", "writeOnly", "xml", "externalDocs", "deprecated"}
_MAX_SCHEMA_DEPTH = 4


@dataclass
class Param:
    name: str
    location: str          # path | query | body
    required: bool
    schema: dict


@dataclass
class Action:
    id: str                # operationId
    method: str            # GET / POST / ...
    path: str              # /cards/{id} (ยังไม่รวม base path ของ server)
    summary: str
    description: str
    tags: list[str]
    risk: str
    label: str | None = None           # ชื่อภาษาไทยที่แอดมินตั้ง ใช้ในข้อความยืนยัน
    params: list[Param] = field(default_factory=list)
    defaults: dict = field(default_factory=dict)  # ค่าที่ใส่ให้เองถ้าโมเดลไม่ส่ง (แก้ spec ที่ไม่ตรงของจริง)
    body_format: str = "json"                     # json | multipart | form (urlencoded)

    @property
    def required(self) -> list[str]:
        return [p.name for p in self.params if p.required]

    def input_schema(self) -> dict:
        """schema รวมของ path/query/body เป็น object เดียว ให้โมเดลเห็น"""
        props = {}
        for p in self.params:
            s = dict(p.schema)
            if p.location == "path":
                s["description"] = (s.get("description", "") + " (ส่วนหนึ่งของ URL)").strip()
            props[p.name] = s
        out = {"type": "object", "properties": props}
        if self.required:
            out["required"] = self.required
        return out


def _resolve(spec: dict, node, depth: int = 0, seen: frozenset = frozenset()):
    """แทนที่ $ref ด้วยเนื้อหาจริง และรวม allOf แบบง่าย"""
    if depth > 30:
        return {}
    if isinstance(node, list):
        return [_resolve(spec, n, depth + 1, seen) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        ref = node["$ref"]
        if ref in seen or not ref.startswith("#/"):
            return {}
        target = spec
        for part in ref[2:].split("/"):
            target = target.get(part, {}) if isinstance(target, dict) else {}
        return _resolve(spec, target, depth + 1, seen | {ref})
    out = {k: _resolve(spec, v, depth + 1, seen) for k, v in node.items()}
    if "allOf" in out:
        merged: dict = {"type": "object", "properties": {}, "required": []}
        for part in out.pop("allOf"):
            merged["properties"].update(part.get("properties", {}))
            merged["required"] += part.get("required", [])
        merged["properties"].update(out.pop("properties", {}))
        merged.update({k: v for k, v in out.items() if k not in ("type", "required")})
        if not merged["required"]:
            merged.pop("required")
        out = merged
    return out


def _slim(schema, depth: int = 0):
    """ตัดคีย์ที่ไม่จำเป็น และจำกัดความลึกของ schema"""
    if isinstance(schema, list):
        return [_slim(s, depth) for s in schema]
    if not isinstance(schema, dict):
        return schema
    if depth >= _MAX_SCHEMA_DEPTH:
        keep = {k: schema[k] for k in ("type", "description") if k in schema}
        return keep or {"type": "object"}
    out = {}
    for k, v in schema.items():
        if k in _DROP_SCHEMA_KEYS:
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _slim(pv, depth + 1) for pk, pv in v.items()}
        elif k in ("items", "additionalProperties") and isinstance(v, dict):
            out[k] = _slim(v, depth + 1)
        elif k in ("oneOf", "anyOf") and isinstance(v, list):
            out[k] = [_slim(x, depth + 1) for x in v]
        else:
            out[k] = v
    return out


def build_actions(spec: dict, policy: dict | None = None) -> dict[str, Action]:
    policy = policy or {}
    risk_override: dict = policy.get("risk", {})
    blocked = set(policy.get("blocked", []))
    blocked_tags = set(policy.get("blocked_tags", []))
    labels: dict = policy.get("labels", {})
    defaults: dict = policy.get("defaults", {})

    actions: dict[str, Action] = {}
    for path, item in spec.get("paths", {}).items():
        item = _resolve(spec, item)
        shared_params = item.get("parameters", [])
        for method, op in item.items():
            if method not in METHOD_RISK or not isinstance(op, dict):
                continue
            op_id = op.get("operationId") or f"{method}_{path}"
            tags = op.get("tags") or []
            if op_id in blocked or blocked_tags.intersection(tags):
                continue

            params: list[Param] = []
            for p in shared_params + op.get("parameters", []):
                if p.get("in") not in ("path", "query"):
                    continue  # header/cookie ระบบจัดการเอง
                params.append(Param(
                    name=p["name"], location=p["in"],
                    required=bool(p.get("required")) or p["in"] == "path",
                    schema=_slim({**p.get("schema", {}),
                                  **({"description": p["description"]} if p.get("description") else {})}),
                ))

            body = op.get("requestBody")
            body_format = "json"
            if body:
                content = body.get("content", {})
                if "application/json" in content:
                    bschema = content["application/json"].get("schema", {})
                else:
                    # รองรับ form โดยตัดช่องไฟล์ออก (แนบไฟล์ผ่านแชตไม่ได้)
                    # ถ้าบังคับต้องมีไฟล์ เช่นอัปโหลดไฟล์แนบ ให้ข้าม action นี้
                    form = next((t for t in _FORM_TYPES if t in content), None)
                    if form is None:
                        continue
                    bschema = content[form].get("schema", {})
                    props = bschema.get("properties", {})
                    files = {n for n, s in props.items() if _is_file(s)}
                    if files & set(bschema.get("required", [])) or (files and len(files) == len(props)):
                        continue
                    bschema = {**bschema, "properties": {n: s for n, s in props.items() if n not in files}}
                    body_format = "multipart" if form == "multipart/form-data" else "form"
                body_required = set(bschema.get("required", []))
                names = {p.name for p in params}
                for name, s in bschema.get("properties", {}).items():
                    if name in names:
                        continue  # ชื่อชนกับ path/query ให้ path/query ชนะ
                    params.append(Param(
                        name=name, location="body",
                        required=name in body_required and bool(body.get("required", True)),
                        schema=_slim(s),
                    ))

            risk = risk_override.get(op_id, METHOD_RISK[method])
            if risk not in RISK_LEVELS:
                raise ValueError(f"ระดับความเสี่ยงไม่ถูกต้องสำหรับ {op_id}: {risk}")
            actions[op_id] = Action(
                id=op_id, method=method.upper(), path=path,
                summary=(op.get("summary") or "").strip(),
                description=(op.get("description") or "").strip(),
                tags=tags, risk=risk, label=labels.get(op_id), params=params,
                defaults=defaults.get(op_id, {}), body_format=body_format,
            )
    return actions


def server_base_path(spec: dict) -> str:
    """เช่น servers: [{url: "/api"}] -> "/api" (รองรับเฉพาะ path แบบ relative)"""
    servers = spec.get("servers") or []
    url = (servers[0].get("url") if servers else "") or ""
    return urlparse(url).path.rstrip("/")
