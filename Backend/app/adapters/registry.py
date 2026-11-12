from app.adapters.base import Adapter
from app.adapters.mock import MockAdapter
from app.config import TENANTS

# เพิ่มระบบใหม่: เขียน adapter แล้วลงทะเบียนที่นี่บรรทัดเดียว
ADAPTERS: dict[str, type[Adapter]] = {
    "mock": MockAdapter,
}


def get_adapter(tenant_id: str, user_token: str) -> Adapter:
    tenant = TENANTS.get(tenant_id)
    if not tenant:
        raise KeyError(f"ไม่รู้จัก tenant: {tenant_id}")
    adapter_cls = ADAPTERS.get(tenant["adapter"])
    if not adapter_cls:
        raise KeyError(f"ไม่รู้จัก adapter: {tenant['adapter']}")
    return adapter_cls(tenant["base_url"], user_token)