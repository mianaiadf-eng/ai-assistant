"""รูปแบบข้อมูลของ API"""
from pydantic import BaseModel


class PendingAction(BaseModel):
    """งานเขียนที่รอผู้ใช้กดยืนยัน (summary สร้างจากโค้ด ไม่ใช่โมเดล)"""
    id: str
    tool: str
    summary: str
    risk: str                 # write | destructive
    agent: str = ""           # sub agent เจ้าของงาน
    expires_in: int = 300     # วินาที


class AgentInfo(BaseModel):
    name: str
    title: str
    linked: bool = True       # มี token ใช้งานระบบนี้แล้วหรือยัง
    can_login: bool = False   # ผูกบัญชีผ่าน widget ได้ไหม


class ChatRequest(BaseModel):
    tenant_id: str
    user_token: str
    message: str
    session_id: str | None = None
    # True = ให้ไคลเอนต์เรียก API ระบบที่ฝัง widget เอง คำตอบอาจเป็น {"turn_id","call"}
    client_exec: bool = False


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    agent: str | None = None          # sub agent ที่ตอบ
    agent_title: str | None = None
    pending_action: PendingAction | None = None
    link_required: AgentInfo | None = None   # ต้องผูกบัญชีระบบนี้ก่อน


class LinkRequest(BaseModel):
    """ผูกบัญชีระบบหนึ่งเข้ากับผู้ใช้ (auth กลาง)"""
    tenant_id: str
    user_token: str
    agent: str
    username: str
    password: str


class UserRef(BaseModel):
    tenant_id: str
    user_token: str


class UnlinkRequest(UserRef):
    agent: str


class ConfirmRequest(BaseModel):
    tenant_id: str
    user_token: str
    action_id: str
    client_exec: bool = False


class TurnResult(BaseModel):
    """ผลการเรียก API ที่ไคลเอนต์ทำแทน ส่งกลับมาให้งานที่พักไว้ทำต่อ"""
    tenant_id: str
    user_token: str
    call_id: str
    status: int
    body: object = None


class ConfirmResponse(BaseModel):
    message: str
    agent: str | None = None


class TurnCall(BaseModel):
    """งานยังไม่เสร็จ: ให้ไคลเอนต์เรียก API ตาม call แล้วส่งผลที่ POST /turn/{turn_id}"""
    turn_id: str
    call: dict
