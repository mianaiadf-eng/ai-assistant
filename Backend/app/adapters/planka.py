"""Adapter ของ Planka
สมมติโครงสร้างการ์ด: ชื่อการ์ด = วิชา, due date = เวลาสอบ,
label = ประเภทสอบ, description มีบรรทัด "ห้อง: xxx"

หมายเหตุ: API ของ Planka ไม่มีเอกสารทางการครบ ชื่อ field อาจต่างตามเวอร์ชัน
ให้ทดสอบกับเวอร์ชันที่ติดตั้งจริง แล้วปรับตรงนี้ที่เดียว"""
import re
from datetime import datetime

import httpx

from app.adapters.base import Adapter, AdapterError, normalize_dt
from app.schemas import Exam

ROOM_RE = re.compile(r"(?:ห้อง|room)\s*[:：]\s*(.+)", re.IGNORECASE)

TYPE_MAP = {
    "กลางภาค": "midterm",
    "midterm": "midterm",
    "ปลายภาค": "final",
    "final": "final",
    "สอบซ่อม": "makeup",
}


class PlankaAdapter(Adapter):
    def _headers(self) -> dict:
        # v1/JWT ใช้ Bearer, v2 ที่ใช้ API key ใช้ X-API-Key (ส่งทั้งคู่ไม่เสียหาย)
        return {
            "Authorization": f"Bearer {self.user_token}",
            "X-API-Key": self.user_token,
        }

    async def _get(self, client: httpx.AsyncClient, path: str) -> dict:
        try:
            r = await client.get(f"{self.base_url}{path}", headers=self._headers())
        except httpx.HTTPError as e:
            raise AdapterError(f"เชื่อมต่อ Planka ไม่ได้ ({type(e).__name__})") from e
        if r.status_code in (401, 403):
            raise AdapterError("token ไม่ถูกต้องหรือไม่มีสิทธิ์เข้าถึง Planka")
        if r.status_code >= 400:
            raise AdapterError(f"Planka ตอบกลับด้วยรหัส {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise AdapterError("Planka ตอบกลับข้อมูลที่อ่านไม่ได้") from e

    @staticmethod
    def _parse_due(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return normalize_dt(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None

    async def get_exams(self, date_from=None, date_to=None, exam_type=None):
        if date_from:
            date_from = normalize_dt(date_from)
        if date_to:
            date_to = normalize_dt(date_to)

        exams: list[Exam] = []
        async with httpx.AsyncClient(timeout=15) as client:
            projects = await self._get(client, "/api/projects")
            boards = projects.get("included", {}).get("boards", [])

            seen_boards = set()
            for board in boards:
                bid = board.get("id")
                if not bid or bid in seen_boards:
                    continue
                seen_boards.add(bid)

                data = await self._get(client, f"/api/boards/{bid}")
                inc = data.get("included", {})
                labels = {l["id"]: l.get("name", "") for l in inc.get("labels", [])}

                card_label_ids: dict[str, list[str]] = {}
                for cl in inc.get("cardLabels", []):
                    card_label_ids.setdefault(cl["cardId"], []).append(cl["labelId"])

                for card in inc.get("cards", []):
                    starts = self._parse_due(card.get("dueDate"))
                    if starts is None:
                        continue  # การ์ดที่ไม่มีวันสอบ ข้าม
                    if date_from and starts < date_from:
                        continue
                    if date_to and starts > date_to:
                        continue

                    names = [labels.get(i, "") for i in card_label_ids.get(card["id"], [])]
                    etype = None
                    for n in names:
                        etype = TYPE_MAP.get(n.strip().lower()) or TYPE_MAP.get(n.strip())
                        if etype:
                            break
                    if etype is None and names:
                        etype = names[0]
                    if exam_type and etype != exam_type:
                        continue

                    desc = card.get("description") or ""
                    m = ROOM_RE.search(desc)
                    room = m.group(1).strip() if m else None

                    exams.append(Exam(
                        id=str(card["id"]),
                        course=card.get("name", "(ไม่มีชื่อ)"),
                        starts_at=starts,
                        room=room,
                        exam_type=etype,
                        notes=desc.strip()[:300] or None,
                    ))

        exams.sort(key=lambda e: e.starts_at)
        return exams