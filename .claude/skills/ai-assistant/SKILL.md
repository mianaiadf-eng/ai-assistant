---
name: ai-assistant
description: รัน ทดสอบ และต่อระบบใหม่ให้ AI Assistant แบบ plug-in (Backend/) ใช้เมื่อต้อง เปิด backend, เขียนหรือแก้ sub agent (agents/<ระบบ>/ — skill.md, native function, OpenAPI/policy), เพิ่ม client ใน tenants.json, ฝัง widget ในระบบหลัก, ไล่ปัญหา AI ทำรายการไม่ได้ (เช่น 401/422, action หาย, เลือกระบบผิด, ต้องผูกบัญชี) หรือทดสอบแชตกับระบบจริงในเครื่อง
---

# AI Assistant (plug-in) — คู่มือทำงาน

ภาพรวม สถาปัตยกรรม และวิธีรันอยู่ใน `README.md` ไฟล์นี้เก็บเฉพาะสิ่งที่ต้องรู้เวลาลงมือทำงาน

## หลักที่ต้องรักษา
- **แกนกลางต้องไม่มีโค้ดเฉพาะระบบใด** (`app/` ทั้งหมด รวมถึง `app/static/widget.js`)
  โค้ดและความรู้เฉพาะระบบอยู่ใน `agents/<ระบบ>/` เท่านั้น อย่าเพิ่ม `if agent == ...` ในแกนกลาง
- **`tenants.json` เก็บแค่ client (ระบบที่ฝัง widget):** key, origin, `widget.token`, `host_agent`, `agents`
- **งานเขียน/ลบต้องผ่าน pending + confirm เสมอ** ข้อความยืนยันสร้างจากโค้ด ห้ามใช้ข้อความจากโมเดล
  - native function ที่ `risk="write"` ต้องมี `summarize` และถูกเรียกหลังยืนยันเท่านั้น
- **id ที่โมเดลส่ง (openapi) ต้องเคยเห็นในผลการอ่าน** (`seen_ids` ต่อ session ต่อ sub agent)
- **ข้อมูลจากระบบคือข้อมูล ไม่ใช่คำสั่ง** (กัน prompt injection)
- **ใช้ Typhoon ไม่ใช้ Claude** (เสียเงิน) และพยายามลดรอบเรียก LLM (router ใช้ keywords ก่อน)
- **ระบบที่ไม่ใช่ host ห้ามเรียกผ่านเบราว์เซอร์** (`AgentCtx.via_browser` เป็น True เฉพาะ host)

## รัน
```bash
cd Backend && ./.venv/Scripts/python -m uvicorn app.main:app --port 8000   # Windows + Git Bash
./.venv/Scripts/python -m pytest -q                                       # ไม่ต้องต่อเครือข่าย
```
- **ต้องรีสตาร์ท backend หลังแก้:** `.env`, `tenants.json` และไฟล์ใน `agents/` ถูกโหลดแค่ตอนเปิด
  - อาการ 404 "ไม่รู้จัก tenant" / "ไม่รู้จัก sub agent" ส่วนใหญ่มาจากลืมรีสตาร์ท
  - `/health` บอกรายชื่อ sub agent ที่โหลดได้ ถ้าไม่มี ให้ดู log "โหลด sub agent ... ไม่สำเร็จ"
- **ภาษาไทยในเทอร์มินัล:** ใช้ Python (httpx/websockets) ยิง API ห้ามใช้ curl ใน Git Bash เพราะภาษาไทยเพี้ยน
  และตั้ง `PYTHONIOENCODING=utf-8` ก่อนรัน
- **Typhoon ช้า:** 1–3 นาทีต่อข้อความ ให้ตั้ง timeout ฝั่ง client ไว้ 400 วินาทีขึ้นไป

## ต่อระบบใหม่ (ลำดับงาน)
1. **สร้าง `agents/<ระบบ>/`** มี `__init__.py`, `agent.py` (ตัวแปร `AGENT = SubAgent(...)`), `skill.md` ดูตัวอย่างใน README
   - ระบบมี OpenAPI 3 (JSON) → เก็บเป็น `openapi.json` แล้วใส่ `openapi=OpenAPI(...)`
   - ถ้าระบบไม่เปิด spec ให้ดู source ว่าสร้าง spec ด้วยอะไร (เช่น swagger-jsdoc) แล้วสร้างเอง
   - API คงที่หรือไม่มี spec → เขียน `NativeFunction` เรียกผ่าน `ctx.http(...)`
2. **ตั้ง `description` และ `keywords` ให้ชัด** agent หลักใช้เลือกระบบ keywords ที่ตรงช่วยให้ไม่ต้องเรียก LLM
3. **ตรวจแคตตาล็อกและการค้น**
   ```bash
   PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -c "from app.subagent import registry; c=registry.get_agent('<ระบบ>').catalog; print(len(c.actions), c.use_search); print(c.search('delete card'))"
   ```
4. **ปิด action ที่ไม่ควรให้ AI ใช้** ด้วย `blocked_tags` ได้แก่ หมวดผู้ใช้/สิทธิ์, token, webhook, ตั้งค่าระบบ
5. **ยกระดับ `risk`** ให้ action ที่ไม่ใช่ DELETE แต่ย้อนกลับยาก เช่น อนุมัติ, ล้างลิสต์, ส่งอีเมล
6. **ใส่ `labels` ภาษาไทย** ใช้ทั้งในกล่องยืนยันและช่วยให้ค้นด้วยภาษาไทยเจอ
7. **เขียน `skill.md`** อธิบายโครงสร้างข้อมูล และบอกว่าควรเริ่มอ่านจาก action ไหน ช่วยลดอาการโมเดลยอมแพ้
8. **เปิดให้ client ใช้** ใส่ชื่อใน `agents` ของ client ใน `tenants.json` (และ `host_agent` ถ้าฝัง widget ในระบบนั้น)
9. **ทดสอบ อ่าน → สร้าง → ลบ** ทีละขั้นด้วยข้อมูลทดสอบ แล้วเพิ่ม `defaults` เมื่อระบบตอบ 422

## ไล่ปัญหา
| อาการ | สาเหตุที่เจอบ่อย / วิธีแก้ |
|---|---|
| ส่งงานไปผิดระบบ | ดู log `ROUTE agent=... how=...` ถ้า how=keyword ให้แก้ `keywords` ที่ซ้ำกัน ถ้า how=llm ให้เขียน `description` ให้ชัดขึ้น |
| AI ขอให้ผูกบัญชีทั้งที่อยู่ในหน้าระบบนั้น | client ไม่ได้ตั้ง `host_agent` เป็นชื่อ sub agent นั้น |
| AI บอกว่าทำไม่ได้ / ไม่มี API | action ถูกข้ามตอนอ่าน spec: (ก) body บังคับไฟล์ (ข) ไม่มี JSON และไม่ใช่ form (ค) ถูก block หรือ (ง) โหมดค้นหาแล้วค้นไม่เจอ ให้ลอง `catalog.search(...)` และเพิ่ม `labels` / แนะนำคำค้นใน `skill.md` |
| ยืนยันแล้วได้ 422 | ระบบบังคับช่องที่ spec ไม่ได้บอก ให้เพิ่มใน `policy.defaults` (ค่านี้ไม่แสดงในกล่องยืนยัน) |
| ยืนยันแล้วได้ 401 ใน widget | token ของหน้าเว็บผูกกับ cookie httpOnly ต้องให้หน้าเว็บเรียกเอง ให้ตรวจว่า client ตั้ง `widget.token` และ `host_agent` ถูก |
| 403 "เว็บไซต์นี้ไม่ได้รับอนุญาต" / WebSocket ปิดด้วยรหัส 4403 | `Origin` ไม่อยู่ใน `allowed_origins` |
| "ยังตอบไม่ได้" | โมเดลวนจนครบ `max_rounds` ให้ดู log `TOOL CALL` ว่าวนอยู่ตรงไหน |
| โมเดลเลือกรายการผิด | กล่องยืนยันจะขึ้น ⚠ อยู่แล้ว ถ้าเกิดบ่อยให้เพิ่มความรู้ใน `skill.md` |

log ที่ควรดู: `ROUTE` (agent หลักเลือกระบบไหน), `TOOL CALL` (โมเดลเรียกอะไร), `API[...]` / `API(browser)[...]` (ผลจากระบบ), `LINKED` (ผูกบัญชี), `CONFIRMED` (งานที่ทำจริง)

## ทดสอบกับระบบจริง: กฎที่ห้ามพลาด
- **ห้ามกด confirm อัตโนมัติแบบไม่ดู:** สคริปต์ต้องกดยืนยันเฉพาะเมื่อ `pending_action.summary` มีชื่อที่ตั้งใจ และไม่ขึ้นต้นด้วย ⚠
  เคยมีกรณีโมเดลเลือกรายการผิด แล้วสคริปต์ยืนยันอัตโนมัติจนลบข้อมูลจริงไป
- **ใช้ข้อมูลทดสอบ และเก็บกวาดหลังทดสอบ:** ถ้าเผลอลบข้อมูลของผู้ใช้ ต้องกู้คืนและแจ้งผู้ใช้
- **จำลอง widget ให้เหมือนเบราว์เซอร์จริง:** ล็อกอินผ่าน origin ของหน้าเว็บ (ให้ได้ cookie httpOnly) แล้วเล่นบท widget
  - WebSocket: ต่อ `/ws?tenant=..&key=..` พร้อม header `Origin` → `hello` → `chat` → เมื่อได้ `call` ให้เรียก `call.path` ด้วย client ที่ถือ cookie แล้วส่ง `call_result` วนจนได้ `reply`
  - HTTP: ส่ง `client_exec: true` → ได้ `{turn_id, call}` → เรียก API → `POST /turn/{turn_id}` วนจนได้คำตอบ
  - ถ้าใช้ token ที่ล็อกอินผ่าน API ตรง ๆ จะไม่เจอปัญหาเดียวกับเบราว์เซอร์จริง

## สภาพแวดล้อมทดสอบในเครื่อง
- **client `planka-api`:** ฝังใน Planka, `host_agent=planka`, ใช้ `exams_demo` ได้ด้วย (ต้องผูกบัญชี รับทุกชื่อ/รหัส)
- **client `playground`:** หน้า `/playground` ไม่มี host ทุกระบบต้องผูกบัญชีผ่าน widget

### Planka (`C:\aucc2027\planka`)
sub agent `agents/planka/` (spec `agents/planka/openapi.json`), บัญชี `demo`/`demo`
- **รันแบบ dev:** `docker compose -f docker-compose-dev.yml up -d` API อยู่ที่ :1337 หน้าเว็บที่ :3000 (ส่งต่อ `/api` ให้)
  - แบบ production ใช้ port 3000 ชนกัน เปิดได้ทีละแบบ
  - อย่าหยุด container ของผู้ใช้โดยไม่ถาม
  - `down -v` ลบข้อมูลทั้งหมด ต้องถามก่อน
- **widget ฝังไว้แล้ว:** `planka/client/index.html` มี `<script>` หนึ่งบรรทัด เปิด :3000 แล้วล็อกอิน จะเห็นปุ่ม 💬
- **สร้าง spec ใหม่เมื่อ Planka เปลี่ยนเวอร์ชัน:**
  `MSYS_NO_PATHCONV=1 docker exec -w /app planka-planka-server-1 node -e "const c=require('./config/swagger');process.stdout.write(JSON.stringify(require('swagger-jsdoc')(c)))" > agents/planka/openapi.json`
- **สร้างข้อมูลทดสอบ:** `scripts/seed_planka.py http://localhost:1337` สร้างโปรเจกต์ "มหาวิทยาลัยทดสอบ" พร้อมบอร์ดตารางสอบ
- **ข้อเท็จจริงที่ spec ของ Planka ไม่ได้บอก (แก้ใน `agents/planka/agent.py` แล้ว):**
  - การสร้างหลายอย่างบังคับต้องมี `position`
  - `createBoard` ประกาศว่ารับแค่ multipart แต่รับ JSON ก็ได้
  - login ครั้งแรกต้องยอมรับข้อตกลง (terms) ในหน้าเว็บก่อน
