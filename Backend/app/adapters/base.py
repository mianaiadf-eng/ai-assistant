"""สัญญา (interface) ที่ทุก adapter ต้องทำตาม
ระบบใหม่ = เขียนคลาสใหม่ 1 ตัว AI Core ไม่ต้องแก้"""
from abc import ABC, abstractmethod
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import TIMEZONE
from app.schemas import Exam

TZ = ZoneInfo(TIMEZONE)


class NotSupported(Exception):
    """ระบบนี้ไม่รองรับฟังก์ชันที่ขอ"""


class AdapterError(Exception):
    """ติดต่อหรืออ่านข้อมูลจากระบบหลักไม่สำเร็จ (ข้อความต้องอ่านเข้าใจได้)"""


def normalize_dt(dt: datetime) -> datetime:
    """ทำให้ทุกเวลามีเขตเวลา เพื่อเทียบกันได้ไม่ error"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


class Adapter(ABC):
    def __init__(self, base_url: str, user_token: str):
        self.base_url = base_url.rstrip("/")
        self.user_token = user_token

    @abstractmethod
    async def get_exams(
        self,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        exam_type: str | None = None,
    ) -> list[Exam]:
        ...

    # ฟังก์ชันอื่นเพิ่มได้ทีหลัง ระบบไหนไม่รองรับให้ raise NotSupported
    async def get_assignments(self, *args, **kwargs):
        raise NotSupported("ระบบนี้ยังไม่รองรับ")