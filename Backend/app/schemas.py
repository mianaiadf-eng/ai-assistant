"""รูปแบบข้อมูลกลาง: ทุก adapter ต้องแปลงข้อมูลของระบบตัวเองให้เป็นแบบนี้"""
from datetime import datetime
from pydantic import BaseModel


class Exam(BaseModel):
    id: str
    course: str
    starts_at: datetime | None = None
    room: str | None = None
    exam_type: str | None = None  # เช่น midterm / final
    notes: str | None = None


class ChatRequest(BaseModel):
    tenant_id: str            # มหาลัย/ระบบไหน
    user_token: str           # token ของผู้ใช้ในระบบหลัก
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str                # ข้อความตอบ (มีตารางมาร์กดาวน์ได้)
    exams: list[Exam] = []    # ข้อมูลโครงสร้าง ให้ frontend วาดตารางเองได้