"""sub agent ตัวอย่าง: ระบบทะเบียนจำลอง — ใช้ความสามารถแบบ native function + skill.md

เป็นต้นแบบสำหรับระบบที่ไม่มี OpenAPI หรือมี API คงที่ที่อยากเขียนโค้ดเอง
- get_exams            [read]  อ่านตารางสอบ (ข้อมูลจำลอง)
- request_makeup_exam  [write] ยื่นคำร้องขอสอบซ่อม (ต้องยืนยันก่อน ทำจริงหลังกดยืนยันเท่านั้น)
- login: รับทุกชื่อผู้ใช้/รหัสผ่าน (ใช้ทดสอบการผูกบัญชีกับ auth กลาง)

ระบบจริง: ใน run() ให้เรียก await ctx.http("GET", "/api/...") ซึ่งใช้ token ของผู้ใช้ให้เอง
"""
import secrets
from datetime import datetime, timedelta

from app.core.thai import TZ, normalize_dt, thai_date
from app.errors import UpstreamError
from app.subagent.base import AgentCtx, NativeFunction, SubAgent

TYPE_TH = {"midterm": "กลางภาค", "final": "ปลายภาค", "makeup": "สอบซ่อม"}

# (id, วิชา, อีกกี่วันจากวันนี้, ชั่วโมง, นาที, ห้อง, ประเภท, หมายเหตุ)
_SAMPLES = [
    ("1", "คณิตศาสตร์วิศวกรรม 1", 1, 9, 0, "อาคาร 5 ห้อง 501", "midterm", "09:00-12:00 อนุญาตเครื่องคิดเลข"),
    ("2", "ฟิสิกส์ 1", 3, 13, 0, "อาคาร 2 ห้อง 204", "midterm", "13:00-16:00"),
    ("3", "การเขียนโปรแกรมเบื้องต้น", 6, 9, 0, "ห้องปฏิบัติการคอม 3", "midterm", "09:00-11:00 สอบปฏิบัติ"),
    ("4", "ภาษาอังกฤษเพื่อการสื่อสาร", 20, 13, 0, "อาคาร 1 ห้อง 105", "final", "13:00-15:00"),
]

# คำร้องที่ยื่นแล้ว (จำลอง: เก็บในหน่วยความจำ)
REQUESTS: list[dict] = []


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


async def get_exams(ctx: AgentCtx, args: dict):
    date_from = _parse_date(args.get("date_from"))
    date_to = _parse_date(args.get("date_to"), end_of_day=True)
    exam_type = args.get("exam_type")
    today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    items = []
    for eid, course, offset, hh, mm, room, etype, notes in _SAMPLES:
        starts = (today + timedelta(days=offset)).replace(hour=hh, minute=mm)
        if (date_from and starts < date_from) or (date_to and starts > date_to):
            continue
        if exam_type and etype != exam_type:
            continue
        items.append({"course": course, "date_th": thai_date(starts), "time": starts.strftime("%H:%M"),
                      "room": room, "type_th": TYPE_TH[etype], "notes": notes})
    return {"count": len(items), "exams": items}


async def request_makeup_exam(ctx: AgentCtx, args: dict) -> str:
    """เรียกหลังผู้ใช้กดยืนยันเท่านั้น"""
    ref = "MU-" + secrets.token_hex(3).upper()
    REQUESTS.append({"ref": ref, "course": args["course"], "reason": args["reason"],
                     "at": datetime.now(TZ).isoformat()})
    return f"ยื่นคำร้องขอสอบซ่อมวิชา “{args['course']}” เรียบร้อยแล้ว เลขที่คำร้อง {ref}"


def _summarize_makeup(args: dict) -> str:
    return f"ยื่นคำร้องขอสอบซ่อมวิชา “{args['course']}” เหตุผล: {args['reason']}"


async def _login(agent: SubAgent, username: str, password: str) -> str:
    if not username or not password:
        raise UpstreamError("กรุณากรอกชื่อผู้ใช้และรหัสผ่าน")
    return "demo-" + secrets.token_urlsafe(8)


AGENT = SubAgent(
    name="exams_demo",
    title="ระบบทะเบียน (จำลอง)",
    description="ระบบทะเบียนนักศึกษา: ตารางสอบกลางภาค/ปลายภาคของนักศึกษา และยื่นคำร้องขอสอบซ่อม",
    keywords=["ทะเบียน", "สอบซ่อม", "คำร้อง", "ตารางสอบของฉัน", "สอบกลางภาค", "สอบปลายภาค"],
    login=_login,
    functions=[
        NativeFunction(
            name="get_exams",
            description="ดึงตารางสอบของนักศึกษา ระบุช่วงวันที่ได้ ถ้าไม่ระบุจะได้ทั้งหมด",
            input_schema={
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": "วันเริ่มต้น YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "วันสิ้นสุด YYYY-MM-DD (รวมทั้งวัน)"},
                    "exam_type": {"type": "string", "enum": ["midterm", "final", "makeup"],
                                  "description": "midterm=กลางภาค, final=ปลายภาค, makeup=สอบซ่อม"},
                },
            },
            run=get_exams,
        ),
        NativeFunction(
            name="request_makeup_exam",
            description="ยื่นคำร้องขอสอบซ่อม ต้องรู้ชื่อวิชาและเหตุผล ระบบจะให้ผู้ใช้กดยืนยันก่อนยื่นจริง",
            input_schema={
                "type": "object",
                "properties": {
                    "course": {"type": "string", "description": "ชื่อวิชาตามตารางสอบ"},
                    "reason": {"type": "string", "description": "เหตุผลที่ขอสอบซ่อม"},
                },
                "required": ["course", "reason"],
            },
            risk="write",
            run=request_makeup_exam,
            summarize=_summarize_makeup,
        ),
    ],
)
