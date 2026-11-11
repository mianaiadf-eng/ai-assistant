"""ทะเบียน tool: เพิ่มความสามารถใหม่ = เพิ่ม Tool หนึ่งรายการท้ายไฟล์ ไม่ต้องแก้ assistant.py

risk:
  read        ทำทันที
  write       ต้องให้ผู้ใช้กดยืนยันก่อน (ป๊อปอัป)
  destructive ต้องยืนยัน (ใช้กับงานลบ/ย้อนกลับยาก ยังไม่มี tool ชนิดนี้)
"""
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from app.adapters.base import Adapter, normalize_dt
from app.core.thai import TYPE_TH, thai_date, thai_datetime


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    risk: str
    run: Callable[[Adapter, dict, dict], Awaitable[str]]
    summarize: Callable[[dict], str] | None = None


def _parse_date(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if len(value) <= 10 and end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return normalize_dt(dt)


# ---------------------------------------------------------------- get_exams

async def _get_exams(adapter: Adapter, args: dict, collected: dict) -> str:
    exams = await adapter.get_exams(
        date_from=_parse_date(args.get("date_from")),
        date_to=_parse_date(args.get("date_to"), end_of_day=True),
        exam_type=args.get("exam_type"),
    )
    items = []
    for ex in exams:
        collected[ex.id] = ex
        d = ex.model_dump(mode="json")
        if ex.starts_at:
            d["date_th"] = thai_date(ex.starts_at)
            d["time"] = normalize_dt(ex.starts_at).strftime("%H:%M")
        if ex.exam_type:
            d["type_th"] = TYPE_TH.get(ex.exam_type, ex.exam_type)
        items.append(d)
    return json.dumps({"count": len(items), "exams": items}, ensure_ascii=False)


# -------------------------------------------------------------- create_card

def _summarize_create_card(args: dict) -> str:
    text = f"สร้างการ์ด “{args['name']}” ในลิสต์ “{args['list_name']}”"
    due = _parse_date(args.get("due_date"))
    if due:
        text += f" กำหนดวันที่ {thai_datetime(due)}"
    if args.get("description"):
        text += f" รายละเอียด: {args['description']}"
    return text


async def _create_card(adapter: Adapter, args: dict, collected: dict) -> str:
    result = await adapter.create_card(
        list_name=args["list_name"],
        name=args["name"],
        due_date=_parse_date(args.get("due_date")),
        description=args.get("description"),
    )
    return f"สร้างการ์ด “{result['name']}” ในลิสต์ “{result['list']}” เรียบร้อยแล้ว"


# ------------------------------------------------------------------ ทะเบียน

_TOOL_LIST: list[Tool] = [
    Tool(
        name="get_exams",
        description=(
            "ดึงตารางสอบจากระบบ ใช้ทุกครั้งที่ผู้ใช้ถามเรื่องการสอบ "
            "ระบุช่วงวันที่ได้ ถ้าไม่ระบุจะได้ทั้งหมด"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "วันเริ่มต้น YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "วันสิ้นสุด YYYY-MM-DD (รวมทั้งวัน)"},
                "exam_type": {
                    "type": "string",
                    "enum": ["midterm", "final", "makeup"],
                    "description": "midterm=กลางภาค, final=ปลายภาค, makeup=สอบซ่อม",
                },
            },
        },
        risk="read",
        run=_get_exams,
    ),
    Tool(
        name="create_card",
        description=(
            "สร้างการ์ด/งานใหม่ในลิสต์ที่ระบุ ใช้เมื่อผู้ใช้ขอให้สร้างหรือเพิ่มการ์ด "
            "ระบบจะให้ผู้ใช้กดยืนยันก่อนสร้างจริง"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "list_name": {"type": "string", "description": "ชื่อลิสต์ที่จะสร้างการ์ดใน"},
                "name": {"type": "string", "description": "ชื่อการ์ด"},
                "due_date": {
                    "type": "string",
                    "description": "กำหนดวัน/เวลา รูปแบบ YYYY-MM-DDTHH:MM (ถ้าไม่ระบุเวลาใช้ YYYY-MM-DD)",
                },
                "description": {"type": "string", "description": "รายละเอียดการ์ด"},
            },
            "required": ["list_name", "name"],
        },
        risk="write",
        run=_create_card,
        summarize=_summarize_create_card,
    ),
]

REGISTRY: dict[str, Tool] = {t.name: t for t in _TOOL_LIST}

# รูปแบบที่ส่งให้โมเดล
TOOLS = [
    {"name": t.name, "description": t.description, "input_schema": t.input_schema}
    for t in _TOOL_LIST
]