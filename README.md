# AI Assistant (Plug-in)

ผู้ช่วย AI แบบ microservice ที่เสียบเข้ากับระบบเว็บใดก็ได้ ผู้ใช้พิมพ์สั่งงานเป็นภาษาไทยในหน้าระบบเดิม แล้ว AI ทำรายการให้ด้วยสิทธิ์ของผู้ใช้คนนั้น และสั่งงานข้ามไปยังระบบอื่นที่เชื่อมไว้ได้ด้วย

ระบบที่ใช้ทดลองเสียบตอนนี้คือ [Planka](https://github.com/plankanban/planka) (บอร์ดคัมบัง open source)

- **ระบบรอบข้างไม่ต้องแก้โค้ด** เพิ่มแค่ `<script>` หนึ่งบรรทัดเพื่อฝัง widget
- **agent หลัก 1 ตัว + sub agent 1:1 กับแต่ละระบบ** เราเขียน sub agent เองทีละระบบ เพราะแต่ละระบบมีเงื่อนไขต่างกัน
- **งานที่แก้ไขข้อมูลต้องยืนยันก่อนเสมอ** งานลบต้องยืนยันทุกครั้ง และกฎนี้บังคับด้วยโค้ด โมเดลข้ามไม่ได้
- **ใช้ Typhoon** (API รูปแบบ OpenAI) เป็น LLM หลัก

---

## สถาปัตยกรรม

```
 หน้าเว็บระบบ A (เช่น Planka)
  └─ widget.js ──────── WebSocket hub (/ws) ── แสดงสถานะเรียลไทม์ / ขอให้หน้าเว็บเรียก API ของระบบ A
                                │
                                ▼
                     agent หลัก (router)  ── วิเคราะห์ว่าข้อความนี้เป็นงานของระบบไหน
                                │
               ┌────────────────┼──────────────────┐
               ▼                ▼                  ▼
         sub agent A       sub agent B        sub agent C          ← agents/<ชื่อ>/ (1 ระบบ = 1 โฟลเดอร์)
         ├ skill.md        ├ skill.md         ├ ...
         ├ native fn       ├ native fn
         └ openapi ─┐      └ ...
                    ▼
            service ค้น action (search_actions) ── ส่งให้โมเดลเฉพาะ action ที่เกี่ยวข้อง
                                │
                     auth กลาง (vault) ── token ของแต่ละระบบที่ผู้ใช้ผูกไว้
```

### ลำดับงานของหนึ่งข้อความ
1. **widget ส่งข้อความ** ผ่าน WebSocket
2. **agent หลักเลือก sub agent** โดยเรียก LLM ให้น้อยที่สุด (Typhoon ช้า):
   - มี sub agent ตัวเดียว → ใช้เลย
   - ข้อความมีคำสำคัญ (`keywords`) ของระบบเดียว → ใช้ระบบนั้น
   - ข้อความสั้นแบบต่อเนื่อง เช่น "ใช่" → ใช้ระบบเดิมของบทสนทนา
   - นอกนั้นถาม LLM ด้วย prompt สั้น ๆ ให้ตอบชื่อระบบคำเดียว
3. **ขอ token ของระบบนั้นจาก auth กลาง**
   - ระบบที่ฝัง widget อยู่ (host): ใช้ session ของหน้าเว็บ และให้หน้าเว็บเป็นคนเรียก API (cookie httpOnly)
   - ระบบอื่น: ใช้ token ที่ผู้ใช้ผูกไว้ ถ้ายังไม่ผูก widget จะแสดงฟอร์มล็อกอินระบบนั้นในแชต
4. **sub agent วนเรียกเครื่องมือ** ภายใต้กฎความปลอดภัยของแกนกลาง
5. **ตอบกลับ** พร้อมกล่องยืนยัน (ถ้ามีงานเขียน/ลบ) สถานะระหว่างทางแสดงแบบเรียลไทม์

### ความสามารถ 3 แบบใน sub agent

| แบบ | ไฟล์ | เหมาะกับ |
|---|---|---|
| **skill (ความรู้)** | `skill.md` | โครงสร้างข้อมูล ศัพท์ ขั้นตอนที่ควรทำ ส่วนที่เอกสาร API ไม่บอก |
| **native function** | `agent.py` (`functions=[...]`) | API ที่คงที่หรือเปลี่ยนน้อย, งานที่ต้องแปลงข้อมูลเยอะ, ระบบที่ไม่มี OpenAPI |
| **openapi** | `openapi.json` + `OpenAPI(...)` | ให้ AI เรียนรู้ action เองจากเอกสาร ถ้ามี action มากกว่า `search_threshold` (ค่าเริ่มต้น 40) จะไม่ส่งรายการทั้งหมด แต่ให้โมเดลค้นด้วย `search_actions` แทน เพื่อประหยัด token |

### ระดับความเสี่ยงของ action

| ระดับ | กำหนดจาก (ค่าเริ่มต้น) | พฤติกรรม |
|---|---|---|
| `read` | `GET` / native `risk="read"` | ทำทันที |
| `write` | `POST` `PUT` `PATCH` / native `risk="write"` | หยุดและแสดงกล่องยืนยันก่อน |
| `destructive` | `DELETE` หรือกำหนดใน policy | ยืนยันทุกครั้ง ใช้ปุ่มสีแดง |
| ปิดใช้ | `blocked` / `blocked_tags` | AI มองไม่เห็นและเรียกไม่ได้ |

### กฎที่บังคับด้วยโค้ด (โมเดลข้ามไม่ได้ และ sub agent ไม่ต้องเขียนเอง)
- **ข้อความในกล่องยืนยันสร้างจากโค้ด** แสดงชื่อจริงของรายการที่จะแก้หรือลบ (openapi) หรือข้อความจาก `summarize` (native)
- **ชื่อไม่ตรงกับที่ผู้ใช้พิมพ์** กล่องยืนยันจะขึ้นคำเตือน ⚠
- **id ต้องมาจากผลการอ่านข้อมูลก่อน** โมเดลเดา id เองไม่ได้
- **โมเดลอ้างว่าทำสำเร็จทั้งที่ยังไม่ได้ทำ** ระบบให้แก้ตัวหนึ่งครั้ง ถ้ายังผิดจะตอบตามจริงแทน
- **ทำงานเขียนได้ทีละรายการ** งานที่รอยืนยันหมดอายุใน 5 นาที ใช้ได้ครั้งเดียว และผู้ใช้อื่นยืนยันแทนไม่ได้
- **ระบบอื่นไม่ถูกเรียกผ่านหน้าเว็บของระบบที่ฝัง widget** (กันส่ง request ข้ามระบบ)

---

## วิธีรัน

ต้องมี Python 3.11 ขึ้นไป (ทดสอบกับ 3.13)

```powershell
cd Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt

copy .env.example .env                # แล้วแก้ค่าในไฟล์ (อย่างน้อย LLM_API_KEY ของ Typhoon)
copy tenants.example.json tenants.json

uvicorn app.main:app --reload --port 8000
```

| URL | ใช้ทำอะไร |
|---|---|
| http://localhost:8000/playground | หน้าทดสอบแชต (client `playground` ผูกบัญชีทีละระบบ) |
| http://localhost:8000/docs | Swagger ของ API |
| http://localhost:8000/widget.js | ไฟล์ widget สำหรับฝังในระบบ |
| http://localhost:8000/health | สถานะ + รายชื่อ sub agent ที่โหลดได้ |

เทสต์ (ไม่ต้องต่อเครือข่าย): `python -m pytest -q`

backend อ่าน `.env`, `tenants.json` และไฟล์ใน `agents/` แค่ตอนเปิด แก้แล้วต้องรีสตาร์ท

### `.env`
- **`LLM_API_KEY`:** key ของ Typhoon (ค่าเริ่มต้นชี้ `https://api.opentyphoon.ai/v1` และโมเดล `typhoon-v2.5-30b-a3b-instruct`)
- **`APP_API_KEY`:** key หลักของผู้ดูแล ห้ามฝังในหน้าเว็บ
- **`AGENT_<ชื่อ>_BASE_URL`:** เปลี่ยนที่อยู่ระบบของ sub agent ตามที่ติดตั้ง เช่น `AGENT_PLANKA_BASE_URL`
- **`LINK_TTL`:** token ที่ผู้ใช้ผูกไว้หมดอายุหลังไม่ได้ใช้กี่วินาที (ค่าเริ่มต้น 8 ชั่วโมง)

---

## ต่อระบบใหม่ (เขียน sub agent)

**1. สร้างโฟลเดอร์ `Backend/agents/<ชื่อ>/`** มี `__init__.py` (ว่าง), `agent.py` และ `skill.md`

```python
# agents/helpdesk/agent.py
from app.subagent.base import NativeFunction, OpenAPI, SubAgent

async def get_tickets(ctx, args):
    status, data = await ctx.http("GET", "/api/tickets", {"status": args.get("status")})
    return data                                   # ใช้ token ของผู้ใช้ให้เอง

AGENT = SubAgent(
    name="helpdesk",
    title="ระบบแจ้งปัญหา",
    description="ตั๋วแจ้งปัญหา สถานะงานซ่อม ผู้รับผิดชอบ",   # agent หลักใช้เลือกระบบ
    keywords=["ตั๋ว", "แจ้งปัญหา", "helpdesk"],             # ตรงคำ = ไม่ต้องเรียก LLM เพื่อเลือกระบบ
    base_url="https://helpdesk.example.com",
    auth={"type": "bearer"},                          # หรือ {"type": "header", "name": "X-Api-Key"}
    login={"path": "/api/login",                      # ใช้ตอนผู้ใช้ผูกบัญชี (หรือส่งเป็นฟังก์ชัน async)
           "body": {"username": "{username}", "password": "{password}"},
           "token_field": "token"},
    functions=[
        NativeFunction("get_tickets", "ดูตั๋วแจ้งปัญหาของผู้ใช้",
                       {"type": "object", "properties": {"status": {"type": "string"}}},
                       get_tickets),
    ],
    openapi=OpenAPI(                                  # ไม่บังคับ
        spec="openapi.json",
        policy={
            "blocked_tags": ["Users", "Admin"],
            "blocked": ["deleteEverything"],
            "risk": {"closeTicket": "destructive"},
            "labels": {"createTicket": "แจ้งปัญหา"},
            "defaults": {"createTicket": {"channel": "web"}},
        },
    ),
)
```

| ค่า | ความหมาย |
|---|---|
| `functions` | native function: `run(ctx, args)` คืนข้อความหรือข้อมูล ถ้า `risk="write"`/`"destructive"` จะถูกเรียกหลังผู้ใช้กดยืนยันเท่านั้น และควรมี `summarize(args)` สำหรับกล่องยืนยัน |
| `ctx.http(...)` | เรียก API ของระบบนี้ ถ้าเป็นระบบที่ฝัง widget จะเรียกผ่านหน้าเว็บของผู้ใช้ ถ้าไม่ใช่จะเรียกจากเซิร์ฟเวอร์ด้วย token จาก auth กลาง |
| `policy.blocked_tags` / `blocked` | ซ่อน action ทั้งหมวด หรือทีละตัว |
| `policy.risk` | ปรับระดับความเสี่ยงราย action |
| `policy.labels` | ชื่อไทยที่แสดงในกล่องยืนยัน และช่วยให้ค้นด้วยภาษาไทยเจอ |
| `policy.defaults` | ค่าที่ส่งให้เองเมื่อ spec บอกไม่ครบ (ไม่แสดงในกล่องยืนยัน) |
| `search_threshold` | จำนวน action ที่เกินแล้วจะเปลี่ยนเป็นโหมดค้นหา |

**2. เขียน `skill.md`** อธิบายโครงสร้างข้อมูล และควรเริ่มอ่านจาก action ไหน ช่วยลดอาการโมเดลยอมแพ้

**3. เปิดให้ client ใช้** ใน `Backend/tenants.json` (ไฟล์นี้เก็บเฉพาะ "ระบบที่ฝัง widget")

```json
"helpdesk-web": {
  "title": "ระบบแจ้งปัญหา",
  "public_key": "pk_ค่าสุ่ม",
  "allowed_origins": ["https://helpdesk.example.com"],
  "widget": {"token": {"from": "cookie", "name": "accessToken"}},
  "host_agent": "helpdesk",
  "agents": ["helpdesk", "planka"]
}
```

| ช่อง | ความหมาย |
|---|---|
| `public_key` | key ที่ฝังใน widget ได้ ใช้ได้เฉพาะ client นี้ และเฉพาะ request จาก `allowed_origins` |
| `widget.token` | ที่อยู่ของ token ผู้ใช้ในหน้าเว็บ ถ้าไม่ตั้ง widget จะสร้างรหัสผู้ใช้ชั่วคราวเอง แล้วให้ผูกบัญชีทีละระบบ |
| `host_agent` | sub agent ของระบบที่ฝัง widget (ใช้ session ของหน้าเว็บ ไม่ต้องผูกบัญชี) |
| `agents` | sub agent ที่ผู้ใช้ของ client นี้สั่งงานได้ (ไม่ใส่ = ทุกตัว) |

**4. ฝัง widget ในหน้าเว็บ**

```html
<script src="https://assistant.example/widget.js" data-tenant="helpdesk-web" data-key="pk_ค่าสุ่ม" defer></script>
```

### sub agent ที่มีอยู่
| ชื่อ | ระบบ | ใช้ความสามารถ |
|---|---|---|
| `planka` | [Planka](https://github.com/plankanban/planka) บอร์ดคัมบัง (ระบบหลักที่ใช้ทดลอง) | openapi (69 action, โหมดค้นหา) + skill.md |
| `exams_demo` | ระบบจำลองในหน่วยความจำ (ไม่ใช่ระบบจริง) | ตัวอย่าง native function + ล็อกอินจำลอง ใช้ทดสอบ router และ auth กลางคู่กับ Planka |

---

## API ของ service

ทุก endpoint (ยกเว้น `/health`, `/widget.js`, `/playground`) ต้องมี key ซึ่งใช้ได้สองแบบ:
- `APP_API_KEY`
- `public_key` ของ client คู่กับ header `Origin` ที่อยู่ใน `allowed_origins`

### WebSocket `/ws?tenant=<client>&key=<key>` (ช่องทางหลักของ widget)

| ทิศทาง | ข้อความ |
|---|---|
| widget → | `hello {user_token}`, `chat {message, session_id?}`, `confirm`/`cancel {action_id}`, `link {agent, username, password}`, `unlink {agent}`, `call_result {call_id, status, body}` |
| → widget | `ready {agents}`, `status {text, agent?}`, `call {call_id, method, path, query, body, format}`, `reply`, `confirmed`, `cancelled`, `linked`, `error {status, detail}` |

ใส่ `req_id` ในข้อความได้ คำตอบจะมี `req_id` เดียวกัน

### HTTP (สำหรับสคริปต์และไคลเอนต์ที่ไม่ใช้ WebSocket)

| Endpoint | หน้าที่ |
|---|---|
| `POST /chat` | ส่งข้อความ `{tenant_id, user_token, message, session_id?, client_exec?}` |
| `POST /confirm` / `POST /cancel` | ยืนยันหรือยกเลิกงานที่รอยืนยัน `{tenant_id, user_token, action_id, client_exec?}` |
| `POST /turn/{turn_id}` | ส่งผลการเรียก API ระบบที่ฝัง widget กลับมา `{tenant_id, user_token, call_id, status, body}` |
| `POST /auth/link` / `POST /auth/unlink` | ผูก/ยกเลิกบัญชีระบบหนึ่ง `{tenant_id, user_token, agent, username?, password?}` |
| `POST /agents` | รายการ sub agent ที่ใช้ได้และสถานะการผูกบัญชี `{tenant_id, user_token}` |
| `GET /widget/config/{tenant_id}` | ค่าตั้งที่ widget ต้องรู้ (ไม่มีความลับ) |

เมื่อส่ง `client_exec: true` คำตอบของ `/chat` หรือ `/confirm` อาจเป็น `{turn_id, call}` แทนคำตอบจริง
แปลว่า service ขอให้ไคลเอนต์เรียก API ตาม `call` แล้วส่งผลที่ `/turn/{turn_id}` ทำซ้ำจนได้คำตอบจริงกลับมา
ถ้าผู้ใช้เปิด widget อยู่ สถานะของงานที่เริ่มจาก HTTP จะแสดงที่ widget ผ่าน hub ด้วย

---

## โครงสร้างโค้ด

```
Backend/
  agents/                 sub agent ของแต่ละระบบ (โค้ดเฉพาะระบบอยู่ที่นี่เท่านั้น)
    planka/               agent.py + skill.md + openapi.json
    exams_demo/           agent.py + skill.md (native function)
  app/
    main.py               endpoint HTTP + WebSocket
    security.py           ตรวจ key / origin ต่อ client
    core/
      router.py           agent หลัก: เลือก sub agent
      orchestrator.py     ลำดับงาน: router → auth กลาง → sub agent → ตรวจคำตอบ
      llm.py              คุยกับ LLM (Typhoon / OpenAI-compatible, Claude เป็นทางเลือก)
    subagent/
      base.py             SubAgent, NativeFunction, OpenAPI, AgentCtx
      toolset.py          เครื่องมือที่ให้โมเดล + กฎความปลอดภัยทั้งหมด
      registry.py         โหลด agents/*, client → sub agent ที่ใช้ได้
    openapi/
      spec.py             อ่าน OpenAPI → action + ระดับความเสี่ยง + policy
      catalog.py          แคตตาล็อก action, แปลงเวลา, ดึงชื่อรายการ
      search.py           service ค้น action (ประหยัด token)
    auth/vault.py         auth กลาง: token ของแต่ละระบบที่ผู้ใช้ผูกไว้
    hub/ws.py             WebSocket hub
    services/
      pending.py          งานที่รอผู้ใช้ยืนยัน
      bridge.py           ช่องทางกลับไปหาหน้าเว็บ (WebSocket หรือ HTTP turn)
      turns.py            bridge แบบ HTTP
    static/               widget.js, playground.html
  tests/
  tenants.json            client ที่ฝัง widget (ไม่ commit ใช้ tenants.example.json เป็นต้นแบบ)
```

---

## สถานะตอนนี้

| เฟส | งาน | สถานะ |
|---|---|---|
| 1 | แคตตาล็อก action จาก OpenAPI + กฎยืนยัน | ✅ ใช้งานได้ |
| 2 | key ต่อ client + จำกัด origin | ✅ บางส่วน (ยังไม่มี rate limit, client ยังเก็บเป็นไฟล์) |
| 3 | widget ฝังในระบบหลัก ใช้ session ผู้ใช้ เรียก API จากเบราว์เซอร์ | ✅ รุ่นทดลอง |
| 4 | agent หลัก + sub agent ต่อระบบ, ค้น action, auth กลาง, WebSocket hub | ✅ รุ่นแรก |
| 5 | หน้าแอดมิน, audit log, ย้ายข้อมูลออกจากหน่วยความจำ | ยังไม่เริ่ม |
| 6 | SSO / OAuth2 token exchange แทนการผูกบัญชีด้วยรหัสผ่าน | ยังไม่เริ่ม |

### ข้อจำกัดที่รู้อยู่
- **คุณภาพโมเดล:** Typhoon ตอบช้า 1–3 นาทีต่อข้อความ บางครั้งเลือกรายการผิดหรือยอมแพ้เร็ว
  กฎในโค้ดกันความเสียหายได้ แต่ผู้ใช้ต้องอ่านกล่องยืนยันทุกครั้ง
  agent หลักจึงพยายามเลือกระบบด้วยคำสำคัญก่อน เพื่อลดการเรียก LLM
- **ข้อมูลอยู่ในหน่วยความจำ:** session, งานรอยืนยัน, งานที่พักไว้, การเชื่อมต่อ WebSocket และ token ที่ผูกไว้
  หายเมื่อรีสตาร์ท และยังรันหลาย instance ไม่ได้
- **auth กลางรุ่นแรก:** ผูกบัญชีด้วยการล็อกอินผ่าน widget token ผูกกับ token ของหน้าเว็บที่ฝัง widget
  ถ้าผู้ใช้ล็อกอินระบบหลักใหม่ต้องผูกบัญชีใหม่
- **agent หลักส่งงานได้ 1 ระบบต่อข้อความ** งานที่ต้องใช้หลายระบบในข้อความเดียวต้องสั่งแยกกัน
- **service ค้น action เป็นการค้นด้วยคำสำคัญ** ภาษาไทยค้นเจอเมื่อมี `policy.labels` หรือเป็นคำกริยาพื้นฐาน
- **spec ไม่ตรงกับระบบจริง:** เจอบ่อย แก้ด้วย `policy` ใน `agent.py`
