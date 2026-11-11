---
name: planka
description: เปิด/เชื่อมต่อ/ทดสอบ Planka ในเครื่อง (C:\aucc2027\planka) กับ backend ของ ai-assistant ผ่านแคตตาล็อก OpenAPI (tenant planka-api) — ใช้เมื่อต้องรัน Planka, สร้างข้อมูลทดสอบ, อัปเดต spec, ปรับ policy ของ tenant หรือแก้ปัญหา login/อ่าน/สร้าง/ลบกับ Planka
---

# Planka ในเครื่อง + ai-assistant

## ภาพรวม
- Planka (source) อยู่ที่ `C:\aucc2027\planka` รันด้วย Docker Compose
- backend ต่อ Planka แบบไม่มีโค้ดเฉพาะ Planka: อ่าน OpenAPI จาก `Backend/specs/planka.json`
  แล้ว AI เรียก API ผ่าน `app/catalog/` (ไม่มี adapter ของ Planka แล้ว)
- tenant คือ `planka-api` ใน `Backend/tenants.json` ประกอบด้วย base_url, openapi, auth, login,
  notes (ความรู้ที่ spec ไม่มี) และ policy (blocked_tags, risk, labels, defaults)
- บัญชีทดสอบ: `demo` / `demo` (email `demo@demo.demo`) ตั้งใน
  `C:\aucc2027\planka\docker-compose.override.yml` (อยู่ใน .gitignore ของ planka ใช้ในเครื่องเท่านั้น)

## เปิดระบบ
Planka มีสองแบบ ใช้ฐานข้อมูล (volume) ชุดเดียวกัน แต่ใช้ port 3000 ชนกัน เปิดได้ทีละแบบ
- **แบบ dev** (ที่ผู้ใช้เปิดใช้อยู่): `docker compose -f docker-compose-dev.yml up -d`
  API ที่ http://localhost:1337 หน้าเว็บที่ http://localhost:3000
- **แบบ production**: `docker compose up -d` ทั้ง API และเว็บอยู่ที่ http://localhost:3000
  ถ้าใช้แบบนี้ต้องเปลี่ยน `base_url` ของ `planka-api` เป็น `http://localhost:3000`

ก่อนเปิดต้องให้ Docker Desktop ทำงานก่อน ถ้า `docker info` แจ้งว่าหา pipe ไม่เจอ แปลว่ายังไม่เปิด:
`Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"`
อย่าหยุดหรือรีสตาร์ท container แบบ dev ของผู้ใช้โดยไม่ถามก่อน
`docker compose down -v` จะลบข้อมูลทิ้งทั้งหมด ต้องถามผู้ใช้ก่อนทุกครั้ง

backend (รันในโฟลเดอร์ Backend):
`./.venv/Scripts/python -m uvicorn app.main:app --port 8000`
backend อ่าน `.env`, `tenants.json` และ spec แค่ตอนเปิด แก้ไฟล์เหล่านี้แล้วต้องรีสตาร์ท

## อัปเดต spec เมื่อ Planka เปลี่ยนเวอร์ชัน
Planka ไม่เปิด `/swagger.json` ให้โดยค่าเริ่มต้น ให้สร้าง spec จาก source ใน container ของ dev server:
```bash
cd /c/aucc2027/ai-assistant/Backend && MSYS_NO_PATHCONV=1 docker exec -w /app planka-planka-server-1 \
  node -e "const c=require('./config/swagger');process.stdout.write(JSON.stringify(require('swagger-jsdoc')(c)))" \
  > specs/planka.json
```
ต้องใส่ `MSYS_NO_PATHCONV=1` เพราะถ้าไม่ใส่ Git Bash จะแปลง `/app` เป็น path ของ Windows

## ข้อมูลทดสอบ
`PYTHONIOENCODING=utf-8 ./.venv/Scripts/python scripts/seed_planka.py http://localhost:1337`
สร้างโปรเจกต์ "มหาวิทยาลัยทดสอบ" > บอร์ด "ตารางสอบ" (ลิสต์ สอบกลางภาค/สอบปลายภาค/งานที่ต้องทำ)
ถ้ามีโปรเจกต์นี้อยู่แล้วจะข้าม และสคริปต์ยอมรับ terms ให้ผู้ใช้ demo อัตโนมัติ

## widget ในหน้า Planka
- `planka/client/index.html` มีบรรทัด `<script src="http://localhost:8000/widget.js" data-tenant="planka-api" data-key="pk_...">`
  บรรทัดนี้เป็นจุดเดียวที่แก้ใน Planka ส่วน `data-key` คือ `public_key` ของ tenant ซึ่งไม่ใช่ความลับ
- widget อ่าน token ของผู้ใช้จาก cookie `accessToken` ของ Planka ตามค่า `widget.token` ใน tenant จึงไม่ต้องล็อกอินซ้ำ
  ปุ่ม 💬 แสดงเฉพาะตอนที่ล็อกอิน Planka อยู่
- token จากหน้าเว็บของ Planka ผูกกับ cookie `httpOnlyToken` (httpOnly) ถ้า backend เอาไปเรียก Planka เองจะได้ 401
  widget จึงส่ง `client_exec: true` ไปด้วย ให้ backend ตอบกลับเป็น `{turn_id, call}` จากนั้น widget เรียก `/api/...`
  จากหน้า Planka เอง แล้วส่งผลกลับที่ `POST /turn/{turn_id}` (ดู `app/services/turns.py`)
  ถ้าจะจำลองกรณีนี้ด้วยสคริปต์ ให้ล็อกอินด้วย `withHttpOnlyToken: true` ผ่าน `http://localhost:3000`
- public key ใช้ได้เฉพาะ tenant `planka-api` และ request จาก origin ใน `allowed_origins` (http://localhost:3000) เท่านั้น
  ถ้าเปลี่ยน port หรือโดเมนของ Planka ต้องแก้ `allowed_origins` แล้วรีสตาร์ท backend

## ทดสอบ
- **แบบ manual:** เปิด http://localhost:8000/playground แล้วกด 💬
  หรือใช้ bookmarklet ที่หน้านั้นให้มา เพื่อฉีด widget เข้าหน้า Planka
- **เทสต์อัตโนมัติ:** `./.venv/Scripts/python -m pytest -q` ไม่ต้องต่อเครือข่าย
- **ยิง API ด้วยสคริปต์:** ใช้ Python (httpx) ห้ามใช้ curl ใน Git Bash เพราะส่งภาษาไทยเพี้ยน
  และตั้ง `PYTHONIOENCODING=utf-8`
- **ห้ามกด `/confirm` อัตโนมัติแบบไม่ดู:** ต้องตรวจ `pending_action.summary` ก่อนว่าเป็นรายการที่ตั้งใจ
  และไม่ขึ้นต้นด้วย ⚠ เคยมีกรณีโมเดลเลือกการ์ดผิดใบ แล้วสคริปต์ที่ยืนยันอัตโนมัติลบข้อมูลจริงไป

## ข้อเท็จจริงของ Planka ที่ spec ไม่ได้บอก
- POST สร้าง card/list/label/task บังคับต้องมี `position` ทั้งที่ spec บอกว่าไม่บังคับ
  แก้แล้วด้วย `policy.defaults`
- login ครั้งแรกของผู้ใช้ได้ 403 `{step: "accept-terms"}` ผู้ใช้ต้อง login ผ่านหน้าเว็บแล้วกดยอมรับก่อน
  (หรือรัน seed script) backend จะแจ้งข้อความนี้ให้ผู้ใช้เห็น
- เวลาใน API เป็น UTC แต่ catalog แปลงเป็นเวลาไทยให้ทั้งขาเข้าและขาออกแล้ว

## ปัญหาที่เจอบ่อย
| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| `/login` ได้ 404 "ไม่รู้จัก tenant" | เพิ่ม tenant แล้วยังไม่รีสตาร์ท backend |
| "เชื่อมต่อระบบหลักไม่ได้" | Planka ยังไม่ขึ้น ให้ตรวจ `docker ps` และดูว่า base_url ตรงกับแบบที่เปิดอยู่ (dev = 1337) |
| `docker compose up` แจ้งว่า port 3000 ถูกใช้แล้ว | มีแบบ dev รันอยู่ ใช้แบบ dev ต่อไป อย่าเปิดสองแบบพร้อมกัน |
| ยืนยันแล้ว "ระบบหลักปฏิเสธ (รหัส 422)" | ขาดฟิลด์ที่ Planka บังคับ ให้เพิ่มใน `policy.defaults` |
| โมเดลตอบว่าไม่มีข้อมูลหรือขอ id จากผู้ใช้ | เพิ่มคำอธิบายใน `notes` ของ tenant |
