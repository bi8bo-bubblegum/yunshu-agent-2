# backend/tests/test_org_sync.py
"""OrgSyncService 单测：全量同步 / 幂等 / 对账清理 / 增量事件。

钉钉接口全部用 httpx.MockTransport 拦截（可变 state 模拟通讯录变化），
本地落库走 conftest 的真实 yunshu_test 库（每个测试前重建表）。
"""
import json

import pytest
from httpx import MockTransport, Response
from sqlalchemy import func, select

from app.models import Department, DingTalkSyncState, User
from app.services.dingtalk.client import DingTalkClient
from app.services.dingtalk.org_sync import (
    OrgSyncService,
    handle_dept_change_event,
    handle_user_change_event,
)


def build_state() -> dict:
    """模拟钉钉通讯录快照：部门树（1 根 + 2 研发 + 3 市场）+ 各部门直属员工。"""
    return {
        "departments": {
            1: {"dept_id": 1, "name": "云枢科技", "parent_id": None},
            2: {"dept_id": 2, "name": "研发部", "parent_id": 1},
            3: {"dept_id": 3, "name": "市场部", "parent_id": 1},
        },
        "users": {
            2: [
                {"userid": "user_a", "name": "张三", "dept_id_list": [2], "active": True,
                 "mobile": "13800000001", "title": "工程师"},
                {"userid": "user_b", "name": "李四", "dept_id_list": [2, 3], "active": True,
                 "mobile": "13800000002"},
            ],
            3: [
                # user_b 多部门：在部门 3 列表重复出现，验证按 userid 去重
                {"userid": "user_b", "name": "李四", "dept_id_list": [2, 3], "active": True},
                {"userid": "user_c", "name": "王五", "dept_id_list": [3], "active": True},
            ],
        },
    }


def make_client(state: dict) -> DingTalkClient:
    """按 state 分发钉钉通讯录接口的 MockTransport 客户端。"""
    def handler(request):
        path = request.url.path
        if path == "/v1.0/oauth2/accessToken":
            return Response(200, json={"accessToken": "TOKEN", "expireIn": 7200})
        body = json.loads(request.content or b"{}")
        if path == "/topapi/v2/department/get":
            did = int(body.get("dept_id"))
            return Response(200, json={"errcode": 0, "errmsg": "ok", "result": state["departments"].get(did, {})})
        if path == "/topapi/v2/department/listsub":
            pid = int(body.get("dept_id"))
            subs = [info for did, info in state["departments"].items() if info.get("parent_id") == pid]
            return Response(200, json={"errcode": 0, "errmsg": "ok", "result": subs})
        if path == "/topapi/v2/user/list":
            did = int(body.get("dept_id"))
            return Response(200, json={"errcode": 0, "errmsg": "ok", "result": {
                "has_more": False, "next_cursor": 0, "list": state["users"].get(did, [])}})
        if path == "/topapi/v2/user/get":
            uid = body.get("userid")
            for lst in state["users"].values():
                for u in lst:
                    if u["userid"] == uid:
                        return Response(200, json={"errcode": 0, "errmsg": "ok", "result": u})
            return Response(200, json={"errcode": 0, "errmsg": "ok", "result": {}})
        return Response(404, json={})

    return DingTalkClient(client_id="k", client_secret="s", transport=MockTransport(handler))


async def _all_depts(db):
    return list((await db.scalars(select(Department))).all())


async def _all_users(db):
    return list((await db.scalars(select(User))).all())


# ---------------------------------------------------------------------------
# 全量同步
# ---------------------------------------------------------------------------

async def test_full_sync_creates_depts_and_users(db_session):
    """部门树 + 用户 upsert：名称映射、主部门映射、根部门父级为空、同步游标落库。"""
    svc = OrgSyncService(db_session, make_client(build_state()))
    stats = await svc.sync_all()

    assert stats["dept_new"] == 3 and stats["user_new"] == 3
    depts = await _all_depts(db_session)
    users = await _all_users(db_session)
    assert len(depts) == 3 and len(users) == 3

    root = next(d for d in depts if d.dingtalk_dept_id == 1)
    yanfa = next(d for d in depts if d.dingtalk_dept_id == 2)
    shichang = next(d for d in depts if d.dingtalk_dept_id == 3)
    assert root.parent_id is None                    # 根部门父级为空
    assert yanfa.parent_id == root.id and shichang.parent_id == root.id

    zhang = next(u for u in users if u.dingtalk_userid == "user_a")
    assert zhang.display_name == "张三"               # 钉钉 name → display_name
    assert zhang.department_id == yanfa.id           # 主部门映射
    assert zhang.username == "user_a"                # 本地登录名取 userid
    assert zhang.source == "dingtalk" and zhang.status == "active"
    li = next(u for u in users if u.dingtalk_userid == "user_b")
    assert li.department_id == yanfa.id              # dept_id_list[0]=2 为主部门

    state_row = (await db_session.scalars(select(DingTalkSyncState))).first()
    assert state_row is not None and state_row.sync_type == "full_sync"
    assert state_row.last_synced_at is not None


async def test_full_sync_idempotent(db_session):
    """重复同步不重复建记录，只更新已有。"""
    svc = OrgSyncService(db_session, make_client(build_state()))
    await svc.sync_all()
    stats = await svc.sync_all()
    assert stats["dept_new"] == 0 and stats["user_new"] == 0
    assert stats["dept_updated"] == 3 and stats["user_updated"] == 3
    assert (await db_session.scalar(select(func.count()).select_from(Department))) == 3
    assert (await db_session.scalar(select(func.count()).select_from(User))) == 3


async def test_full_sync_reconcile_removed(db_session):
    """对账清理：钉钉删除部门/员工 → 本地部门删除、员工停用；active=false → 停用。"""
    state = build_state()
    svc = OrgSyncService(db_session, make_client(state))
    await svc.sync_all()

    # 模拟钉钉侧变化：部门 3 删除、user_c 离职、user_a 未激活（但仍在列表）
    del state["departments"][3]
    del state["users"][3]
    state["users"][2] = [
        {"userid": "user_a", "name": "张三", "dept_id_list": [2], "active": False},
        {"userid": "user_b", "name": "李四", "dept_id_list": [2], "active": True},
    ]

    stats = await svc.sync_all()
    assert stats["dept_removed"] == 1

    depts = await _all_depts(db_session)
    users = {u.dingtalk_userid: u for u in await _all_users(db_session)}
    assert all(d.dingtalk_dept_id != 3 for d in depts)
    assert users["user_c"].status == "inactive"     # 快照中消失 → 停用
    assert users["user_a"].status == "inactive"     # active=false → 停用
    assert users["user_b"].status == "active"


# ---------------------------------------------------------------------------
# 增量同步（Stream 事件）
# ---------------------------------------------------------------------------

async def test_incremental_user_add(db_session):
    """user_add_org：拉用户详情后新增（部门树已在库中）。"""
    state = build_state()
    await OrgSyncService(db_session, make_client(state)).sync_all()  # 先建部门树
    state["users"].setdefault(2, []).append(
        {"userid": "user_d", "name": "赵六", "dept_id_list": [2], "active": True})
    await handle_user_change_event(make_client(state), "user_add_org", {"UserId": "user_d"})

    u = (await db_session.scalars(select(User).where(User.dingtalk_userid == "user_d"))).first()
    assert u is not None and u.display_name == "赵六" and u.status == "active"
    yanfa = (await db_session.scalars(select(Department).where(Department.dingtalk_dept_id == 2))).first()
    assert u.department_id == yanfa.id


async def test_incremental_user_leave(db_session):
    """user_leave_org：本地用户软删除（inactive）。"""
    svc = OrgSyncService(db_session, make_client(build_state()))
    await svc.sync_all()
    await handle_user_change_event(make_client(build_state()), "user_leave_org", {"UserId": "user_a"})

    u = (await db_session.scalars(select(User).where(User.dingtalk_userid == "user_a"))).first()
    assert u.status == "inactive"


async def test_incremental_dept_modify(db_session):
    """org_dept_modify：部门改名。"""
    state = build_state()
    svc = OrgSyncService(db_session, make_client(state))
    await svc.sync_all()
    state["departments"][2]["name"] = "研发中心"
    await handle_dept_change_event(make_client(state), "org_dept_modify", {"DeptId": 2})

    d = (await db_session.scalars(select(Department).where(Department.dingtalk_dept_id == 2))).first()
    assert d.name == "研发中心"


async def test_incremental_dept_remove(db_session):
    """org_dept_remove：删除部门并解除用户归属引用。"""
    svc = OrgSyncService(db_session, make_client(build_state()))
    await svc.sync_all()
    await handle_dept_change_event(make_client(build_state()), "org_dept_remove", {"DeptId": 2})

    depts = await _all_depts(db_session)
    assert all(d.dingtalk_dept_id != 2 for d in depts)
    users = {u.dingtalk_userid: u for u in await _all_users(db_session)}
    # user_a / user_b 主部门是 2，部门删除后归属置空
    assert users["user_a"].department_id is None
    assert users["user_b"].department_id is None
    # 部门 3 仍存在（不受影响）
    assert any(d.dingtalk_dept_id == 3 for d in depts)
