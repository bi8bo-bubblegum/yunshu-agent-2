"""端到端全链路冒烟测试。

覆盖：认证 → 会话 → SSE 聊天（含 high 风险即时确认）→ 消息/留痕/记忆沉淀
      → 知识库上传检索 → 经验提交与审批晋升 → 配置查询。

用法（backend 目录下）：
    E2E_BASE=http://localhost:8091 .venv/bin/python script/e2e_test.py
"""
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_ROOT)

# 必须在导入 app 之前把数据库指向 E2E 库,保证种子数据与后端实例写同一库
_env_url = ""
for line in (Path(_BACKEND_ROOT) / ".env").read_text(encoding="utf-8").splitlines():
    if line.startswith("DATABASE_URL="):
        _env_url = line.split("=", 1)[1].strip()
        break
_E2E_DB_URL = _env_url.rsplit("/", 1)[0] + "/yunshu_e2e"
os.environ["DATABASE_URL"] = _E2E_DB_URL

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.seed import seed_roles, seed_agent_mcp_bindings

BASE = os.environ.get("E2E_BASE", "http://localhost:8091")
DB_URL = settings.DATABASE_URL.replace("+asyncpg", "")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))


async def db_fetch(sql: str, *args):
    conn = await asyncpg_connect()
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def db_fetchval(sql: str, *args):
    conn = await asyncpg_connect()
    try:
        return await conn.fetchval(sql, *args)
    finally:
        await conn.close()


async def asyncpg_connect():
    import asyncpg
    return await asyncpg.connect(DB_URL)


async def chat_sse(client: httpx.AsyncClient, conv_id: str, message: str,
                   headers: dict) -> tuple[list[dict], str | None, dict | None]:
    """发送聊天消息，消费 SSE，自动处理一次 high 风险即时确认；
    返回 (事件列表, 最终内容, /chat/resume 响应体)。"""
    events: list[dict] = []
    async with client.stream(
        "POST", "/api/chat/completions",
        json={"conversation_id": conv_id, "message": message}, headers=headers, timeout=300,
    ) as resp:
        if resp.status_code != 200:
            body = (await resp.aread()).decode(errors="ignore")
            return [{"event": "http_error", "status": resp.status_code, "body": body[:500]}], None, None
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    # high 风险即时确认 → 恢复
    confirm = next((e for e in events if e.get("event") == "confirm_required"), None)
    if confirm:
        r = await client.post("/api/chat/resume",
                              json={"conversation_id": conv_id, "approved": True},
                              headers=headers, timeout=300)
        if r.status_code != 200:
            return events, f"resume failed: {r.status_code} {r.text[:300]}", None
        body = r.json()
        return events, body.get("content"), body
    token = next((e for e in events if e.get("event") == "token"), None)
    if token:
        return events, token.get("content"), None
    err = next((e for e in events if e.get("event") == "error"), None)
    if err:
        return events, f"error event: {err.get('content')}", None
    return events, None, None


async def main() -> int:
    print(f"== E2E 全链路测试 == base={BASE} db={DB_URL.split('@')[-1]}")

    # ---------- 0. 种子数据 ----------
    async with SessionLocal() as db:
        await seed_roles(db)
        await seed_agent_mcp_bindings(db)
    check("种子数据（角色/Agent MCP 绑定）", True)

    async with httpx.AsyncClient(base_url=BASE, timeout=60) as client:
        # ---------- 1. 注册 / 登录 ----------
        suffix = uuid.uuid4().hex[:6]
        admin_name, user_name = f"e2e_admin_{suffix}", f"e2e_user_{suffix}"
        for name, display in ((admin_name, "E2E管理员"), (user_name, "E2E用户")):
            r = await client.post("/api/auth/register",
                                  json={"username": name, "password": "Passw0rd!2026", "display_name": display})
            check(f"注册 {name}", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

        r = await client.post("/api/auth/login", json={"username": user_name, "password": "Passw0rd!2026"})
        user_token = r.json().get("access_token") if r.status_code == 200 else ""
        check("登录 user", bool(user_token), r.text[:200])
        r = await client.post("/api/auth/login", json={"username": admin_name, "password": "Passw0rd!2026"})
        admin_token = r.json().get("access_token") if r.status_code == 200 else ""
        check("登录 admin", bool(admin_token), r.text[:200])
        h_user, h_admin = {"Authorization": f"Bearer {user_token}"}, {"Authorization": f"Bearer {admin_token}"}

        r = await client.get("/api/auth/me", headers=h_user)
        me = r.json() if r.status_code == 200 else {}
        check("GET /auth/me", r.status_code == 200 and me.get("role_code") in (None, "member"), str(me)[:200])

        # 造一个部门，user 入部门；admin 提权
        r = await client.post("/api/departments", json={"name": f"E2E部门{suffix}"}, headers=h_admin)
        dept_id = r.json().get("id") if r.status_code == 200 else None
        check("创建部门", bool(dept_id), r.text[:200])
        await db_fetch("UPDATE users SET role_code='admin' WHERE username=$1", admin_name)
        await db_fetch("UPDATE users SET department_id=$1 WHERE username=$2", dept_id, user_name)
        r = await client.post("/api/auth/login", json={"username": admin_name, "password": "Passw0rd!2026"})
        admin_token = r.json().get("access_token", "")
        h_admin = {"Authorization": f"Bearer {admin_token}"}
        r = await client.get("/api/auth/me", headers=h_admin)
        check("admin 角色生效", r.json().get("role_code") == "admin", r.text[:200])
        r = await client.get("/api/auth/me", headers=h_user)
        check("user 部门生效", r.json().get("department_id") == dept_id, r.text[:200])

        # ---------- 2. 会话 ----------
        r = await client.post("/api/conversations", json={"title": "E2E国庆营销"}, headers=h_user)
        conv = r.json() if r.status_code == 200 else {}
        conv_id = conv.get("id")
        check("创建会话", bool(conv_id), r.text[:200])
        r = await client.get("/api/conversations", headers=h_user)
        check("会话列表", r.status_code == 200 and any(c.get("id") == conv_id for c in r.json()), "")

        # ---------- 3. 聊天（SSE + 可能的 high 风险确认） ----------
        events, final, resume_body = await chat_sse(client, conv_id,
                                                    "帮我策划一个国庆营销方案，先查一下现有营销活动，然后创建一个预算50000元的方案",
                                                    h_user)
        ev_names = [e.get("event") for e in events]
        check("聊天 SSE 有响应事件", len(events) > 0, str(ev_names)[:300])
        check("聊天无 error 事件", "error" not in ev_names, str(events)[:600])
        check("high 风险即时确认已触发", "confirm_required" in ev_names, str(ev_names)[:300])
        if "confirm_required" in ev_names:
            # 如果后续还有 critical 工具 → 进审批中心,由管理员审批后恢复图
            if resume_body and resume_body.get("ok") is False and resume_body.get("payload", {}).get("approval_id"):
                ap_id = resume_body["payload"]["approval_id"]
                check("critical 工具进入审批中心", bool(ap_id), str(resume_body)[:300])
                r = await client.post(f"/api/approvals/{ap_id}/decide",
                                      json={"approve": True, "comment": "e2e 通过"}, headers=h_admin, timeout=300)
                check("管理员审批 critical 通过", r.status_code == 200, r.text[:200])
                await asyncio.sleep(2.5)  # 等图恢复 + 消息落库
                r = await client.get(f"/api/conversations/{conv_id}/messages", headers=h_user)
                msgs = r.json()
                final = next((m.get("content") for m in reversed(msgs) if m.get("role") == "assistant"), None)
            elif resume_body:
                check("high 风险即时确认后恢复", resume_body.get("ok") is True, str(resume_body)[:300])
                final = final or resume_body.get("content")
        check("聊天产出最终内容", bool(final), str(final)[:400])

        # ---------- 4. 消息持久化 + 留痕 ----------
        await asyncio.sleep(2.5)  # 等 trace writer 批量落库
        r = await client.get(f"/api/conversations/{conv_id}/messages", headers=h_user)
        msgs = r.json() if r.status_code == 200 else []
        roles = [m.get("role") for m in msgs]
        check("消息落库（user+assistant）", r.status_code == 200 and "user" in roles and "assistant" in roles,
              str(roles)[:200])

        r = await client.get("/api/traces", headers=h_user)
        traces = r.json() if r.status_code == 200 else []
        trace = next((t for t in traces if t.get("conversation_id") == conv_id), None)
        check("执行留痕存在", bool(trace), str(traces)[:300])
        if trace:
            check("留痕状态 completed/interrupted", trace.get("status") in ("completed", "interrupted"),
                  trace.get("status"))
            r = await client.get(f"/api/traces/{trace['id']}/events", headers=h_user)
            events2 = r.json() if r.status_code == 200 else []
            types = [e.get("type") for e in events2]
            check("留痕事件非空", len(events2) > 0, str(types)[:300])
            check("留痕含 route/llm/tool 类事件", any(t in types for t in ("route", "llm", "tool")), str(types)[:300])

        # ---------- 5. 记忆沉淀（偏好 + 经验自动提炼） ----------
        user_row_id = await db_fetchval("SELECT id FROM users WHERE username=$1", user_name)
        prefs = await db_fetch("SELECT category, content FROM preferences WHERE user_id=$1", str(user_row_id))
        check("偏好提取落库", len(prefs) > 0, str([dict(p) for p in prefs])[:300])
        r = await client.get("/api/experiences", headers=h_user)
        exps = r.json() if r.status_code == 200 else []
        check("经验中心可见个人经验", len(exps) > 0, str(exps)[:300])

        # ---------- 6. 知识库：上传 + 列表 + 检索 ----------
        tmp_doc = f"/tmp/e2e_{uuid.uuid4().hex}.md"
        with open(tmp_doc, "w", encoding="utf-8") as f:
            f.write("# 国庆营销手册\n\n国庆大促采用全渠道投放，预算 50000 元，重点渠道：社交媒体与短信。\n"
                    "ROI 目标 3.0，往年 10 月同期 GMV 环比提升 25%。\n")
        with open(tmp_doc, "rb") as f:
            r = await client.post("/api/documents", files={"file": ("guoqing.md", f, "text/markdown")}, headers=h_user)
        check("文档上传", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
        r = await client.get("/api/documents", headers=h_user)
        docs = r.json() if r.status_code == 200 else []
        doc = next((d for d in docs if d.get("title") == "guoqing.md"), None)
        check("文档列表含新文档", bool(doc), str(docs)[:300])
        if doc:
            check("文档解析状态 ready", doc.get("status") == "ready", str(doc)[:200])
        r = await client.post("/api/kb/search", json={"query": "国庆营销预算与渠道", "top_k": 3}, headers=h_user)
        hits = (r.json() or {}).get("results", []) if r.status_code == 200 else []
        check("知识库检索有命中", r.status_code == 200 and len(hits) > 0, str(hits)[:300])
        if doc:
            r = await client.delete(f"/api/documents/{doc['id']}", headers=h_user)
            check("删除文档", r.status_code == 200, r.text[:200])
        os.remove(tmp_doc)

        # ---------- 7. 经验提交 → 审批 → 晋升 ----------
        if exps:
            exp = exps[0]
            r = await client.post(f"/api/experiences/{exp['id']}/submit",
                                  json={"to_scope": "dept"}, headers=h_user)
            check("经验提交审批", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
            r = await client.get("/api/approvals", params={"status": "pending"}, headers=h_admin)
            approvals = r.json() if r.status_code == 200 else []
            ap = next((a for a in approvals if a.get("category") == "experience_promotion"), None)
            check("管理员可见经验晋升审批单", bool(ap), str(approvals)[:300])
            if ap:
                r = await client.post(f"/api/approvals/{ap['id']}/decide",
                                      json={"approve": True, "comment": "e2e 通过"}, headers=h_admin, timeout=120)
                check("审批通过", r.status_code == 200, r.text[:200])
                scope = await db_fetchval("SELECT scope FROM experiences WHERE id=$1", exp["id"])
                check("经验晋升为 dept 层", scope == "dept", f"scope={scope}")
        else:
            check("经验提交→审批→晋升（无经验可提交，跳过）", True, "skip")

        # ---------- 8. 配置中心 ----------
        r = await client.get("/api/agents", headers=h_admin)
        agents = r.json() if r.status_code == 200 else []
        check("Agent 列表", len(agents) >= 3, str(agents)[:200])
        r = await client.get("/api/mcp-servers", headers=h_admin)
        check("MCP 服务列表可查", r.status_code == 200, r.text[:200])
        r = await client.get("/api/agents/marketing/mcp-bindings", headers=h_admin)
        check("Agent MCP 绑定可查", r.status_code == 200, r.text[:300])
        r = await client.get("/api/departments", headers=h_user)
        check("部门列表可查", r.status_code == 200, r.text[:200])
        r = await client.get("/api/users", headers=h_admin)
        check("用户列表可查", r.status_code == 200, r.text[:200])

    # ---------- 汇总 ----------
    failed = [r for r in results if not r[1]]
    print(f"\n== 汇总：{len(results) - len(failed)}/{len(results)} 通过 ==")
    for name, ok, detail in failed:
        print(f"  FAIL: {name} | {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
