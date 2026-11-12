"""ลำดับงานของหนึ่งข้อความ: agent หลัก -> auth กลาง -> sub agent -> ตรวจคำตอบ

    ข้อความจากระบบ (widget)
      │ 1. agent หลักเลือก sub agent (router)
      │ 2. ขอ token ของระบบนั้น: ระบบที่ฝัง widget ใช้ session ในหน้าเว็บ / ระบบอื่นใช้ token ที่ผูกไว้ (vault)
      │    ยังไม่ผูก -> ตอบ link_required ให้ widget แสดงฟอร์มล็อกอินระบบนั้น
      │ 3. sub agent วนเรียกเครื่องมือ (native / openapi) ภายใต้กฎความปลอดภัยของแกนกลาง
      ▼ 4. ตอบกลับ + งานรอยืนยัน (ถ้ามี) สถานะระหว่างทางส่งผ่าน WebSocket hub
"""
import hashlib
import logging
import uuid

from app.auth import vault
from app.core import llm
from app.core.router import route
from app.schemas import AgentInfo, ChatResponse, ConfirmResponse
from app.services import bridge
from app.services.turns import owner_of
from app.subagent import registry
from app.subagent.base import AgentCtx, SubAgent
from app.subagent.toolset import SubAgentToolset, execute_confirmed

log = logging.getLogger("assistant")

MAX_HISTORY = 20
MAX_SEEN_IDS = 5000


class _Session:
    def __init__(self):
        self.history: list[dict] = []
        self.last_agent: str | None = None
        self.seen_ids: dict[str, set[str]] = {}   # ต่อ sub agent: id ที่เคยอ่านเจอ (กันโมเดลเดา id)


_sessions: dict[str, _Session] = {}


def _session_key(tenant_id: str, user_token: str, session_id: str) -> str:
    # ผูก session กับ client+ผู้ใช้ คนอื่นที่รู้ session_id จึงอ่านประวัติหรือ id ที่เห็นไม่ได้
    return hashlib.sha256(f"{tenant_id}:{user_token}:{session_id}".encode()).hexdigest()


def agent_info(agent: SubAgent, tenant_id: str, owner: str) -> AgentInfo:
    host = registry.host_agent(tenant_id)
    linked = (not agent.requires_auth) or agent.name == host or vault.get(owner, agent.name) is not None
    return AgentInfo(name=agent.name, title=agent.title, linked=linked,
                     can_login=agent.login_cfg is not None)


def make_ctx(agent: SubAgent, tenant_id: str, user_token: str, user_msg: str = "") -> AgentCtx | None:
    """เตรียมบริบทของ sub agent: token มาจากไหน และเรียก API ทางไหน
    คืน None ถ้าต้องผูกบัญชีระบบนี้ก่อน"""
    owner = owner_of(tenant_id, user_token)
    if agent.name == registry.host_agent(tenant_id):
        # ระบบที่ฝัง widget: ใช้ token ของหน้าเว็บ และถ้ามี bridge ให้หน้าเว็บเรียก API เอง (cookie httpOnly)
        return AgentCtx(agent=agent, tenant_id=tenant_id, owner=owner, token=user_token,
                        user_msg=user_msg, via_browser=bridge.current() is not None)
    token = vault.get(owner, agent.name) or ""
    if agent.requires_auth and not token:
        return None
    return AgentCtx(agent=agent, tenant_id=tenant_id, owner=owner, token=token, user_msg=user_msg)


async def chat(tenant_id: str, user_token: str, message: str,
               session_id: str | None = None) -> ChatResponse:
    session_id = session_id or str(uuid.uuid4())
    key = _session_key(tenant_id, user_token, session_id)
    sess = _sessions.setdefault(key, _Session())
    owner = owner_of(tenant_id, user_token)

    candidates = registry.agents_for(tenant_id)
    if len(candidates) > 1:
        await bridge.emit(owner, {"type": "status", "text": "กำลังพิจารณาว่าเป็นงานของระบบไหน"})
    r = await route(message, candidates, sess.last_agent)
    agent = r.agent
    log.info("ROUTE agent=%s how=%s", agent.name, r.how)
    await bridge.emit(owner, {"type": "status", "agent": agent.name,
                              "text": f"ส่งให้ผู้ช่วยของ {agent.title}"})

    ctx = make_ctx(agent, tenant_id, user_token, message)
    if ctx is None:
        info = agent_info(agent, tenant_id, owner)
        how = "ล็อกอินในกล่องด้านล่าง" if info.can_login else "ติดต่อผู้ดูแลระบบ"
        return ChatResponse(
            session_id=session_id, agent=agent.name, agent_title=agent.title, link_required=info,
            reply=f"งานนี้ต้องใช้ระบบ “{agent.title}” ซึ่งคุณยังไม่ได้ผูกบัญชีกับผู้ช่วย กรุณา{how} แล้วสั่งใหม่อีกครั้ง")

    seen = sess.seen_ids.setdefault(agent.name, set())
    if len(seen) > MAX_SEEN_IDS:
        seen.clear()
    toolset = SubAgentToolset(agent, seen)

    reply = await llm.run_tools(sess.history, message, toolset, ctx)
    if not reply:
        reply = ("กรุณากดยืนยันในหน้าจอเพื่อดำเนินการต่อ" if ctx.pending
                 else "ขออภัย ตอนนี้ยังตอบไม่ได้ ลองถามใหม่อีกครั้งนะคะ")
    # กันโมเดลพูดว่า "กดยืนยัน" ทั้งที่ไม่มีงานรอยืนยันจริง
    if ctx.pending is None and toolset.confirm_word in reply:
        reply = toolset.no_pending_reply
    # กันโมเดลอ้างว่าทำงานเขียน/ลบสำเร็จ ทั้งที่ยังไม่ได้ทำ (แก้ตัวแล้วยังผิด)
    elif toolset.check_reply(reply, ctx, message):
        reply = toolset.false_success_reply

    sess.history = (sess.history + [{"role": "user", "content": message},
                                    {"role": "assistant", "content": reply}])[-MAX_HISTORY:]
    sess.last_agent = agent.name
    return ChatResponse(session_id=session_id, reply=reply, agent=agent.name,
                        agent_title=agent.title, pending_action=ctx.pending)


async def confirm(rec, tenant_id: str, user_token: str) -> ConfirmResponse:
    """ทำงานที่ผู้ใช้กดยืนยัน ใน sub agent เจ้าของงาน (rec มาจาก pending.take แล้ว)"""
    agent = registry.get_agent(rec.agent)
    ctx = make_ctx(agent, tenant_id, user_token)
    if ctx is None:
        raise PermissionError(f"บัญชี {agent.title} หมดอายุหรือถูกยกเลิกการผูก กรุณาผูกบัญชีใหม่")
    message = await execute_confirmed(agent, rec, ctx)
    log.info("CONFIRMED agent=%s tool=%s risk=%s tenant=%s args=%s",
             rec.agent, rec.tool, rec.risk, rec.tenant_id, rec.args)  # ไม่ log token
    return ConfirmResponse(message=message, agent=agent.name)


async def link(tenant_id: str, user_token: str, agent_name: str, username: str, password: str) -> AgentInfo:
    """auth กลาง: ล็อกอินระบบหนึ่งด้วยบัญชีของผู้ใช้ แล้วเก็บ token ไว้ให้ sub agent ใช้"""
    agent = registry.get_agent(agent_name)
    if agent_name not in {a.name for a in registry.agents_for(tenant_id)}:
        raise KeyError(f"client นี้ใช้ระบบ {agent_name} ไม่ได้")
    owner = owner_of(tenant_id, user_token)
    token = await agent.login(username, password)
    vault.put(owner, agent.name, token)
    log.info("LINKED agent=%s tenant=%s", agent.name, tenant_id)
    return agent_info(agent, tenant_id, owner)


def agents_status(tenant_id: str, user_token: str) -> list[AgentInfo]:
    owner = owner_of(tenant_id, user_token)
    return [agent_info(a, tenant_id, owner) for a in registry.agents_for(tenant_id)]
