# backend/tests/test_approval_gateway.py
"""M4 审批网关：推送钉钉 OA + bpms_instance_change 事件回写 + URL 回填。

用 MockTransport 拦截钉钉接口（token / 发起实例 / 实例详情），全程不触网。
覆盖：
- push_approval_to_dingtalk：成功建绑定（请求体正确）/ 未配置 400 / 发起人未绑定 400 / 钉钉错误 502
- handle_approval_instance_change：finish agree/refuse、terminate/delete 视为驳回、start 不改状态、
  幂等（重复事件跳过）、未知实例/未知 type 忽略
- apply_decision 分发：tool_call 后台恢复图 / experience_promotion 晋升与驳回恢复
- _enrich_binding_urls：后台回填「去钉钉处理」跳转 URL
"""
import json
import uuid

import pytest
from fastapi import HTTPException
from httpx import MockTransport, Response
from sqlalchemy import select

from app.core.config import settings
from app.models.dingtalk import ApprovalBinding
from app.models.experience import Experience
from app.models.org import Department, User
from app.models.trace import Approval
from app.services.dingtalk.approval_gateway import (
    _enrich_binding_urls, build_form_values, handle_approval_instance_change,
    push_approval_to_dingtalk,
)
from app.services.dingtalk.client import DingTalkClient


def _dingtalk_handler(instance_id="inst_001", create_error=None):
    """Mock 钉钉审批接口：token / 发起实例(POST) / 实例详情(GET)，并捕获请求体。"""
    seen = {"create_body": None, "create_calls": 0, "get_calls": 0}

    def handler(request):
        path = request.url.path
        if path == "/v1.0/oauth2/accessToken":
            return Response(200, json={"accessToken": "T", "expireIn": 7200})
        if path == "/v1.0/workflow/processInstances":
            if request.method == "POST":
                seen["create_calls"] += 1
                seen["create_body"] = json.loads(request.content or b"{}")
                if create_error:
                    return Response(400, json={"code": create_error, "message": "审批模板不存在"})
                return Response(200, json={"instanceId": instance_id})
            seen["get_calls"] += 1
            return Response(200, json={"result": {
                "status": "COMPLETED", "result": "agree",
                "tasks": [{"userId": "approver1", "mobileUrl": "https://m.test",
                           "pcUrl": "https://p.test"}]}})
        return Response(404, json={})
    return handler, seen


@pytest.fixture
def enable_dingtalk(monkeypatch):
    """启用钉钉审批配置（凭证 + 审批模板编码 + agentId）；client 由各用例注入 MockTransport 版本。"""
    monkeypatch.setattr(settings, "DINGTALK_CLIENT_ID", "test-app-key")
    monkeypatch.setattr(settings, "DINGTALK_CLIENT_SECRET", "test-app-secret")
    monkeypatch.setattr(settings, "DINGTALK_AGENT_ID", "123456")
    monkeypatch.setattr(settings, "DINGTALK_OA_PROCESS_CODES",
                        {"tool_call": "PROC_TOOL", "experience_promotion": "PROC_EXP"})
    return monkeypatch


def _use_client(monkeypatch, handler) -> None:
    """把审批网关使用的 dingtalk_client 换成 MockTransport 版本（避免真实网络请求）。"""
    client = DingTalkClient(client_id="test-app-key", client_secret="test-app-secret",
                            transport=MockTransport(handler))
    monkeypatch.setattr("app.services.dingtalk.approval_gateway.dingtalk_client", client)


async def _make_context(db_session, category="tool_call", with_dept=True, requester_dingtalk="ding_owner"):
    """预置发起人（钉钉 userid）+ 部门（钉钉 dept_id）+ 待审批单（+经验晋升用 Experience 行）。"""
    dept_id = str(uuid.uuid4())
    if with_dept:
        db_session.add(Department(id=dept_id, name="市场部", dingtalk_dept_id=1001))
    user = User(username="owner", password_hash="!", display_name="负责人",
                dingtalk_userid=requester_dingtalk, source="dingtalk", status="active",
                department_id=dept_id if with_dept else None)
    db_session.add(user)
    await db_session.commit()
    if category == "experience_promotion":
        exp_id = str(uuid.uuid4())
        db_session.add(Experience(id=exp_id, owner_id=str(user.id), scope="personal",
                                  status="pending", title="晋升经验", summary="s"))
        ref_id, context = exp_id, {"experience_id": exp_id, "from_scope": "personal", "to_scope": "dept"}
    else:
        ref_id, context = "tr-1", {"tool": "x", "args": {"id": 1}}
    ap = Approval(category=category, risk="critical" if category == "tool_call" else None,
                  mode="sync" if category == "tool_call" else "async",
                  ref_type="trace", ref_id=ref_id, title="测试审批",
                  context=context, status="pending", requester_id=str(user.id),
                  approver_role="admin")
    db_session.add(ap)
    await db_session.commit()
    return ap


async def _add_binding(db_session, approval_id, pid="inst_001"):
    db_session.add(ApprovalBinding(approval_id=approval_id, process_code="PROC_TOOL",
                                   process_instance_id=pid, status="pushed"))
    await db_session.commit()


# ---------------------------------------------------------------------------
# 推送：push_approval_to_dingtalk
# ---------------------------------------------------------------------------

async def test_push_success_creates_binding(monkeypatch, enable_dingtalk, db_session):
    """推送成功：请求体（发起人/模板/deptId/表单/agentId）正确 + binding 落库。"""
    handler, seen = _dingtalk_handler()
    _use_client(monkeypatch, handler)
    ap = await _make_context(db_session)
    binding = await push_approval_to_dingtalk(db_session, ap)
    await db_session.commit()
    assert binding.process_instance_id == "inst_001"
    assert binding.status == "pushed"
    assert binding.process_code == "PROC_TOOL"
    body = seen["create_body"]
    assert body["originatorUserId"] == "ding_owner"
    assert body["processCode"] == "PROC_TOOL"
    assert body["deptId"] == 1001
    assert body["microappAgentId"] == 123456
    names = [v["name"] for v in body["formComponentValues"]]
    assert names == ["审批标题", "审批详情"]
    # 落库可反查
    row = (await db_session.scalars(
        select(ApprovalBinding).where(ApprovalBinding.approval_id == ap.id))).first()
    assert row and row.process_instance_id == "inst_001"


async def test_push_missing_config_raises_400(db_session):
    """钉钉未配置（无凭证/无模板编码）：全走钉钉策略 → 400，不落任何单。"""
    ap = await _make_context(db_session)
    with pytest.raises(HTTPException) as ei:
        await push_approval_to_dingtalk(db_session, ap)
    assert ei.value.status_code == 400
    assert "未配置" in ei.value.detail


async def test_push_requester_not_bound_raises_400(enable_dingtalk, db_session):
    """发起人未绑定钉钉账号（dingtalk_userid 为空）→ 400。"""
    ap = await _make_context(db_session, requester_dingtalk=None)
    with pytest.raises(HTTPException) as ei:
        await push_approval_to_dingtalk(db_session, ap)
    assert ei.value.status_code == 400
    assert "未绑定" in ei.value.detail


async def test_push_dingtalk_error_raises_502(monkeypatch, enable_dingtalk, db_session):
    """钉钉接口错误（processCodeError）→ 502，携带业务可读提示。"""
    handler, _ = _dingtalk_handler(create_error="processCodeError")
    _use_client(monkeypatch, handler)
    ap = await _make_context(db_session)
    with pytest.raises(HTTPException) as ei:
        await push_approval_to_dingtalk(db_session, ap)
    assert ei.value.status_code == 502
    assert "审批模板不存在" in ei.value.detail


async def test_build_form_values_contains_controls(db_session):
    """表单映射：标题 TextField + 详情 TextareaField（context 序列化 JSON）。"""
    ap = await _make_context(db_session)
    vals = build_form_values(ap)
    assert vals[0] == {"name": "审批标题", "value": "测试审批", "componentType": "TextField"}
    assert vals[1]["name"] == "审批详情" and vals[1]["componentType"] == "TextareaField"
    assert "tool" in json.loads(vals[1]["value"])


# ---------------------------------------------------------------------------
# 事件回写：handle_approval_instance_change
# ---------------------------------------------------------------------------

async def test_event_finish_agree_tool_call_resumes(monkeypatch, db_session):
    """finish-agree（tool_call）：状态 approved + 审批人反查 + binding synced + 后台恢复图被调。"""
    calls = []

    async def fake_resume(approval_id, approved, trace_id):
        calls.append((approval_id, approved, trace_id))

    monkeypatch.setattr("app.services.approval_service._resume_graph_in_background", fake_resume)
    approver = User(username="approver", password_hash="!", display_name="审批人",
                    dingtalk_userid="ding_approver", source="dingtalk", status="active")
    db_session.add(approver)
    await db_session.commit()
    ap = await _make_context(db_session)
    await _add_binding(db_session, ap.id)
    await handle_approval_instance_change({"processInstanceId": "inst_001", "type": "finish",
                                           "result": "agree", "staffId": "ding_approver"})
    # expire 前捕获主键（expire_all 后同步访问属性会触发过期懒加载 → MissingGreenlet）
    ap_id, approver_id = ap.id, str(approver.id)
    db_session.expire_all()
    ap2 = await db_session.get(Approval, ap_id)
    assert ap2.status == "approved"
    assert ap2.approver_id == approver_id
    binding = (await db_session.scalars(
        select(ApprovalBinding).where(ApprovalBinding.approval_id == ap_id))).first()
    assert binding.status == "synced"
    assert calls == [(ap_id, True, "tr-1")]


async def test_event_finish_refuse_experience_restores_draft(db_session):
    """finish-refuse（experience_promotion）：状态 rejected + 经验恢复 personal/draft。"""
    ap = await _make_context(db_session, category="experience_promotion")
    await _add_binding(db_session, ap.id)
    await handle_approval_instance_change({"processInstanceId": "inst_001", "type": "finish",
                                           "result": "refuse", "staffId": "ding_approver"})
    ap_id, exp_id = ap.id, ap.ref_id
    db_session.expire_all()
    ap2 = await db_session.get(Approval, ap_id)
    assert ap2.status == "rejected"
    exp = await db_session.get(Experience, exp_id)
    assert exp.status == "draft" and exp.scope == "personal"


async def test_event_finish_agree_experience_promotes(db_session):
    """finish-agree（experience_promotion）：经验晋升到目标层级。"""
    ap = await _make_context(db_session, category="experience_promotion")
    await _add_binding(db_session, ap.id)
    await handle_approval_instance_change({"processInstanceId": "inst_001", "type": "finish",
                                           "result": "agree", "staffId": "ding_approver"})
    exp_id = ap.ref_id
    db_session.expire_all()
    exp = await db_session.get(Experience, exp_id)
    assert exp.status == "approved" and exp.scope == "dept"


async def test_event_terminate_treated_as_reject(db_session):
    """钉钉侧终止（terminate）：视为驳回，comment 标注「已终止」。"""
    ap = await _make_context(db_session, category="experience_promotion")
    await _add_binding(db_session, ap.id)
    await handle_approval_instance_change({"processInstanceId": "inst_001", "type": "terminate"})
    ap_id = ap.id
    db_session.expire_all()
    ap2 = await db_session.get(Approval, ap_id)
    assert ap2.status == "rejected"
    assert "已终止" in (ap2.comment or "")
    binding = (await db_session.scalars(
        select(ApprovalBinding).where(ApprovalBinding.approval_id == ap_id))).first()
    assert binding.status == "synced"


async def test_event_delete_treated_as_reject(db_session):
    """钉钉侧删除实例（delete）：视为驳回，comment 标注「已删除」。"""
    ap = await _make_context(db_session, category="experience_promotion")
    await _add_binding(db_session, ap.id)
    await handle_approval_instance_change({"processInstanceId": "inst_001", "type": "delete"})
    ap_id = ap.id
    db_session.expire_all()
    ap2 = await db_session.get(Approval, ap_id)
    assert ap2.status == "rejected"
    assert "已删除" in (ap2.comment or "")
    binding = (await db_session.scalars(
        select(ApprovalBinding).where(ApprovalBinding.approval_id == ap_id))).first()
    assert binding.status == "synced"


async def test_event_unknown_type_ignored(db_session):
    """未知 type：不落任何决定（状态仍 pending，binding 不置 synced），避免误恢复图。"""
    ap = await _make_context(db_session, category="experience_promotion")
    await _add_binding(db_session, ap.id)
    await handle_approval_instance_change({"processInstanceId": "inst_001", "type": "weird"})
    ap_id = ap.id
    db_session.expire_all()
    ap2 = await db_session.get(Approval, ap_id)
    assert ap2.status == "pending"
    binding = (await db_session.scalars(
        select(ApprovalBinding).where(ApprovalBinding.approval_id == ap_id))).first()
    assert binding.status == "pushed"


async def test_event_start_no_status_change(db_session):
    """start 事件：不改审批单状态（仍 pending），binding 不置 synced。"""
    ap = await _make_context(db_session, category="experience_promotion")
    await _add_binding(db_session, ap.id)
    await handle_approval_instance_change({"processInstanceId": "inst_001", "type": "start"})
    ap_id = ap.id
    db_session.expire_all()
    ap2 = await db_session.get(Approval, ap_id)
    assert ap2.status == "pending"
    binding = (await db_session.scalars(
        select(ApprovalBinding).where(ApprovalBinding.approval_id == ap_id))).first()
    assert binding.status == "pushed"


async def test_event_idempotent_second_finish_ignored(db_session):
    """幂等：重复 finish 事件第二次跳过（status!=pending 返回 False，不报错）。"""
    ap = await _make_context(db_session, category="experience_promotion")
    await _add_binding(db_session, ap.id)
    for _ in range(2):
        await handle_approval_instance_change({"processInstanceId": "inst_001", "type": "finish",
                                               "result": "agree", "staffId": "ding_approver"})
    ap_id = ap.id
    db_session.expire_all()
    ap2 = await db_session.get(Approval, ap_id)
    assert ap2.status == "approved"


async def test_event_unknown_instance_ignored(db_session):
    """未知 processInstanceId：忽略不报错，库中无变化。"""
    ap = await _make_context(db_session, category="experience_promotion")
    await handle_approval_instance_change({"processInstanceId": "inst_unknown", "type": "finish",
                                           "result": "agree", "staffId": "ding_approver"})
    ap_id = ap.id
    db_session.expire_all()
    ap2 = await db_session.get(Approval, ap_id)
    assert ap2.status == "pending"


# ---------------------------------------------------------------------------
# URL 回填
# ---------------------------------------------------------------------------

async def test_enrich_binding_urls_backfills(monkeypatch, enable_dingtalk, db_session):
    """后台回填：拉实例详情填 mobile_url/pc_url（「去钉钉处理」跳转地址）。"""
    handler, seen = _dingtalk_handler()
    _use_client(monkeypatch, handler)
    ap = await _make_context(db_session)
    await _add_binding(db_session, ap.id)
    await _enrich_binding_urls("inst_001")
    ap_id = ap.id
    db_session.expire_all()
    binding = (await db_session.scalars(
        select(ApprovalBinding).where(ApprovalBinding.approval_id == ap_id))).first()
    assert binding.mobile_url == "https://m.test"
    assert binding.pc_url == "https://p.test"
    assert seen["get_calls"] == 1
