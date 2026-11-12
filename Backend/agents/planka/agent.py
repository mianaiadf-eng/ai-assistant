"""sub agent ของ Planka (บอร์ดคัมบัง) — ใช้ความสามารถแบบ openapi + skill.md

base_url เปลี่ยนได้ใน .env: AGENT_PLANKA_BASE_URL=https://planka.example.com
สร้าง openapi.json ใหม่เมื่อ Planka เปลี่ยนเวอร์ชัน: ดู .claude/skills/ai-assistant/SKILL.md
"""
from app.subagent.base import OpenAPI, SubAgent

AGENT = SubAgent(
    name="planka",
    title="Planka (บอร์ดงาน)",
    description="บอร์ดคัมบัง (Planka): โปรเจกต์ บอร์ด ลิสต์ การ์ด งานย่อย ป้ายกำกับ ความคิดเห็น "
                "รวมถึงข้อมูลที่ผู้ใช้จัดเก็บเป็นการ์ด เช่น บอร์ดตารางสอบ",
    keywords=["planka", "บอร์ด", "การ์ด", "ลิสต์", "โปรเจกต์", "คัมบัง", "งานย่อย", "ป้ายกำกับ"],
    base_url="http://localhost:1337",
    auth={"type": "bearer"},
    login={
        "path": "/api/access-tokens",
        "body": {"emailOrUsername": "{username}", "password": "{password}"},
        "token_field": "item",
    },
    openapi=OpenAPI(
        spec="openapi.json",
        search_threshold=40,
        policy={
            # หมวดที่ AI ไม่ควรแตะ: ผู้ใช้/สิทธิ์, token, webhook, ตั้งค่าระบบ
            "blocked_tags": [
                "Access Tokens", "Users", "Webhooks", "Config", "Notification Services",
                "Terms", "Bootstrap", "Background Images",
            ],
            # ช่องที่ Planka บังคับแต่ spec ไม่ได้บอก (ไม่แสดงในกล่องยืนยัน)
            "defaults": {
                "createCard": {"type": "project", "position": 65536},
                "createList": {"type": "active", "position": 65536},
                "createLabel": {"position": 65536},
                "createTask": {"position": 65536},
                "createTaskList": {"position": 65536},
                "createBoard": {"position": 65536},
            },
            # ไม่ใช่ DELETE แต่ย้อนกลับยาก
            "risk": {"clearList": "destructive", "sortList": "write", "moveListCards": "write"},
            "labels": {
                "createProject": "สร้างโปรเจกต์", "updateProject": "แก้ไขโปรเจกต์",
                "deleteProject": "ลบโปรเจกต์", "updateBoard": "แก้ไขบอร์ด", "deleteBoard": "ลบบอร์ด",
                "createList": "สร้างลิสต์", "updateList": "แก้ไขลิสต์", "deleteList": "ลบลิสต์",
                "clearList": "ล้างการ์ดทั้งหมดในลิสต์", "createCard": "สร้างการ์ด",
                "updateCard": "แก้ไขการ์ด", "deleteCard": "ลบการ์ด", "duplicateCard": "ทำสำเนาการ์ด",
                "createComment": "เพิ่มความคิดเห็น", "deleteComment": "ลบความคิดเห็น",
                "createLabel": "สร้างป้ายกำกับ", "deleteLabel": "ลบป้ายกำกับ",
                "createCardLabel": "ติดป้ายกำกับให้การ์ด", "deleteCardLabel": "เอาป้ายกำกับออกจากการ์ด",
                "createTask": "เพิ่มงานย่อย", "updateTask": "แก้ไขงานย่อย", "deleteTask": "ลบงานย่อย",
                "createBoard": "สร้างบอร์ด",
            },
        },
    ),
)
