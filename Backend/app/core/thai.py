"""ตัวช่วยแสดงวันที่ภาษาไทย (พ.ศ.)"""
from datetime import datetime

from app.adapters.base import normalize_dt

THAI_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
               "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
TYPE_TH = {"midterm": "กลางภาค", "final": "ปลายภาค", "makeup": "สอบซ่อม"}


def thai_date(dt: datetime) -> str:
    dt = normalize_dt(dt)
    return f"{THAI_DAYS[dt.weekday()]} {dt.day} {THAI_MONTHS[dt.month - 1]} {dt.year + 543}"


def thai_datetime(dt: datetime) -> str:
    dt = normalize_dt(dt)
    return f"{thai_date(dt)} เวลา {dt.strftime('%H:%M')}"