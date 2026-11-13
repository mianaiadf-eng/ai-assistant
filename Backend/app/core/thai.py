"""เขตเวลา และตัวช่วยแสดงวันที่ภาษาไทย (พ.ศ.)"""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import TIMEZONE

TZ = ZoneInfo(TIMEZONE)

THAI_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
               "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


def normalize_dt(dt: datetime) -> datetime:
    """ทำให้ทุกเวลามีเขตเวลา เพื่อเทียบกันได้ไม่ error"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def thai_date(dt: datetime) -> str:
    dt = normalize_dt(dt)
    return f"{THAI_DAYS[dt.weekday()]} {dt.day} {THAI_MONTHS[dt.month - 1]} {dt.year + 543}"


def thai_datetime(dt: datetime) -> str:
    dt = normalize_dt(dt)
    return f"{thai_date(dt)} เวลา {dt.strftime('%H:%M')}"


def now_line() -> str:
    now = datetime.now(TZ)
    return (f"เวลาปัจจุบัน: วัน{THAI_DAYS[now.weekday()]}ที่ {now.strftime('%Y-%m-%d')} "
            f"เวลา {now.strftime('%H:%M')} (เขตเวลา {TZ.key})")
