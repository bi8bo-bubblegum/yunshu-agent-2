# backend/app/services/dingtalk/org_sync.py
"""组织架构同步（部门 / 用户）——M3。

全量同步（sync_all）：
  1. 从根部门（dept_id=1）BFS 递归拉取部门树（topapi/v2/department/listsub）
  2. 逐部门分页拉取直属员工（topapi/v2/user/list，has_more 终止）
  3. 按 dingtalk_dept_id / dingtalk_userid 幂等 upsert 到本地
  4. 对账清理：本地 dingtalk 记录不在快照中的 → 部门删除 / 用户停用

增量同步（Stream 事件，M1 预留的入口）：
  - user_add_org / user_modify_org → 拉单用户详情 upsert
  - user_leave_org → 本地 status=inactive
  - org_dept_create / org_dept_modify → 拉单部门详情 upsert
  - org_dept_remove → 解除引用后删除本地部门

定时兜底（start_org_sync_loop）：lifespan 后台任务按 DINGTALK_SYNC_INTERVAL_MINUTES 全量对账。

名称映射（与用户确认）：钉钉 user.name → User.display_name；部门 name → Department.name；
userid → dingtalk_userid；dept_id → dingtalk_dept_id。主部门取 dept_id_list 第一个。
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import Department, DingTalkSyncState, User
from app.repositories.department_repo import DepartmentRepository
from app.repositories.user_repo import UserRepository
from app.services.dingtalk.client import DingTalkClient, dingtalk_client

logger = logging.getLogger(__name__)

# 事件类型字面量（与 stream.py 保持一致，为避免循环 import 直接写常量）
EV_USER_LEAVE = "user_leave_org"
EV_DEPT_REMOVE = "org_dept_remove"

# 钉钉同步用户的本地密码占位：钉钉用户不走密码登录（M2 登录按 dingtalk_userid 匹配）
PLACEHOLDER_PASSWORD = "!"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OrgSyncService:
    """组织同步服务：持有 db 会话 + 钉钉客户端，同步逻辑幂等。"""

    def __init__(self, db, dt_client: DingTalkClient | None = None):
        self.db = db
        self.dt_client = dt_client or dingtalk_client
        self.dept_repo = DepartmentRepository(db)
        self.user_repo = UserRepository(db)

    # ------------------------------------------------------------------
    # 全量同步
    # ------------------------------------------------------------------

    async def sync_all(self) -> dict:
        """全量同步钉钉组织到本地（幂等），返回统计。"""
        snapshot = await self._fetch_snapshot()
        return await self._apply_snapshot(snapshot)

    async def _fetch_snapshot(self) -> dict:
        """拉取钉钉全量组织快照：部门树 + 各部门直属员工（按 userid 去重）。"""
        # 根部门详情（dept_id=1），根部门自身信息 listsub 拿不到，必须 department/get
        root = await self.dt_client.get_dept_detail(1)
        root_id = root.get("dept_id") or root.get("id") or 1
        root_id = int(root_id)
        dept_map: dict[int, dict] = {
            root_id: {"name": root.get("name") or "根部门", "parent_id": root.get("parent_id")}
        }
        # BFS 逐级遍历子部门（listsub 只取直属下级）
        queue = [root_id]
        while queue:
            pid = queue.pop(0)
            for sub in await self.dt_client.list_sub_departments(pid):
                did = int(sub.get("dept_id"))
                if did in dept_map:
                    continue
                dept_map[did] = {"name": sub.get("name"), "parent_id": sub.get("parent_id")}
                queue.append(did)
        # 逐部门拉直属员工；多部门员工会重复出现，按 userid 去重
        seen: dict[str, dict] = {}
        for did in dept_map:
            for user in await self.dt_client.list_all_dept_users(did):
                uid = user.get("userid")
                if uid and uid not in seen:
                    seen[uid] = user
        return {"dept_map": dept_map, "users": list(seen.values())}

    async def _apply_snapshot(self, snapshot: dict) -> dict:
        """把钉钉快照应用到本地库：部门/用户 upsert + 对账清理。"""
        dept_map = snapshot["dept_map"]
        dingtalk_users = snapshot["users"]
        stats = {"dept_new": 0, "dept_updated": 0, "dept_removed": 0,
                 "user_new": 0, "user_updated": 0, "user_deactivated": 0}
        now = _now()

        # ---- 部门 upsert（BFS 顺序保证父先于子，父映射已建）----
        local_depts = await self.dept_repo.list()
        local_by_dtalk = {d.dingtalk_dept_id: d for d in local_depts if d.dingtalk_dept_id is not None}
        dtalk_to_local: dict[int, str] = {}  # 钉钉 dept_id → 本地部门 id
        for did in self._order_depts(dept_map):
            info = dept_map[did]
            local = local_by_dtalk.get(did)
            parent_dtalk = info.get("parent_id")
            # 父部门映射；根部门（parent 为空/自指/不在快照）父级为 None
            parent_local = dtalk_to_local.get(parent_dtalk) if parent_dtalk and parent_dtalk != did else None
            if local is None:
                local = Department(
                    name=info.get("name") or f"钉钉部门{did}",
                    parent_id=parent_local,
                    dingtalk_dept_id=did,
                    source="dingtalk",
                    synced_at=now,
                )
                self.db.add(local)
                await self.db.flush()  # 拿到本地 id 供子部门/用户映射
                stats["dept_new"] += 1
            else:
                local.name = info.get("name") or local.name
                local.parent_id = parent_local
                local.synced_at = now
                stats["dept_updated"] += 1
            dtalk_to_local[did] = local.id

        # ---- 用户 upsert ----
        local_users = await self.user_repo.list()
        local_users_by_dtalk = {u.dingtalk_userid: u for u in local_users if u.dingtalk_userid}
        dingtalk_ids: set[str] = set()
        for info in dingtalk_users:
            userid = info.get("userid")
            if not userid:
                continue
            dingtalk_ids.add(userid)
            local = local_users_by_dtalk.get(userid)
            dept_list = info.get("dept_id_list") or []
            main_dtalk = dept_list[0] if dept_list else None
            department_id = dtalk_to_local.get(main_dtalk) if main_dtalk else None
            # active 缺省视为在职（active=false 表示未激活钉钉，也标停用由对账覆盖）
            status = "active" if info.get("active", True) else "inactive"
            if local is None:
                self.db.add(User(
                    username=userid,  # 钉钉 userid 唯一且稳定，直接作本地登录名
                    password_hash=PLACEHOLDER_PASSWORD,
                    display_name=info.get("name") or userid,
                    department_id=department_id,
                    dingtalk_userid=userid,
                    mobile=info.get("mobile"),
                    email=info.get("email"),
                    avatar=info.get("avatar"),
                    job_number=info.get("job_number"),
                    title=info.get("title"),
                    status=status,
                    source="dingtalk",
                    synced_at=now,
                ))
                stats["user_new"] += 1
            else:
                local.display_name = info.get("name") or local.display_name
                local.department_id = department_id
                local.mobile = info.get("mobile")
                local.email = info.get("email")
                local.avatar = info.get("avatar")
                local.job_number = info.get("job_number")
                local.title = info.get("title")
                local.status = status
                local.synced_at = now
                stats["user_updated"] += 1

        # ---- 对账清理：本地 dingtalk 记录不在快照中的 ----
        # 部门删除（先解除用户归属与子部门父级引用）
        for local in local_depts:
            if local.source == "dingtalk" and local.dingtalk_dept_id not in dept_map:
                for u in local_users:
                    if u.department_id == local.id:
                        u.department_id = None
                for child in local_depts:
                    if child.parent_id == local.id and child.id != local.id:
                        child.parent_id = None
                await self.dept_repo.delete(local)
                stats["dept_removed"] += 1
        # 用户停用（离职 / 移出授权范围，快照中不再出现）
        for local in local_users:
            if (local.source == "dingtalk" and local.dingtalk_userid not in dingtalk_ids
                    and local.status != "inactive"):
                local.status = "inactive"
                local.synced_at = now
                stats["user_deactivated"] += 1

        await self.db.commit()
        await self._update_sync_state(now)
        return stats

    @staticmethod
    def _order_depts(dept_map: dict[int, dict]) -> list[int]:
        """按父先子后的 BFS 顺序返回部门 id，保证 upsert 时父映射已建立。"""
        roots = [d for d, i in dept_map.items()
                 if not i.get("parent_id") or i.get("parent_id") == d
                 or i.get("parent_id") not in dept_map]
        ordered: list[int] = []
        visited: set[int] = set()
        queue = list(roots)
        while queue:
            did = queue.pop(0)
            if did in visited:
                continue
            visited.add(did)
            ordered.append(did)
            for cid, cinfo in dept_map.items():
                if cinfo.get("parent_id") == did and cid not in visited:
                    queue.append(cid)
        return ordered

    async def _update_sync_state(self, ts: datetime) -> None:
        """记录最近全量同步时间（供前端/状态查询与定时对账判定）。"""
        state = (await self.db.scalars(
            select(DingTalkSyncState).where(DingTalkSyncState.sync_type == "full_sync"))).first()
        if state is None:
            state = DingTalkSyncState(sync_type="full_sync")
            self.db.add(state)
        state.last_synced_at = ts
        await self.db.commit()

    # ------------------------------------------------------------------
    # 增量同步（Stream 事件单条处理，全部幂等）
    # ------------------------------------------------------------------

    async def upsert_single_user(self, userid: str) -> None:
        """入职/变更：拉用户详情后 upsert（主部门映射到本地，不存在则置空）。"""
        info = await self.dt_client.get_user_detail(userid)
        if not info.get("userid"):
            logger.warning("钉钉用户详情为空，跳过增量同步 userid=%s", userid)
            return
        userid = info["userid"]
        now = _now()
        local = await self.user_repo.get_by(dingtalk_userid=userid)
        dept_list = info.get("dept_id_list") or []
        main_dtalk = dept_list[0] if dept_list else None
        department_id = None
        if main_dtalk is not None:
            dept = await self.dept_repo.get_by(dingtalk_dept_id=int(main_dtalk))
            department_id = dept.id if dept else None
        status = "active" if info.get("active", True) else "inactive"
        if local is None:
            self.db.add(User(
                username=userid, password_hash=PLACEHOLDER_PASSWORD,
                display_name=info.get("name") or userid, department_id=department_id,
                dingtalk_userid=userid, mobile=info.get("mobile"), email=info.get("email"),
                avatar=info.get("avatar"), job_number=info.get("job_number"), title=info.get("title"),
                status=status, source="dingtalk", synced_at=now,
            ))
        else:
            local.display_name = info.get("name") or local.display_name
            local.department_id = department_id
            local.mobile = info.get("mobile")
            local.email = info.get("email")
            local.avatar = info.get("avatar")
            local.job_number = info.get("job_number")
            local.title = info.get("title")
            local.status = status
            local.synced_at = now
        await self.db.commit()

    async def deactivate_user(self, userid: str) -> None:
        """离职：本地对应用户软删除（status=inactive）。"""
        local = await self.user_repo.get_by(dingtalk_userid=userid)
        if local and local.status != "inactive":
            local.status = "inactive"
            local.synced_at = _now()
            await self.db.commit()

    async def upsert_single_dept(self, dept_id: int) -> None:
        """部门新增/变更：拉部门详情后 upsert（父部门未同步则父级置空）。"""
        info = await self.dt_client.get_dept_detail(int(dept_id))
        did = info.get("dept_id") or info.get("id")
        if did is None:
            logger.warning("钉钉部门详情为空，跳过增量同步 dept_id=%s", dept_id)
            return
        did = int(did)
        now = _now()
        local = await self.dept_repo.get_by(dingtalk_dept_id=did)
        parent = info.get("parent_id")
        parent_local = None
        if parent and parent != did:
            p = await self.dept_repo.get_by(dingtalk_dept_id=int(parent))
            parent_local = p.id if p else None
        if local is None:
            self.db.add(Department(
                name=info.get("name") or f"钉钉部门{did}", parent_id=parent_local,
                dingtalk_dept_id=did, source="dingtalk", synced_at=now,
            ))
        else:
            local.name = info.get("name") or local.name
            local.parent_id = parent_local
            local.synced_at = now
        await self.db.commit()

    async def remove_department(self, dept_id: int) -> None:
        """部门删除：先解除该部门下用户归属与子部门父级引用，再删除本地部门。"""
        local = await self.dept_repo.get_by(dingtalk_dept_id=int(dept_id))
        if not local:
            return
        for u in await self.user_repo.list(department_id=local.id):
            u.department_id = None
        for child in await self.dept_repo.list(parent_id=local.id):
            child.parent_id = None
        await self.dept_repo.delete(local)
        await self.db.commit()


# ------------------------------------------------------------------
# Stream 事件入口（M1 stream.py 调用；异常交由 stream 层统一记日志兜底）
# ------------------------------------------------------------------

async def handle_user_change_event(dt_client, event_type: str, data: dict) -> None:
    """员工入职/变更/离职事件的增量同步入口。"""
    userid = data.get("UserId")
    if not userid:
        logger.warning("用户事件缺少 UserId: type=%s data=%s", event_type, data)
        return
    async with SessionLocal() as db:
        svc = OrgSyncService(db, dt_client)
        if event_type == EV_USER_LEAVE:
            await svc.deactivate_user(userid)
        else:
            await svc.upsert_single_user(userid)


async def handle_dept_change_event(dt_client, event_type: str, data: dict) -> None:
    """部门新增/变更/删除事件的增量同步入口。"""
    dept_id = data.get("DeptId")
    if dept_id is None:
        logger.warning("部门事件缺少 DeptId: type=%s data=%s", event_type, data)
        return
    async with SessionLocal() as db:
        svc = OrgSyncService(db, dt_client)
        if event_type == EV_DEPT_REMOVE:
            await svc.remove_department(int(dept_id))
        else:
            await svc.upsert_single_dept(int(dept_id))


# ------------------------------------------------------------------
# 定时兜底：全量对账（lifespan 后台常驻任务）
# ------------------------------------------------------------------

async def start_org_sync_loop() -> None:
    """按 DINGTALK_SYNC_INTERVAL_MINUTES 周期执行全量对账，直至任务取消。"""
    interval = max(int(settings.DINGTALK_SYNC_INTERVAL_MINUTES), 1) * 60
    logger.info("钉钉组织同步定时对账启动，间隔 %d 分钟", interval / 60)
    while True:
        await asyncio.sleep(interval)
        try:
            async with SessionLocal() as db:
                result = await OrgSyncService(db).sync_all()
            logger.info("钉钉组织定时对账完成: %s", result)
        except Exception as e:
            logger.warning("钉钉组织定时对账失败: %s", e)
