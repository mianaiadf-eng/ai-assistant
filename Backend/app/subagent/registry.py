"""ทะเบียน sub agent: โหลดทุกโฟลเดอร์ใน agents/ ที่มี agent.py (ต้องประกาศตัวแปร AGENT)

  agents/<ชื่อ>/agent.py     AGENT = SubAgent(...)  native function / ค่าตั้ง / ล็อกอิน
  agents/<ชื่อ>/skill.md     ความรู้ของระบบ (ไม่บังคับ)
  agents/<ชื่อ>/openapi.json เอกสาร API (ไม่บังคับ)

ค่าที่ต่างกันตามที่ติดตั้ง ตั้งใน .env ได้โดยไม่ต้องแก้โค้ด agent:
  AGENT_<ชื่อตัวพิมพ์ใหญ่>_BASE_URL   เช่น AGENT_PLANKA_BASE_URL=https://planka.example.com
"""
import importlib
import logging

from app.config import AGENTS_DIR, TENANTS, env
from app.subagent.base import SubAgent

log = logging.getLogger("assistant")

_agents: dict[str, SubAgent] = {}
_loaded = False


def register(agent: SubAgent) -> SubAgent:
    """ลงทะเบียน agent (ใช้โดยตัวโหลด และในเทสต์)"""
    _agents[agent.name] = agent
    return agent


def unregister(name: str) -> None:
    _agents.pop(name, None)


def _load_all() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not AGENTS_DIR.is_dir():
        return
    for folder in sorted(p for p in AGENTS_DIR.iterdir() if (p / "agent.py").is_file()):
        try:
            module = importlib.import_module(f"agents.{folder.name}.agent")
        except Exception:
            log.exception("โหลด sub agent %s ไม่สำเร็จ", folder.name)
            continue
        agent = getattr(module, "AGENT", None)
        if not isinstance(agent, SubAgent):
            log.warning("agents/%s/agent.py ไม่มีตัวแปร AGENT", folder.name)
            continue
        agent.folder = folder
        skill = folder / "skill.md"
        if skill.is_file():
            agent.skill = skill.read_text(encoding="utf-8")
        override = env(f"AGENT_{agent.name.upper()}_BASE_URL")
        if override:
            agent.base_url = override.rstrip("/")
        _agents.setdefault(agent.name, agent)
        log.info("SUB AGENT %s (%s)", agent.name, agent.title)


def all_agents() -> dict[str, SubAgent]:
    _load_all()
    return _agents


def get_agent(name: str) -> SubAgent:
    agent = all_agents().get(name)
    if agent is None:
        raise KeyError(f"ไม่รู้จัก sub agent: {name}")
    return agent


# ------------------------------------------------ client (ระบบที่ฝัง widget)

def client_cfg(tenant_id: str) -> dict:
    cfg = TENANTS.get(tenant_id)
    if cfg is None:
        raise KeyError(f"ไม่รู้จัก tenant: {tenant_id}")
    return cfg


def host_agent(tenant_id: str) -> str | None:
    """sub agent ของระบบที่ฝัง widget อยู่ (เรียก API ผ่านหน้าเว็บด้วย session ของผู้ใช้)"""
    return client_cfg(tenant_id).get("host_agent")


def agents_for(tenant_id: str) -> list[SubAgent]:
    """sub agent ที่ client นี้ใช้ได้ (ค่าเริ่มต้น: ทุกตัว) ตัว host อยู่ลำดับแรก"""
    cfg = client_cfg(tenant_id)
    available = all_agents()
    names = cfg.get("agents") or list(available)
    out = [available[n] for n in names if n in available]
    host = cfg.get("host_agent")
    out.sort(key=lambda a: a.name != host)
    return out
