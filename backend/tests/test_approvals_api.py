# backend/tests/test_approvals_api.py
import asyncio
import time

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.main import app
from app.models.experience import Experience
from app.models.org import User
from app.models.trace import Approval, ExecutionTrace


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


@pytest.mark.asyncio
async def test_approve_experience_promotion(db_session, monkeypatch):
    """经验晋升审批：本部门 dept_owner 通过后经验层级晋升。"""
    async def fake_embed(texts):
        return [[0.1] * 1536] * len(texts)
    monkeypatch.setattr("app.services.experience_service.embed_texts", fake_embed)
    transport = ASGITransport(app=app)
    h = await _register(transport, "owner")
    await _set_role(db_session, "owner", "dept_owner", department_id="dept-1")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # 创建待审批经验
        r = await c.post("/api/experiences", json={"title": "t", "summary": "s"}, headers=h)
        exp_id = r.json()["id"]
        await c.post(f"/api/experiences/{exp_id}/submit", json={"to_scope": "dept"}, headers=h)
        # 审批中心查看待办
        r = await c.get("/api/approvals?status=pending", headers=h)
        assert len(r.json()) >= 1
        ap_id = r.json()[0]["id"]
        # 审批通过
        r = await c.post(f"/api/approvals/{ap_id}/decide", json={"approve": True, "comment": "ok"}, headers=h)
        assert r.status_code == 200
        exp = await db_session.get(Experience, exp_id)
        assert exp.scope == "dept" and exp.status == "approved"


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
async def test_member_cannot_approve_admin_approval(db_session):
    """member 无审批资格：审批 admin 专属（critical）审批单返回 403。"""
    db_session.add(Approval(category="tool_call", risk="critical", mode="sync", ref_type="trace",
                            ref_id="t1", title="删除文件", status="pending", requester_id="u1",
                            approver_role="admin"))
    await db_session.commit()
    ap_id = (await db_session.scalars(select(Approval).where(Approval.ref_id == "t1"))).first().id
    transport = ASGITransport(app=app)
    h = await _register(transport, "member1")  # 默认 member
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(f"/api/approvals/{ap_id}/decide", json={"approve": True}, headers=h)
        assert r.status_code == 403


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
async def test_decide_tool_call_returns_immediately(db_session, monkeypatch):
    """critical 审批通过：decide 立即返回（图恢复改后台任务，不再阻塞请求）。

    真实事故：decide 同步 await 恢复图执行（graph.ainvoke 含 LLM，最长 90s）→
    请求长时间不返回，前端「无反应」；而审批单状态已 commit 为 approved，
    用户再次点击即抛 404「审批单不存在或已处理」。修复后 decide 立即返回 ok，
    图恢复在后台独立 session 执行。"""
    from app.services import approval_service

    trace = ExecutionTrace(id="11111111-1111-1111-1111-111111111111", user_id="u1",
                           conversation_id="22222222-2222-2222-2222-222222222222",
                           status="interrupted")
    db_session.add(trace)
    db_session.add(Approval(category="tool_call", risk="critical", mode="sync",
                            ref_type="trace", ref_id=str(trace.id), title="发布活动",
                            status="pending", requester_id="u1", approver_role="admin"))
    await db_session.commit()
    ap_id = (await db_session.scalars(
        select(Approval).where(Approval.ref_id == str(trace.id)))).first().id

    # fake 图恢复：睡 1s。若 decide 仍同步 await，请求会明显变慢
    async def slow_impl(db, approval_id, approved, trace_id):
        await asyncio.sleep(1.0)

    monkeypatch.setattr(approval_service, "_resume_graph_impl", slow_impl)

    transport = ASGITransport(app=app)
    h = await _register(transport, "admin2")
    await _set_role(db_session, "admin2", "admin")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        t0 = time.monotonic()
        r = await c.post(f"/api/approvals/{ap_id}/decide", json={"approve": True}, headers=h)
        dt = time.monotonic() - t0
        assert r.status_code == 200
        assert dt < 0.5, f"decide 应立即返回（后台恢复），实际耗时 {dt:.2f}s"
    # 审批单状态已持久化（第二次点击应 404，但前端已收到反馈不会再点）
    ap = await db_session.get(Approval, ap_id)
    assert ap.status == "approved"
    # 等后台恢复任务自然结束，避免 pytest 事件循环残留 pending task
    await asyncio.sleep(1.2)


@pytest.mark.asyncio
async def test_list_shows_requester_and_approver_username(db_session):
    """审批列表展示发起人/审批人 username（而非不可读的 id）。"""
    transport = ASGITransport(app=app)
    h_req = await _register(transport, "requser")
    h_admin = await _register(transport, "admin3")
    await _set_role(db_session, "admin3", "admin")
    req = (await db_session.scalars(select(User).where(User.username == "requser"))).first()
    db_session.add(Approval(category="tool_call", risk="critical", mode="sync", ref_type="trace",
                            ref_id="t1", title="删除文件", status="pending",
                            requester_id=str(req.id), approver_role="admin"))
    await db_session.commit()
    ap_id = (await db_session.scalars(select(Approval).where(Approval.ref_id == "t1"))).first().id
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # 待审批：有发起人 username，无审批人
        r = await c.get("/api/approvals?status=pending", headers=h_admin)
        row = next(x for x in r.json() if x["id"] == ap_id)
        assert row["requester_name"] == "requser"
        assert row["approver_name"] is None
        # 通过后：展示审批人 username
        await c.post(f"/api/approvals/{ap_id}/decide", json={"approve": True, "comment": "ok"}, headers=h_admin)
        r = await c.get("/api/approvals?status=approved", headers=h_admin)
        row = next(x for x in r.json() if x["id"] == ap_id)
        assert row["approver_name"] == "admin3"
        assert row["requester_name"] == "requser"


@pytest.mark.asyncio
async def test_dept_owner_cannot_approve_other_dept(db_session):
    """dept_owner 只能审批本部门审批单：跨部门经验晋升返回 403。"""
    db_session.add(User(id="11111111-1111-1111-1111-111111111111", username="other", password_hash="x",
                        department_id="dept-9", display_name="Other"))
    db_session.add(Approval(category="experience_promotion", mode="async", ref_type="experience",
                            ref_id="e1", title="经验晋升", status="pending",
                            requester_id="11111111-1111-1111-1111-111111111111",
                            approver_role="dept_owner"))
    await db_session.commit()
    ap_id = (await db_session.scalars(select(Approval).where(Approval.ref_id == "e1"))).first().id
    transport = ASGITransport(app=app)
    h = await _register(transport, "owner2")
    await _set_role(db_session, "owner2", "dept_owner", department_id="dept-1")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # 列表也不可见跨部门待办
        r = await c.get("/api/approvals?status=pending", headers=h)
        assert r.json() == []
        # 直接审批跨部门单返回 403
        r = await c.post(f"/api/approvals/{ap_id}/decide", json={"approve": True}, headers=h)
        assert r.status_code == 403
