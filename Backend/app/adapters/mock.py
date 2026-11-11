"""Adapter จำลอง: คืนตารางสอบตัวอย่าง ใช้ทดสอบโดยไม่ต้องมี Planka"""
from datetime import datetime, timedelta

from app.adapters.base import Adapter, TZ, normalize_dt
from app.schemas import Exam


class MockAdapter(Adapter):
    async def get_exams(self, date_from=None, date_to=None, exam_type=None):
        today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        if date_from:
            date_from = normalize_dt(date_from)
        if date_to:
            date_to = normalize_dt(date_to)

        # (id, วิชา, อีกกี่วันจากวันนี้, ชั่วโมง, นาที, ห้อง, ประเภท, หมายเหตุ)
        samples = [
            ("1", "คณิตศาสตร์วิศวกรรม 1", 1, 9, 0, "อาคาร 5 ห้อง 501", "midterm", "09:00-12:00 อนุญาตเครื่องคิดเลข"),
            ("2", "ฟิสิกส์ 1", 3, 13, 0, "อาคาร 2 ห้อง 204", "midterm", "13:00-16:00"),
            ("3", "การเขียนโปรแกรมเบื้องต้น", 6, 9, 0, "ห้องปฏิบัติการคอม 3", "midterm", "09:00-11:00 สอบปฏิบัติ"),
            ("4", "ภาษาอังกฤษเพื่อการสื่อสาร", 20, 13, 0, "อาคาร 1 ห้อง 105", "final", "13:00-15:00"),
        ]

        exams = []
        for eid, course, offset, hh, mm, room, etype, notes in samples:
            starts = (today + timedelta(days=offset)).replace(hour=hh, minute=mm)
            if date_from and starts < date_from:
                continue
            if date_to and starts > date_to:
                continue
            if exam_type and etype != exam_type:
                continue
            exams.append(Exam(
                id=eid, course=course, starts_at=starts,
                room=room, exam_type=etype, notes=notes,
            ))
        return exams