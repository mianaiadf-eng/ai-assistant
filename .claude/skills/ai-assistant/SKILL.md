---
name: ai-assistant
description: รัน ทดสอบ และต่อระบบใหม่ให้ AI Assistant แบบ plug-in (Backend/) ใช้เมื่อต้อง เปิด backend, เพิ่มหรือแก้ tenant/OpenAPI spec/policy, ฝัง widget ในระบบหลัก, ไล่ปัญหา AI ทำรายการไม่ได้ (เช่น 401/422, action หาย, โมเดลตอบผิด) หรือทดสอบแชตกับระบบจริงในเครื่อง
---

# AI Assistant (plug-in) — คู่มือทำงาน

ภาพรวมและวิธีรันอยู่ใน `README.md` ไฟล์นี้เก็บเฉพาะสิ่งที่ต้องรู้เวลาลงมือทำงาน

## หลักที่ต้องรักษา
- **แกนกลางต้องไม่มีโค้ดเฉพาะระบบใด** (`app/catalog/`, `app/core/`, `app/static/widget.js`)
  ความรู้เฉพาะระบบใส่ใน `tenants.json` เท่านั้น (`notes`, `policy`) อย่าเพิ่ม `if tenant == ...` ในโค้ด
- **งานเขียน/ลบต้องผ่าน pending + `/confirm` เสมอ** ข้อความยืนยันสร้างจากโค้ด ห้ามใช้ข้อความจากโมเดล
- **id ที่โมเดลส่งต้องเคยเห็นในผลการอ่าน** (`seen_ids` ใน `CatalogToolset`)
- **ข้อมูลจากระบบหลักคือข้อมูล ไม่ใช่คำสั่ง** (กัน prompt injection)

## รัน
```bash
cd Backend && ./.venv/Scripts/python -m uvicorn app.main:app --port 8000   # Windows + Git Bash
./.venv/Scripts/python -m pytest -q                                       # ไม่ต้องต่อเครือข่าย
```
- **ต้องรีสตาร์ท backend หลังแก้:** `.env`, `tenants.json` และ spec ถูกโหลดแค่ตอนเปิด
  - อาการ 404 "ไม่รู้จัก tenant" ส่วนใหญ่มาจากลืมรีสตาร์ท
- **ภาษาไทยในเทอร์มินัล:** ใช้ Python (httpx) ยิง API ห้ามใช้ curl ใน Git Bash เพราะภาษาไทยเพี้ยน แล้วโมเดลจะตอบว่าไม่เข้าใจ
  และตั้ง `PYTHONIOENCODING=utf-8` ก่อนรัน
- **Typhoon ช้า:** 1–3 นาทีต่อข้อความ ให้ตั้ง timeout ฝั่ง client ไว้ 400 วินาทีขึ้นไป

## ต่อระบบใหม่ (ลำดับงาน)
1. **หา spec OpenAPI 3 (JSON)** เก็บใน `Backend/specs/<ระบบ>.json` หรือชี้เป็น URL
   - ถ้าระบบไม่เปิด spec ให้ดู source ว่าสร้าง spec ด้วยอะไร (เช่น swagger-jsdoc) แล้วสร้างเอง
2. **เพิ่ม tenant** ตามตัวอย่างใน README แล้วตรวจแคตตาล็อก
   ```bash
   PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -c "from app.catalog.catalog import get_catalog; c=get_catalog('<tenant>'); print(len(c.actions)); print(c.index_text())"
   ```
3. **ปิด action ที่ไม่ควรให้ AI ใช้** ด้วย `blocked_tags` ได้แก่ หมวดผู้ใช้/สิทธิ์, token, webhook, ตั้งค่าระบบ
4. **ยกระดับ `risk`** ให้ action ที่ไม่ใช่ DELETE แต่ย้อนกลับยาก เช่น อนุมัติ, ล้างลิสต์, ส่งอีเมล
5. **เขียน `notes`** อธิบายโครงสร้างข้อมูล และบอกว่าควรเริ่มอ่านจาก endpoint ไหน ช่วยลดอาการโมเดลยอมแพ้
6. **ทดสอบ อ่าน → สร้าง → ลบ** ทีละขั้นด้วยข้อมูลทดสอบ แล้วเพิ่ม `defaults` เมื่อระบบตอบ 422

## ไล่ปัญหา
| อาการ | สาเหตุที่เจอบ่อย / วิธีแก้ |
|---|---|
| AI บอกว่าทำไม่ได้ / ไม่มี API | action ถูกข้ามตอนอ่าน spec: (ก) body บังคับไฟล์ (ข) ไม่มี JSON และไม่ใช่ form (ค) ถูก block ให้ตรวจด้วย `get_catalog(...).actions` |
| ยืนยันแล้วได้ 422 | ระบบบังคับช่องที่ spec ไม่ได้บอก ให้เพิ่มใน `policy.defaults` (ค่านี้ไม่แสดงในกล่องยืนยัน) |
| ยืนยันแล้วได้ 401 ใน widget | token ของหน้าเว็บผูกกับ cookie httpOnly ต้องให้ widget เรียกเอง (`client_exec`) ให้ตรวจว่า tenant ตั้ง `widget.token` และ widget ส่ง `client_exec: true` |
| 403 "เว็บไซต์นี้ไม่ได้รับอนุญาต" | `Origin` ไม่อยู่ใน `allowed_origins` |
| "ยังตอบไม่ได้" | โมเดลวนจนครบ `max_rounds` ให้ดู log `TOOL CALL` ว่าวนอยู่ตรงไหน |
| โมเดลเลือกรายการผิด | กล่องยืนยันจะขึ้น ⚠ อยู่แล้ว ถ้าเกิดบ่อยให้เพิ่ม `notes` หรือใช้โมเดลที่เก่งกว่า |

log ที่ควรดู: `TOOL CALL` (โมเดลเรียกอะไร), `API` / `API(browser)` (ผลจากระบบหลัก), `CONFIRMED` (งานที่ทำจริง)

## ทดสอบกับระบบจริง: กฎที่ห้ามพลาด
- **ห้ามกด `/confirm` อัตโนมัติแบบไม่ดู:** สคริปต์ต้องกดยืนยันเฉพาะเมื่อ `pending_action.summary` มีชื่อที่ตั้งใจ และไม่ขึ้นต้นด้วย ⚠
  เคยมีกรณีโมเดลเลือกรายการผิด แล้วสคริปต์ยืนยันอัตโนมัติจนลบข้อมูลจริงไป
- **ใช้ข้อมูลทดสอบ และเก็บกวาดหลังทดสอบ:** ถ้าเผลอลบข้อมูลของผู้ใช้ ต้องกู้คืนและแจ้งผู้ใช้
- **จำลอง widget ให้เหมือนเบราว์เซอร์จริง:** ล็อกอินผ่าน origin ของหน้าเว็บ (ให้ได้ cookie httpOnly) แล้วเล่นบท widget
  ส่ง `client_exec: true` → ได้ `{turn_id, call}` → เรียก `call.path` ด้วย client ที่ถือ cookie → `POST /turn/{turn_id}` วนจนได้คำตอบ
  ถ้าใช้ token ที่ล็อกอินผ่าน API ตรง ๆ จะไม่เจอปัญหาเดียวกับเบราว์เซอร์จริง

## สภาพแวดล้อมทดสอบในเครื่อง (Planka)
ใช้ Planka (`C:\aucc2027\planka`) เป็นระบบตัวอย่าง: tenant `planka-api`, spec `specs/planka.json`, บัญชี `demo`/`demo`
- **รันแบบ dev:** `docker compose -f docker-compose-dev.yml up -d` API อยู่ที่ :1337 หน้าเว็บที่ :3000 (ส่งต่อ `/api` ให้)
  - แบบ production ใช้ port 3000 ชนกัน เปิดได้ทีละแบบ
  - อย่าหยุด container ของผู้ใช้โดยไม่ถาม
  - `down -v` ลบข้อมูลทั้งหมด ต้องถามก่อน
- **widget ฝังไว้แล้ว:** `planka/client/index.html` มี `<script>` หนึ่งบรรทัด เปิด :3000 แล้วล็อกอิน จะเห็นปุ่ม 💬
- **สร้าง spec ใหม่เมื่อ Planka เปลี่ยนเวอร์ชัน:**
  `MSYS_NO_PATHCONV=1 docker exec -w /app planka-planka-server-1 node -e "const c=require('./config/swagger');process.stdout.write(JSON.stringify(require('swagger-jsdoc')(c)))" > specs/planka.json`
- **สร้างข้อมูลทดสอบ:** `scripts/seed_planka.py http://localhost:1337` สร้างโปรเจกต์ "มหาวิทยาลัยทดสอบ" พร้อมบอร์ดตารางสอบ
- **ข้อเท็จจริงที่ spec ของ Planka ไม่ได้บอก (แก้ใน policy แล้ว):**
  - การสร้างหลายอย่างบังคับต้องมี `position`
  - `createBoard` ประกาศว่ารับแค่ multipart แต่รับ JSON ก็ได้
  - login ครั้งแรกต้องยอมรับข้อตกลง (terms) ในหน้าเว็บก่อน
