# backend/tests/test_approvals_api.py
"""审批列表 API（M4 全走钉钉审批：本地 decide 下线，仅剩列表 + 钉钉事件回写驱动状态）。"""
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.main import app
from app.models.dingtalk import ApprovalBinding
from app.models.experience import Experience
from app.models.org import User
from app.models.trace import Approval


async def _register(transport, username, display_name="X"):
    """注册并登录，返回 headers。"""
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": username, "password": "x123456", "display_name": display_name})
        r = await c.post("/api/auth/login", json={"username": username, "password": "x123456"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _set_role(db_session, username, role_code, department_id=None):
    """通过测试库 session 直接修改用户角色（注册接口默认 member）。"""
    user = (await db_session.scalars(select(User).where(User.username == username))).first()
    user.role_code = role_code
    user.department_id = department_id
    await db_session.commit()


async def _fire_event(pid: str, **overrides):
    """触发钉钉审批实例事件回写（默认 finish-agree，overrides 可覆盖）。"""
    from app.services.dingtalk.approval_gateway import handle_approval_instance_change
    data = {"processInstanceId": pid, "type": "finish", "result": "agree", "staffId": "ding_approver"}
    data.update(overrides)
    await handle_approval_instance_change(data)


@pytest.mark.asyncio
async def test_list_approvals_by_category(db_session):
    """admin 按 category 筛选可见全部审批单。"""
    db_session.add(Approval(category="tool_call", risk="critical", mode="sync", ref_type="trace",
                            ref_id="t1", title="删除文件", status="pending", requester_id="u1",
                            approver_role="admin"))
    db_session.add(Approval(category="experience_promotion", mode="async", ref_type="experience",
                            ref_id="e1", title="经验晋升", status="pending", requester_id="u2",
                            approver_role="dept_owner"))
    await db_session.commit()
    transport = ASGITransport(app=app)
    h = await _register(transport, "admin")
    await _set_role(db_session, "admin", "admin")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/approvals?status=pending&category=tool_call", headers=h)
        assert len(r.json()) == 1
        assert r.json()[0]["category"] == "tool_call"
        r = await c.get("/api/approvals?status=pending&category=experience_promotion", headers=h)
        assert len(r.json()) == 1
        assert r.json()[0]["category"] == "experience_promotion"


@pytest.mark.asyncio
async def test_list_shows_binding_fields(db_session):
    """列表补钉钉绑定字段：process_instance_id / push_status / pc_url / mobile_url。"""
    db_session.add(Approval(category="tool_call", risk="critical", mode="sync", ref_type="trace",
                            ref_id="t1", title="删除文件", status="pending", requester_id="u1",
                            approver_role="admin"))
    await db_session.commit()
    ap_id = (await db_session.scalars(select(Approval).where(Approval.ref_id == "t1"))).first().id
    db_session.add(ApprovalBinding(approval_id=ap_id, process_code="PROC_TOOL",
                                   process_instance_id="inst_binding", status="pushed",
                                   mobile_url="https://m.test", pc_url="https://p.test"))
    await db_session.commit()
    transport = ASGITransport(app=app)
    h = await _register(transport, "admin")
    await _set_role(db_session, "admin", "admin")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/approvals?status=pending", headers=h)
        row = r.json()[0]
        assert row["process_instance_id"] == "inst_binding"
        assert row["push_status"] == "pushed"
        assert row["pc_url"] == "https://p.test"
        assert row["mobile_url"] == "https://m.test"


@pytest.mark.asyncio
async def test_member_cannot_see_others_approvals(db_session):
    """member 列表可见性：看不到他人发起的审批单。"""
    db_session.add(Approval(category="tool_call", risk="critical", mode="sync", ref_type="trace",
                            ref_id="t1", title="删除文件", status="pending", requester_id="other-user",
                            approver_role="admin"))
    await db_session.commit()
    transport = ASGITransport(app=app)
    h = await _register(transport, "member2")  # 默认 member
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/approvals?status=pending", headers=h)
        assert r.json() == []


@pytest.mark.asyncio
async def test_dept_owner_cannot_see_other_dept_approvals(db_session):
    """dept_owner 列表可见性：看不到跨部门审批单。

    本地审批资格（decide）已随 M4 下线，审批权交给钉钉 OA 模板流程；
    列表仅保留可见性过滤：跨部门待办不可见。"""
    db_session.add(User(id="11111111-1111-1111-1111-111111111111", username="other", password_hash="x",
                        department_id="dept-9", display_name="Other"))
    db_session.add(Approval(category="experience_promotion", mode="async", ref_type="experience",
                            ref_id="e1", title="经验晋升", status="pending",
                            requester_id="11111111-1111-1111-1111-111111111111",
                            approver_role="dept_owner"))
    await db_session.commit()
    transport = ASGITransport(app=app)
    h = await _register(transport, "owner2")
    await _set_role(db_session, "owner2", "dept_owner", department_id="dept-1")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/approvals?status=pending", headers=h)
        assert r.json() == []


@pytest.mark.asyncio
async def test_decide_route_removed(db_session):
    """本地审批 decide 路由已下线（全走钉钉审批）：POST /decide → 404。"""
    db_session.add(Approval(category="tool_call", risk="critical", mode="sync", ref_type="trace",
                            ref_id="t1", title="删除文件", status="pending", requester_id="u1",
                            approver_role="admin"))
    await db_session.commit()
    ap_id = (await db_session.scalars(select(Approval).where(Approval.ref_id == "t1"))).first().id
    transport = ASGITransport(app=app)
    h = await _register(transport, "admin4")
    await _set_role(db_session, "admin4", "admin")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(f"/api/approvals/{ap_id}/decide", json={"approve": True}, headers=h)
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_shows_requester_and_approver_username(db_session):
    """审批列表展示发起人/审批人 username（而非不可读的 id）；审批人来自钉钉事件回写反查。"""
    transport = ASGITransport(app=app)
    h_req = await _register(transport, "requser")
    h_admin = await _register(transport, "admin3")
    await _set_role(db_session, "admin3", "admin")
    # 给 admin3 挂钉钉 userid：事件回写 staffId 反查本地审批人
    admin3 = (await db_session.scalars(select(User).where(User.username == "admin3"))).first()
    admin3.dingtalk_userid = "ding_admin3"
    await db_session.commit()
    req = (await db_session.scalars(select(User).where(User.username == "requser"))).first()
    # ref_id 用合法 UUID：apply_decision 晋升路径按 ref_id 反查 Experience（经验不存在则 no-op）
    ap = Approval(category="experience_promotion", mode="async", ref_type="experience",
                  ref_id="11111111-1111-1111-1111-111111111111", title="经验晋升", status="pending",
                  context={"experience_id": "11111111-1111-1111-1111-111111111111",
                           "from_scope": "personal", "to_scope": "dept"},
                  requester_id=str(req.id), approver_role="admin")
    db_session.add(ap)
    await db_session.commit()
    db_session.add(ApprovalBinding(approval_id=ap.id, process_code="PROC_EXP",
                                   process_instance_id="inst_apx", status="pushed"))
    await db_session.commit()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # 待审批：有发起人 username，无审批人
        r = await c.get("/api/approvals?status=pending", headers=h_admin)
        row = next(x for x in r.json() if x["id"] == ap.id)
        assert row["requester_name"] == "requser"
        assert row["approver_name"] is None
        # 钉钉审批通过事件回写 → 展示审批人 username
        await _fire_event("inst_apx", staffId="ding_admin3")
        r = await c.get("/api/approvals?status=approved", headers=h_admin)
        row = next(x for x in r.json() if x["id"] == ap.id)
        assert row["approver_name"] == "admin3"
        assert row["requester_name"] == "requser"
        assert row["push_status"] == "synced"


@pytest.mark.asyncio
async def test_approve_experience_promotion_via_dingtalk(db_session, monkeypatch, mock_dingtalk_push):
    """经验晋升审批（钉钉 agree 事件回写）：dept_owner 审批单通过后经验层级晋升。"""
    async def fake_embed(texts):
        return [[0.1] * 1536] * len(texts)
    monkeypatch.setattr("app.services.experience_service.embed_texts", fake_embed)
    transport = ASGITransport(app=app)
    h = await _register(transport, "owner")
    await _set_role(db_session, "owner", "dept_owner", department_id="dept-1")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        exp_id = (await c.post("/api/experiences", json={"title": "t", "summary": "s"}, headers=h)).json()["id"]
        await c.post(f"/api/experiences/{exp_id}/submit", json={"to_scope": "dept"}, headers=h)
        r = await c.get("/api/approvals?status=pending", headers=h)
        assert r.status_code == 200
        ap_id = r.json()[0]["id"]
        assert r.json()[0]["push_status"] == "pushed"
        # 钉钉审批通过 → 经验晋升
        pid = (await db_session.scalars(
            select(ApprovalBinding).where(ApprovalBinding.approval_id == ap_id))).first().process_instance_id
        await _fire_event(pid)
        exp = await db_session.get(Experience, exp_id)
        assert exp.scope == "dept" and exp.status == "approved"


@pytest.mark.asyncio
async def test_reject_promotion_restores_status_via_dingtalk(db_session, monkeypatch, mock_dingtalk_push):
    """经验晋升被钉钉驳回 → 恢复审批前状态（personal 回 draft），可再次晋升。

    真实事故：驳回后经验 status 卡在 pending，前端永远显示「审批中」，无法再晋升。"""
    async def fake_embed(texts):
        return [[0.1] * 1536] * len(texts)
    monkeypatch.setattr("app.services.experience_service.embed_texts", fake_embed)
    transport = ASGITransport(app=app)
    h = await _register(transport, "rej_owner")
    await _set_role(db_session, "rej_owner", "dept_owner", department_id="dept-1")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        exp_id = (await c.post("/api/experiences", json={"title": "被驳回经验", "summary": "s"},
                               headers=h)).json()["id"]
        await c.post(f"/api/experiences/{exp_id}/submit", json={"to_scope": "dept"}, headers=h)
        r = await c.get("/api/approvals?status=pending", headers=h)
        ap_id = r.json()[0]["id"]
        pid = (await db_session.scalars(
            select(ApprovalBinding).where(ApprovalBinding.approval_id == ap_id))).first().process_instance_id
        # 钉钉驳回 → 经验恢复 personal/draft
        await _fire_event(pid, result="refuse")
        exp = await db_session.get(Experience, exp_id)
        assert exp.scope == "personal" and exp.status == "draft"
        # 恢复草稿后可再次晋升
        r = await c.post(f"/api/experiences/{exp_id}/submit", json={"to_scope": "company"}, headers=h)
        assert r.status_code == 200
