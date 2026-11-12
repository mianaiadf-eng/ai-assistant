"""สร้างข้อมูลตารางสอบตัวอย่างใน Planka (สำหรับทดสอบในเครื่องเท่านั้น)

รัน (จากโฟลเดอร์ Backend):
    .venv\\Scripts\\python scripts\\seed_planka.py [base_url] [username] [password]
ค่าเริ่มต้น: http://localhost:3000 demo demo

สิ่งที่สร้าง: โปรเจกต์ "มหาวิทยาลัยทดสอบ" > บอร์ด "ตารางสอบ"
  ลิสต์ "สอบกลางภาค", "สอบปลายภาค", "งานที่ต้องทำ"
  label "กลางภาค", "ปลายภาค"
  การ์ด = วิชา, due date = เวลาสอบ, description มีบรรทัด "ห้อง: ..."
ถ้ามีโปรเจกต์ชื่อนี้อยู่แล้วจะไม่สร้างซ้ำ

ผู้ใช้ที่ login ครั้งแรกต้องยอมรับข้อตกลง (terms) ก่อน สคริปต์นี้ยอมรับให้อัตโนมัติ
"""
import sys
from datetime import datetime, timedelta, timezone

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
USER = sys.argv[2] if len(sys.argv) > 2 else "demo"
PASS = sys.argv[3] if len(sys.argv) > 3 else "demo"
PROJECT_NAME = "มหาวิทยาลัยทดสอบ"
BKK = timezone(timedelta(hours=7))


def login(c: httpx.Client) -> str:
    r = c.post("/api/access-tokens", json={"emailOrUsername": USER, "password": PASS})
    if r.status_code == 403 and r.json().get("step") == "accept-terms":
        pending = r.json()["pendingToken"]
        sig = c.get("/api/terms").json()["item"]["signature"]
        r = c.post("/api/access-tokens/accept-terms",
                   json={"pendingToken": pending, "signature": sig})
        print("ยอมรับข้อตกลง (terms) ให้ผู้ใช้", USER)
    r.raise_for_status()
    return r.json()["item"]


def main():
    with httpx.Client(base_url=BASE, timeout=30) as c:
        token = login(c)
        c.headers["Authorization"] = f"Bearer {token}"

        projects = c.get("/api/projects").json()
        if any(p["name"] == PROJECT_NAME for p in projects.get("items", [])):
            print(f"มีโปรเจกต์ “{PROJECT_NAME}” อยู่แล้ว ข้าม")
            return

        def post(path, body):
            r = c.post(path, json=body)
            if r.status_code >= 400:
                raise SystemExit(f"POST {path} -> {r.status_code}: {r.text[:300]}")
            return r.json()["item"]

        project = post("/api/projects", {"type": "shared", "name": PROJECT_NAME})
        board = post(f"/api/projects/{project['id']}/boards",
                     {"name": "ตารางสอบ", "position": 65536})
        lists = {}
        for i, name in enumerate(["สอบกลางภาค", "สอบปลายภาค", "งานที่ต้องทำ"], 1):
            lists[name] = post(f"/api/boards/{board['id']}/lists",
                               {"type": "active", "name": name, "position": 65536 * i})
        labels = {
            "กลางภาค": post(f"/api/boards/{board['id']}/labels",
                            {"name": "กลางภาค", "color": "morning-sky", "position": 65536}),
            "ปลายภาค": post(f"/api/boards/{board['id']}/labels",
                            {"name": "ปลายภาค", "color": "autumn-leafs", "position": 131072}),
        }

        today = datetime.now(BKK).replace(hour=0, minute=0, second=0, microsecond=0)
        # (ลิสต์, label, วิชา, อีกกี่วัน, ชั่วโมง, ห้อง, หมายเหตุ)
        samples = [
            ("สอบกลางภาค", "กลางภาค", "ฐานข้อมูล", 2, 9, "อาคาร 4 ห้อง 401", "09:00-12:00"),
            ("สอบกลางภาค", "กลางภาค", "โครงสร้างข้อมูล", 4, 13, "อาคาร 3 ห้อง 302", "13:00-16:00"),
            ("สอบกลางภาค", "กลางภาค", "สถิติเบื้องต้น", 7, 9, "อาคาร 1 ห้อง 110", "อนุญาตเครื่องคิดเลข"),
            ("สอบปลายภาค", "ปลายภาค", "ระบบปฏิบัติการ", 30, 9, "อาคาร 4 ห้อง 402", "09:00-12:00"),
        ]
        for pos, (lname, label, course, days, hour, room, note) in enumerate(samples, 1):
            due = (today + timedelta(days=days)).replace(hour=hour).astimezone(timezone.utc)
            card = post(f"/api/lists/{lists[lname]['id']}/cards", {
                "type": "project",
                "name": course,
                "position": 65536 * pos,
                "dueDate": due.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "description": f"ห้อง: {room}\n{note}",
            })
            post(f"/api/cards/{card['id']}/card-labels", {"labelId": labels[label]["id"]})
            print("สร้างการ์ด", course)

        print(f"เสร็จ: เปิดดูที่ {BASE}")


if __name__ == "__main__":
    main()
