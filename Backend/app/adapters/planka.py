"""Adapter ของ Planka
ชื่อการ์ด = วิชา, due date = เวลาสอบ, label = ประเภทสอบ, description มีบรรทัด "ห้อง: xxx"

หมายเหตุ: API ของ Planka ไม่มีเอกสารทางการครบ ชื่อ field อาจต่างตามเวอร์ชัน
ส่วน get_exams/login ทดสอบกับของจริงแล้ว ส่วน create_card ยังไม่ได้ทดสอบ"""
import re
from datetime import datetime, timezone

import httpx

from app.adapters.base import Adapter, AdapterError, normalize_dt
from app.config import HTTP_TIMEOUT
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
        return {
            "Authorization": f"Bearer {self.user_token}",
            "X-API-Key": self.user_token,
        }

    async def login(self, username: str, password: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                r = await client.post(
                    f"{self.base_url}/api/access-tokens",
                    json={"emailOrUsername": username, "password": password},
                )
        except httpx.HTTPError as e:
            raise AdapterError(f"เชื่อมต่อ Planka ไม่ได้ ({type(e).__name__})") from e
        if r.status_code in (400, 401, 403, 422):
            raise AdapterError("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
        if r.status_code >= 400:
            raise AdapterError(f"Planka ตอบกลับด้วยรหัส {r.status_code}")
        try:
            token = r.json().get("item")
        except ValueError as e:
            raise AdapterError("Planka ตอบกลับข้อมูลที่อ่านไม่ได้") from e
        if not token:
            raise AdapterError("ไม่ได้รับ token จาก Planka")
        return token

    async def _request(self, client: httpx.AsyncClient, method: str, path: str,
                       json: dict | None = None) -> dict:
        try:
            r = await client.request(
                method, f"{self.base_url}{path}", headers=self._headers(), json=json
            )
        except httpx.HTTPError as e:
            raise AdapterError(f"เชื่อมต่อ Planka ไม่ได้ ({type(e).__name__})") from e
        if r.status_code in (401, 403):
            raise AdapterError("token ไม่ถูกต้องหรือไม่มีสิทธิ์ทำรายการนี้ใน Planka")
        if r.status_code >= 400:
            raise AdapterError(f"Planka ตอบกลับด้วยรหัส {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise AdapterError("Planka ตอบกลับข้อมูลที่อ่านไม่ได้") from e

    async def _get(self, client: httpx.AsyncClient, path: str) -> dict:
        return await self._request(client, "GET", path)

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
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
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
                        continue
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

    async def _find_list(self, client: httpx.AsyncClient, list_name: str):
        """หาลิสต์จากชื่อ คืน (id, ชื่อจริง, position ท้ายสุด)"""
        target = list_name.strip().lower()
        projects = await self._get(client, "/api/projects")
        matches = []
        for board in projects.get("included", {}).get("boards", []):
            data = await self._get(client, f"/api/boards/{board['id']}")
            inc = data.get("included", {})
            for lst in inc.get("lists", []):
                if lst.get("type") != "active":
                    continue
                if (lst.get("name") or "").strip().lower() != target:
                    continue
                positions = [
                    c.get("position") or 0
                    for c in inc.get("cards", [])
                    if c.get("listId") == lst["id"]
                ]
                matches.append((lst["id"], lst["name"], max(positions, default=0)))
        if not matches:
            raise AdapterError(f"ไม่พบลิสต์ชื่อ “{list_name}”")
        if len(matches) > 1:
            raise AdapterError(f"มีลิสต์ชื่อ “{list_name}” มากกว่าหนึ่งรายการ ระบุให้ชัดเจนขึ้น")
        return matches[0]

    async def create_card(self, list_name, name, due_date=None, description=None):
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            list_id, real_name, last_pos = await self._find_list(client, list_name)

            body: dict = {"type": "project", "name": name, "position": last_pos + 65536}
            if description:
                body["description"] = description
            if due_date:
                utc = normalize_dt(due_date).astimezone(timezone.utc)
                body["dueDate"] = utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")

            data = await self._request(
                client, "POST", f"/api/lists/{list_id}/cards", json=body
            )
            card_id = (data.get("item") or {}).get("id")
            if not card_id:
                raise AdapterError("Planka ไม่ได้ส่งรหัสการ์ดกลับมา")

        return {"id": str(card_id), "name": name, "list": real_name}