# backend/tests/test_approvals_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.main import app
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
