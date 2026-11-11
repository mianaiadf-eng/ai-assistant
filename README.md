# AI Assistant (Plug-in)

ผู้ช่วย AI แบบ microservice ที่เสียบเข้ากับระบบเว็บใดก็ได้ ผู้ใช้พิมพ์สั่งงานเป็นภาษาไทยในหน้าระบบเดิม แล้ว AI ทำรายการให้ด้วยสิทธิ์ของผู้ใช้คนนั้น

- **ระบบหลักไม่ต้องแก้โค้ด** เพิ่มแค่ `<script>` หนึ่งบรรทัดเพื่อฝัง widget
- **AI เรียนรู้ระบบเองจากเอกสาร API (OpenAPI)** ไม่ต้องเขียน adapter ใหม่ทุกระบบ
- **งานที่แก้ไขข้อมูลต้องยืนยันก่อนเสมอ** งานลบต้องยืนยันทุกครั้ง และกฎนี้บังคับด้วยโค้ด โมเดลข้ามไม่ได้

---

## แนวคิดของระบบ

```
หน้าเว็บระบบหลัก
 └─ <script src=".../widget.js" data-tenant="..." data-key="pk_...">   ← สิ่งเดียวที่ระบบหลักเพิ่ม
        │ 1. ผู้ใช้พิมพ์สั่ง
        ▼
 Assistant service (Backend/)
   • อ่าน OpenAPI ของระบบหลัก → แคตตาล็อก action พร้อมระดับความเสี่ยง
   • ให้ LLM เลือก action และพารามิเตอร์
   • ตรวจกฎทุกข้อด้วยโค้ด (ห้ามเดา id, งานเขียน/ลบต้องรอยืนยัน)
        │ 2. "ช่วยเรียก GET /api/... ให้หน่อย"
        ▼
 widget เรียก API ระบบหลักจากหน้าเว็บ ด้วย session/cookie ของผู้ใช้
        │ 3. ส่งผลกลับ → service ทำงานต่อ → ตอบผู้ใช้ หรือแสดงกล่องยืนยัน
```

**ทำไม widget ต้องเป็นคนเรียก API:** ระบบส่วนใหญ่ผูก session ไว้กับ cookie แบบ httpOnly ซึ่งเซิร์ฟเวอร์ของเราเข้าไม่ถึง
ให้เบราว์เซอร์เรียกแทนจึงได้ประโยชน์สามข้อ:
- ผู้ใช้ไม่ต้องล็อกอินซ้ำ
- service ไม่ต้องเก็บรหัสผ่าน
- AI ทำได้ไม่เกินสิทธิ์ของผู้ใช้คนนั้น เพราะระบบหลักตรวจสิทธิ์เอง

### ระดับความเสี่ยงของ action

| ระดับ | กำหนดจาก (ค่าเริ่มต้น) | พฤติกรรม |
|---|---|---|
| `read` | `GET` | ทำทันที |
| `write` | `POST` `PUT` `PATCH` | หยุดและแสดงกล่องยืนยันก่อน |
| `destructive` | `DELETE` หรือแอดมินกำหนด | ยืนยันทุกครั้ง ใช้ปุ่มสีแดง |
| ปิดใช้ | แอดมินกำหนด | AI มองไม่เห็นและเรียกไม่ได้ |

### กฎที่บังคับด้วยโค้ด (โมเดลข้ามไม่ได้)
- **ข้อความในกล่องยืนยันสร้างจากโค้ด** แสดงชื่อจริงของรายการที่จะแก้หรือลบ (ดึงจากระบบหลัก) และชื่อของที่ที่จะสร้าง เช่น "ใน 'งานที่ต้องทำ'"
- **ชื่อไม่ตรงกับที่ผู้ใช้พิมพ์** กล่องยืนยันจะขึ้นคำเตือน ⚠
- **id ต้องมาจากผลการอ่านข้อมูลก่อน** โมเดลเดา id เองไม่ได้
- **โมเดลอ้างว่าทำสำเร็จทั้งที่ยังไม่ได้ทำ** ระบบให้แก้ตัวหนึ่งครั้ง ถ้ายังผิดจะตอบตามจริงแทน
- **ทำงานเขียนได้ทีละรายการ** งานที่รอยืนยันหมดอายุใน 5 นาที ใช้ได้ครั้งเดียว และผู้ใช้อื่นยืนยันแทนไม่ได้
- **เวลา:** แปลงเป็นเวลาไทยให้อัตโนมัติ ทั้งตอนอ่านและตอนส่ง

---

## วิธีรัน

ต้องมี Python 3.11 ขึ้นไป (ทดสอบกับ 3.13)

```powershell
cd Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt

copy .env.example .env                # แล้วแก้ค่าในไฟล์ (ดูหัวข้อถัดไป)
copy tenants.example.json tenants.json

uvicorn app.main:app --reload --port 8000
```

| URL | ใช้ทำอะไร |
|---|---|
| http://localhost:8000/playground | หน้าทดสอบแชต (ล็อกอินใน widget เอง) |
| http://localhost:8000/docs | Swagger ของ API |
| http://localhost:8000/widget.js | ไฟล์ widget สำหรับฝังในระบบหลัก |

เทสต์ (ไม่ต้องต่อเครือข่าย): `python -m pytest -q`

backend อ่าน `.env`, `tenants.json` และไฟล์ spec แค่ตอนเปิด แก้ไฟล์เหล่านี้แล้วต้องรีสตาร์ท

### `.env`
- **`APP_API_KEY`:** key หลักของผู้ดูแล ห้ามฝังในหน้าเว็บ
- **`LLM_PROVIDER`:** เลือกได้สองแบบ
  - `openai`: API รูปแบบ OpenAI เช่น Typhoon, Ollama, OpenRouter ต้องตั้ง `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`
  - `claude`: ต้องตั้ง `ANTHROPIC_API_KEY`

---

## ต่อระบบใหม่

ไม่ต้องเขียนโค้ด ทำสามขั้น:

**1. หาไฟล์ OpenAPI 3 (JSON) ของระบบ** จะชี้เป็น URL หรือเก็บไว้ใน `Backend/specs/` ก็ได้

**2. เพิ่ม tenant ใน `Backend/tenants.json`**

```json
"my-system": {
  "title": "ชื่อระบบที่แสดงใน widget",
  "public_key": "pk_ค่าสุ่ม",
  "allowed_origins": ["https://my-system.example.ac.th"],
  "widget": {"token": {"from": "cookie", "name": "accessToken"}},

  "base_url": "https://my-system.example.ac.th",
  "openapi": "specs/my-system.json",
  "auth": {"type": "bearer"},
  "login": {"path": "/api/login",
            "body": {"username": "{username}", "password": "{password}"},
            "token_field": "token"},

  "notes": "ความรู้ที่เอกสาร API ไม่มี เช่น ข้อมูลแต่ละอย่างหมายถึงอะไร ควรเริ่มดูจาก endpoint ไหน",
  "policy": {
    "blocked_tags": ["Users", "Admin"],
    "blocked": ["deleteEverything"],
    "risk": {"approveRequest": "destructive"},
    "labels": {"createTask": "สร้างงาน"},
    "defaults": {"createTask": {"position": 65536}}
  }
}
```

| ช่อง | ความหมาย |
|---|---|
| `public_key` | key ที่ฝังใน widget ได้ ใช้ได้เฉพาะ tenant นี้ และเฉพาะ request จาก `allowed_origins` |
| `widget.token` | ที่อยู่ของ token ผู้ใช้ในหน้าเว็บระบบหลัก ถ้าไม่ตั้ง widget จะแสดงหน้าล็อกอินของตัวเอง |
| `auth` | วิธีส่ง token: `{"type": "bearer"}` หรือ `{"type": "header", "name": "X-Api-Key"}` |
| `login` | ใช้กับหน้าล็อกอินของ widget และ `/login` (ไม่บังคับ) |
| `notes` | ใส่ใน prompt ช่วยให้ AI เข้าใจโครงสร้างข้อมูล |
| `policy.blocked_tags` / `blocked` | ซ่อน action ทั้งหมวด หรือทีละตัว |
| `policy.risk` | ปรับระดับความเสี่ยงราย action |
| `policy.labels` | ชื่อไทยที่แสดงในกล่องยืนยัน |
| `policy.defaults` | ค่าที่ส่งให้เองเมื่อ spec บอกไม่ครบ เช่น ช่องที่ระบบบังคับแต่ spec ไม่ได้บอก (ไม่แสดงในกล่องยืนยัน) |

**3. ฝัง widget ในหน้าเว็บระบบหลัก**

```html
<script src="https://assistant.example/widget.js" data-tenant="my-system" data-key="pk_ค่าสุ่ม" defer></script>
```

### ระบบแบบไหนต่อได้ตอนนี้
- **ต่อได้:**
  - มี OpenAPI 3 แบบ JSON
  - ยืนยันตัวตนด้วย Bearer token หรือ API key ใน header
  - หน้าเว็บอ่าน token ได้จาก cookie
- **action ที่ body เป็น multipart/form:** ใช้ได้ถ้าไม่บังคับแนบไฟล์ ส่วนการอัปโหลดไฟล์ทำผ่านแชตไม่ได้
- **ยังไม่รองรับ:**
  - spec แบบ YAML และ Swagger 2.0
  - การยืนยันตัวตนแบบ OAuth
  - ระบบที่ไม่มีเอกสาร API (ต้องเขียน adapter เองใน `app/adapters/`)

---

## API ของ service

ทุก endpoint (ยกเว้น `/health`, `/widget.js`, `/playground`) ต้องมี header `X-API-Key` ซึ่งใช้ได้สองแบบ:
- `APP_API_KEY`
- `public_key` ของ tenant คู่กับ header `Origin` ที่อยู่ใน `allowed_origins`

| Endpoint | หน้าที่ |
|---|---|
| `POST /chat` | ส่งข้อความ `{tenant_id, user_token, message, session_id?, client_exec?}` |
| `POST /confirm` / `POST /cancel` | ยืนยันหรือยกเลิกงานที่รอยืนยัน `{tenant_id, user_token, action_id, client_exec?}` |
| `POST /turn/{turn_id}` | widget ส่งผลการเรียก API ระบบหลักกลับมา `{tenant_id, user_token, call_id, status, body}` |
| `POST /login` | ล็อกอินผ่าน service (ใช้กับหน้าล็อกอินของ widget) |
| `GET /widget/config/{tenant_id}` | ค่าตั้งที่ widget ต้องรู้ (ไม่มีความลับ) |

เมื่อส่ง `client_exec: true` คำตอบของ `/chat` หรือ `/confirm` อาจเป็น `{turn_id, call}` แทนคำตอบจริง
แปลว่า service ขอให้ widget เรียก API ตาม `call` แล้วส่งผลที่ `/turn/{turn_id}` ทำซ้ำจนได้คำตอบจริงกลับมา

---

## โครงสร้างโค้ด

```
Backend/
  app/
    main.py            endpoint ทั้งหมด
    security.py        ตรวจ key / origin ต่อ tenant
    catalog/
      spec.py          อ่าน OpenAPI → action + ระดับความเสี่ยง + policy
      catalog.py       เรียก API ระบบหลัก (ผ่านเบราว์เซอร์หรือจากเซิร์ฟเวอร์), แปลงเวลา, ดึงชื่อรายการ
    core/
      assistant.py     วนคุยกับ LLM (Claude / OpenAI-compatible)
      toolsets.py      เครื่องมือที่ให้โมเดล + กฎความปลอดภัยทั้งหมด
    services/
      pending.py       งานที่รอผู้ใช้ยืนยัน
      turns.py         พักงานระหว่างรอ widget เรียก API
    adapters/          ทางเลือกสำหรับระบบที่ไม่มี OpenAPI (ตอนนี้มี mock สำหรับทดสอบ)
    static/            widget.js, playground.html
  specs/               ไฟล์ OpenAPI ของระบบที่ต่อไว้
  tests/
  tenants.json         ค่าตั้งของแต่ละระบบ (ไม่ commit ใช้ tenants.example.json เป็นต้นแบบ)
```

---

## สถานะตอนนี้

| เฟส | งาน | สถานะ |
|---|---|---|
| 1 | แคตตาล็อก action จาก OpenAPI + กฎยืนยัน | ✅ ใช้งานได้ |
| 2 | key ต่อ tenant + จำกัด origin | ✅ บางส่วน (ยังไม่มี rate limit, tenant ยังเก็บเป็นไฟล์) |
| 3 | widget ฝังในระบบหลัก ใช้ session ผู้ใช้ เรียก API จากเบราว์เซอร์ | ✅ รุ่นทดลอง |
| 4 | หน้าแอดมินจัดการแคตตาล็อก/policy, audit log | ยังไม่เริ่ม |
| 5 | AI อ่านหน้าจอสำหรับระบบที่ไม่มี API | ยังไม่เริ่ม |

ทดสอบจริงกับระบบบอร์ดงาน open source ตัวหนึ่งที่รันในเครื่อง ได้ผลดังนี้:
- อ่าน สร้าง และลบข้อมูลผ่านแชตได้
- กล่องยืนยันแสดงชื่อรายการถูกต้อง
- id ที่เดาเองถูกปฏิเสธ

### ข้อจำกัดที่รู้อยู่
- **คุณภาพโมเดล:** โมเดลขนาดเล็ก (เช่น Typhoon 30B) ตอบช้า 1–3 นาทีต่อข้อความ บางครั้งเลือกรายการผิดหรือยอมแพ้เร็ว
  กฎในโค้ดกันความเสียหายได้ แต่ผู้ใช้ต้องอ่านกล่องยืนยันทุกครั้ง
- **ข้อมูลอยู่ในหน่วยความจำ:** session, งานรอยืนยัน และงานที่พักไว้ หายเมื่อรีสตาร์ท และยังรันหลาย instance ไม่ได้
- **spec ไม่ตรงกับระบบจริง:** เจอบ่อย เช่น ไม่บอกช่องที่บังคับ หรือประกาศว่ารับเฉพาะ multipart ตอนนี้แก้ด้วย `policy` แต่ยังต้องแก้ไฟล์เอง
- **widget รุ่นทดลอง:** ใช้ได้เฉพาะระบบที่หน้าเว็บอ่าน token จาก cookie ได้
