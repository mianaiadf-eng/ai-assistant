# Planka Embed

ฝังปุ่มแชตผู้ช่วย AI เข้าหน้า Planka ด้วย nginx โดยไม่แก้โค้ด Planka

## ไฟล์

- `nginx.conf` ส่งต่อทุกอย่างไปที่ Planka และแทรกสคริปต์ widget ท้ายหน้า HTML
- `docker-compose.assistant.yml` รัน nginx ที่พอร์ต 3000
- `assistant/widget.js` ปุ่มและหน้าต่างแชต
- `assistant/test.html` หน้าทดสอบ widget แยก

## วิธีติดตั้ง

1. คัดลอกไฟล์ทั้งหมดไปไว้ในโฟลเดอร์เดียวกับ `docker-compose.yml` ของ Planka
   (`assistant/` ต้องเป็นโฟลเดอร์ย่อย)

2. แก้ `docker-compose.yml` ของ Planka: ลบ 2 บรรทัดนี้ออกจาก service `planka`
   เพราะ nginx จะใช้พอร์ต 3000 แทน

       ports:
         - 3000:1337

3. เปิด `assistant/widget.js` แล้วแก้ `API_KEY` จาก `CHANGE_ME` เป็นคีย์จริงของ backend
   (ใช้ทดสอบในเครื่องเท่านั้น คีย์อยู่ในหน้าเว็บ ใครก็เห็นได้)

4. รัน

       docker compose up -d --force-recreate planka
       docker compose -f docker-compose.assistant.yml up -d

5. ต้องรัน backend (uvicorn) และ Ollama ไว้ด้วย แล้วเปิด http://localhost:3000
   กด Ctrl+F5 จะเห็นปุ่มกลมเขียวมุมขวาล่าง

## หมายเหตุ

- ชื่อ container `planka-planka-1` ใน `nginx.conf` และเครือข่าย `planka_default`
  ขึ้นกับชื่อโฟลเดอร์ของ Planka ถ้าโฟลเดอร์ชื่ออื่น ต้องแก้ให้ตรง
- ถ้าตั้ง API_KEY เป็นค่าอื่น ต้องตรงกับที่ backend ตั้งไว้ใน `.env`