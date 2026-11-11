"""นิยาม tool ที่ AI เรียกได้"""
TOOLS = [
    {
        "name": "get_exams",
        "description": (
            "ดึงตารางสอบจากระบบของมหาลัย ใช้ทุกครั้งที่ผู้ใช้ถามเรื่องการสอบ "
            "ระบุช่วงวันที่ได้ ถ้าไม่ระบุจะได้ทั้งหมด"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {
                    "type": "string",
                    "description": "วันเริ่มต้นช่วงที่ค้นหา รูปแบบ YYYY-MM-DD",
                },
                "date_to": {
                    "type": "string",
                    "description": "วันสิ้นสุดช่วงที่ค้นหา รูปแบบ YYYY-MM-DD (รวมวันนั้นทั้งวัน)",
                },
                "exam_type": {
                    "type": "string",
                    "enum": ["midterm", "final", "makeup"],
                    "description": "ประเภทสอบ: midterm=กลางภาค, final=ปลายภาค, makeup=สอบซ่อม",
                },
            },
        },
    }
]