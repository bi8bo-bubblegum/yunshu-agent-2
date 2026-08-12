# backend/tests/test_experiences_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_submit_experience_for_approval(monkeypatch, db_session):
    # create 内部 embed_texts 调用真实 embedding API，测试中 stub 掉
    async def fake_embed(texts):
        return [[0.1] * 1536] * len(texts)
    monkeypatch.setattr("app.services.experience_service.embed_texts", fake_embed)
    from sqlalchemy import update
    from app.models.org import User
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "gary", "password": "x123456", "display_name": "Gary"})
        r = await c.post("/api/auth/login", json={"username": "gary", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        # 晋升部门层需要所属部门：给 gary 挂部门
        await db_session.execute(update(User).where(User.username == "gary").values(department_id="dept-1"))
        await db_session.commit()
        r = await c.post("/api/experiences", json={
            "title": "国庆大促", "summary": "满减+直播", "content": "详情",
            "tags": ["营销"], "event_time": "2025-10-01", "result_metrics": {"gmv": 320},
        }, headers=h)
        assert r.status_code == 200
        exp_id = r.json()["id"]
        r = await c.post(f"/api/experiences/{exp_id}/submit", json={"to_scope": "dept"}, headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_delete_experience(monkeypatch):
    async def fake_embed(texts):
        return [[0.1] * 1536] * len(texts)
    monkeypatch.setattr("app.services.experience_service.embed_texts", fake_embed)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for u in ("owner", "other", "boss"):
            await c.post("/api/auth/register", json={"username": u, "password": "x123456", "display_name": u})
        r = await c.post("/api/auth/login", json={"username": "owner", "password": "x123456"})
        h_owner = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/auth/login", json={"username": "other", "password": "x123456"})
        h_other = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/auth/login", json={"username": "boss", "password": "x123456"})
        h_boss = {"Authorization": f"Bearer {r.json()['access_token']}"}

        exp_id = (await c.post("/api/experiences", json={
            "title": "待删除经验", "summary": "s", "content": "c",
        }, headers=h_owner)).json()["id"]

        # 他人删除 → 403
        assert (await c.delete(f"/api/experiences/{exp_id}", headers=h_other)).status_code == 403
        # 作者本人删除 → 200 且列表不再出现
        assert (await c.delete(f"/api/experiences/{exp_id}", headers=h_owner)).status_code == 200
        assert exp_id not in [x["id"] for x in (await c.get("/api/experiences", headers=h_owner)).json()]
        # 重复删除 → 404
        assert (await c.delete(f"/api/experiences/{exp_id}", headers=h_owner)).status_code == 404

        # admin 可删除他人经验
        from sqlalchemy import update
        from app.models.org import User
        from app.core.database import SessionLocal
        async with SessionLocal() as db:
            await db.execute(update(User).where(User.username == "boss").values(role_code="admin"))
            await db.commit()
        exp2 = (await c.post("/api/experiences", json={
            "title": "admin删", "summary": "s", "content": "c",
        }, headers=h_owner)).json()["id"]
        assert (await c.delete(f"/api/experiences/{exp2}", headers=h_boss)).status_code == 200


@pytest.mark.asyncio
async def test_experience_detail_visibility(monkeypatch):
    async def fake_embed(texts):
        return [[0.1] * 1536] * len(texts)
    monkeypatch.setattr("app.services.experience_service.embed_texts", fake_embed)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "d_owner", "password": "x123456", "display_name": "O"})
        await c.post("/api/auth/register", json={"username": "d_other", "password": "x123456", "display_name": "X"})
        r = await c.post("/api/auth/login", json={"username": "d_owner", "password": "x123456"})
        h_owner = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/auth/login", json={"username": "d_other", "password": "x123456"})
        h_other = {"Authorization": f"Bearer {r.json()['access_token']}"}

        exp = (await c.post("/api/experiences", json={
            "title": "详情经验", "summary": "摘要", "content": "完整内容",
            "tags": ["营销"], "event_time": "2025-10-01", "result_metrics": {"gmv": 320},
        }, headers=h_owner)).json()
        exp_id = exp["id"]

        # 本人可见详情，含全部内容字段
        r = await c.get(f"/api/experiences/{exp_id}", headers=h_owner)
        assert r.status_code == 200
        detail = r.json()
        assert detail["content"] == "完整内容"
        assert detail["tags"] == ["营销"]
        assert detail["event_time"] == "2025-10-01"
        assert detail["result_metrics"] == {"gmv": 320}

        # 他人（个人层经验）不可见 → 404
        assert (await c.get(f"/api/experiences/{exp_id}", headers=h_other)).status_code == 404
        # 不存在 → 404
        assert (await c.get("/api/experiences/no-such-id", headers=h_owner)).status_code == 404


@pytest.mark.asyncio
async def test_update_experience_metrics(monkeypatch):
    """编辑经验的活动时间与效果指标：作者本人可改，他人 403，admin 可改他人。
    真实场景：上传/自动沉淀的经验 event_time/result_metrics 常缺失或需修正。"""
    async def fake_embed(texts):
        return [[0.1] * 1536] * len(texts)
    monkeypatch.setattr("app.services.experience_service.embed_texts", fake_embed)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for u in ("m_owner", "m_other", "m_boss"):
            await c.post("/api/auth/register", json={"username": u, "password": "x123456", "display_name": u})
        r = await c.post("/api/auth/login", json={"username": "m_owner", "password": "x123456"})
        h_owner = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/auth/login", json={"username": "m_other", "password": "x123456"})
        h_other = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/auth/login", json={"username": "m_boss", "password": "x123456"})
        h_boss = {"Authorization": f"Bearer {r.json()['access_token']}"}

        exp_id = (await c.post("/api/experiences", json={
            "title": "可编辑经验", "summary": "s", "content": "c",
        }, headers=h_owner)).json()["id"]

        # 他人编辑 → 403
        r = await c.put(f"/api/experiences/{exp_id}/metrics",
                        json={"event_time": "2025-01-01", "result_metrics": {"gmv": 1}},
                        headers=h_other)
        assert r.status_code == 403

        # 作者本人编辑 event_time + result_metrics → 200，字段更新
        r = await c.put(f"/api/experiences/{exp_id}/metrics",
                        json={"event_time": "2025-11-11", "result_metrics": {"gmv": 320, "roi": 5}},
                        headers=h_owner)
        assert r.status_code == 200, r.text
        assert r.json()["event_time"] == "2025-11-11"
        assert r.json()["result_metrics"] == {"gmv": 320, "roi": 5}

        # 清空 event_time / result_metrics（null）→ 置空
        r = await c.put(f"/api/experiences/{exp_id}/metrics",
                        json={"event_time": None, "result_metrics": None},
                        headers=h_owner)
        assert r.status_code == 200
        assert r.json()["event_time"] is None
        assert r.json()["result_metrics"] is None

        # admin 可编辑他人经验
        from sqlalchemy import update
        from app.models.org import User
        from app.core.database import SessionLocal
        async with SessionLocal() as db:
            await db.execute(update(User).where(User.username == "m_boss").values(role_code="admin"))
            await db.commit()
        r = await c.put(f"/api/experiences/{exp_id}/metrics",
                        json={"event_time": "2025-12-01", "result_metrics": {"roi": 8}},
                        headers=h_boss)
        assert r.status_code == 200
        assert r.json()["event_time"] == "2025-12-01"

        # 不存在 → 404
        r = await c.put("/api/experiences/no-such-id/metrics",
                        json={"event_time": None, "result_metrics": None},
                        headers=h_owner)
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_submit_dept_requires_department(monkeypatch):
    """无部门的用户晋升部门层 → 400；晋升公司层 → 200（admin 审批）。

    真实事故：无部门用户晋升 dept 成功，但经验无 department_id，同部门成员不可见，
    相当于没晋升。无部门的用户只能晋升公司层。"""
    async def fake_embed(texts):
        return [[0.1] * 1536] * len(texts)
    monkeypatch.setattr("app.services.experience_service.embed_texts", fake_embed)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "nd_owner", "password": "x123456", "display_name": "N"})
        r = await c.post("/api/auth/login", json={"username": "nd_owner", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        exp_id = (await c.post("/api/experiences", json={"title": "无部门晋升", "summary": "s"},
                               headers=h)).json()["id"]
        # 无部门 → 晋升部门层被拒
        assert (await c.post(f"/api/experiences/{exp_id}/submit", json={"to_scope": "dept"},
                             headers=h)).status_code == 400
        # 无部门 → 可晋升公司层
        r = await c.post(f"/api/experiences/{exp_id}/submit", json={"to_scope": "company"}, headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_promote_dept_experience_to_company(monkeypatch, db_session):
    """部门层已通过的经验可继续晋升公司层；company 层不可再晋升。

    真实事故：晋升到部门后无继续晋升企业的入口。"""
    async def fake_embed(texts):
        return [[0.1] * 1536] * len(texts)
    monkeypatch.setattr("app.services.experience_service.embed_texts", fake_embed)
    from sqlalchemy import update
    from app.models.org import User
    from app.models.experience import Experience
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "pc_owner", "password": "x123456", "display_name": "P"})
        r = await c.post("/api/auth/login", json={"username": "pc_owner", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        await db_session.execute(update(User).where(User.username == "pc_owner").values(department_id="dept-1"))
        await db_session.commit()
        exp_id = (await c.post("/api/experiences", json={"title": "逐级晋升", "summary": "s"},
                               headers=h)).json()["id"]
        # 模拟部门层审批已通过
        exp = await db_session.get(Experience, exp_id)
        exp.scope, exp.status = "dept", "approved"
        await db_session.commit()
        # 部门层经验 → 继续晋升公司层
        r = await c.post(f"/api/experiences/{exp_id}/submit", json={"to_scope": "company"}, headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "pending"
        # company 层不可再晋升
        exp = await db_session.get(Experience, exp_id)
        exp.scope, exp.status = "company", "approved"
        await db_session.commit()
        assert (await c.post(f"/api/experiences/{exp_id}/submit", json={"to_scope": "company"},
                             headers=h)).status_code == 400
