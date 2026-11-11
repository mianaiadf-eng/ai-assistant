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


class PendingAction(BaseModel):
    """งานเขียนที่รอผู้ใช้กดยืนยัน (summary สร้างจากโค้ด ไม่ใช่โมเดล)"""
    id: str
    tool: str
    summary: str
    risk: str                 # write | destructive
    expires_in: int = 300     # วินาที


class ChatRequest(BaseModel):
    tenant_id: str
    user_token: str
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    exams: list[Exam] = []
    pending_action: PendingAction | None = None


class LoginRequest(BaseModel):
    tenant_id: str
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str


class ConfirmRequest(BaseModel):
    tenant_id: str
    user_token: str
    action_id: str


class ConfirmResponse(BaseModel):
    message: str