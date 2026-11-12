"""service ค้น action ระหว่าง agent กับ OpenAPI

เอกสาร API ขนาดใหญ่ (หลายสิบถึงหลายร้อย action) ใส่ทั้งก้อนใน prompt จะเปลือง token และโมเดลเล็กสับสน
จึงให้โมเดลค้นด้วยคำสำคัญ แล้วส่งกลับเฉพาะรายการที่เกี่ยวข้อง

รุ่นนี้เป็นการค้นแบบคำสำคัญในหน่วยความจำ (ไม่ต้องมีบริการภายนอก)
- คำภาษาอังกฤษ: แยก camelCase / path / คำในคำอธิบาย และตัด s ท้ายคำ (cards -> card)
- คำภาษาไทย (ไม่มีช่องว่าง): เทียบด้วยชิ้นตัวอักษร 3 ตัว (trigram) กับชื่อไทยใน policy.labels
- คำกริยาพื้นฐานไทยแปลงเป็นอังกฤษ (ลบ -> delete ฯลฯ) ให้ค้นเอกสารภาษาอังกฤษเจอ
ถ้าต้องการความแม่นยำสูงขึ้น เปลี่ยนเป็น embedding/vector search ได้โดยคงหน้าตา search() ไว้
"""
import re

_WORD = re.compile(r"[a-z0-9]+|[฀-๿]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# คำไทยที่ใช้บ่อยในการสั่งงาน -> คำที่มักอยู่ในเอกสาร API
_TH_HINTS = {
    "ลบ": "delete remove", "สร้าง": "create", "เพิ่ม": "create add", "แก้": "update",
    "เปลี่ยน": "update", "ย้าย": "move update", "ดู": "get list", "รายการ": "list get",
    "ค้น": "search get", "ทั้งหมด": "list", "ล้าง": "clear", "สำเนา": "duplicate copy",
    "ความคิดเห็น": "comment", "คอมเมนต์": "comment", "ป้าย": "label", "งานย่อย": "task",
    "ลิสต์": "list", "การ์ด": "card", "บอร์ด": "board", "โปรเจกต์": "project", "สมาชิก": "membership",
    "ไฟล์แนบ": "attachment", "ผู้ใช้": "user", "แจ้งเตือน": "notification",
}


# กริยาที่ขึ้นต้นคำค้น -> คำที่ใช้ในชื่อ action (เช่น "list boards" = getBoards ไม่ใช่ createList)
_VERB_SYNONYMS = {"list": "get", "show": "get", "find": "get", "read": "get", "view": "get",
                  "remove": "delete", "add": "create", "new": "create", "edit": "update",
                  "change": "update", "rename": "update", "move": "update"}


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _words(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(_CAMEL.sub(" ", text or "").lower())]


def _trigrams(text: str) -> set[str]:
    t = re.sub(r"\s+", "", text or "")
    return {t[i:i + 3] for i in range(len(t) - 2)} if len(t) >= 3 else ({t} if t else set())


class ActionIndex:
    def __init__(self, actions: dict):
        self.actions = actions
        self._docs = []
        for a in actions.values():
            ident = set(_words(a.id))
            strong = ident | set(_words(" ".join(a.tags))) | set(_words(a.path))
            weak = set(_words(f"{a.summary} {a.description[:300]}"))
            thai = _trigrams(a.label or "")
            self._docs.append((a, ident, strong, weak, thai))

    def search(self, query: str, limit: int = 8) -> list:
        q = query or ""
        for th, en in _TH_HINTS.items():
            if th in q:
                q += " " + en
        latin = [w for w in _words(q) if not ("฀" <= w[0] <= "๿")]
        terms = set(latin)
        if latin and latin[0] in _VERB_SYNONYMS:
            terms.discard(latin[0])
            terms.add(_VERB_SYNONYMS[latin[0]])
        thai_q = "".join(w for w in _WORD.findall(query or "") if "฀" <= w[0] <= "๿")
        q_tri = _trigrams(thai_q)

        scored = []
        for a, ident, strong, weak, thai in self._docs:
            # คำที่อยู่ในชื่อ action เองได้คะแนนเพิ่ม (createList ชนะ createCard สำหรับ "create list")
            score = 3 * len(terms & strong) + len(terms & ident) + len(terms & weak)
            if q_tri and thai:
                score += 4 * len(q_tri & thai) / max(len(thai), 1)
            if score > 0:
                # read ก่อนเมื่อคะแนนเท่ากัน (ปลอดภัยกว่า และมักต้องอ่านก่อนเขียน)
                scored.append((score, a.risk == "read", a.id, a))
        scored.sort(key=lambda s: (-s[0], not s[1], s[2]))
        return [s[3] for s in scored[:max(1, min(limit, 20))]]
