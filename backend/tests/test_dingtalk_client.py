# backend/tests/test_dingtalk_client.py
"""DingTalkClient 单测：token 缓存 / 并发互斥 / 过期刷新 / 新旧接口封装 / 错误映射。

全部用 httpx.MockTransport 拦截请求，不触网。
"""
import asyncio
import json

import pytest
from httpx import MockTransport, Response

from app.services.dingtalk.client import DingTalkClient, DingTalkError


def build_client(responses: dict, counter: dict | None = None) -> DingTalkClient:
    """按 URL path 分发响应的 MockTransport，构造 DingTalkClient。

    responses: {path 前缀: httpx.Response}
    counter: 可选 dict，记录 {path: 命中次数}（token 端点计数用于缓存断言）。
    """
    def handler(request):
        if counter is not None:
            counter[request.url.path] = counter.get(request.url.path, 0) + 1
        for path, resp in responses.items():
            if request.url.path.startswith(path):
                return resp
        return Response(404, json={})

    return DingTalkClient(client_id="testkey", client_secret="testsecret",
                          transport=MockTransport(handler))


# accessToken 端点响应（多数用例的前置：其他接口请求前需先取 token）
TOKEN_RESP = {"/v1.0/oauth2/accessToken": Response(200, json={"accessToken": "TOKEN_1", "expireIn": 7200})}


# ---------------------------------------------------------------------------
# token 缓存与刷新
# ---------------------------------------------------------------------------

async def test_access_token_cached():
    """同进程内重复获取只请求一次钉钉接口（缓存生效）。"""
    counter = {}
    client = build_client(TOKEN_RESP, counter)
    assert await client.get_access_token() == "TOKEN_1"
    assert await client.get_access_token() == "TOKEN_1"
    assert counter["/v1.0/oauth2/accessToken"] == 1


async def test_access_token_expire_refetch():
    """token 过期后重新获取（强制把过期时间拨到过去）。"""
    counter = {}
    client = build_client(TOKEN_RESP, counter)
    await client.get_access_token()
    client._token_expire_at = 0  # 强制过期
    assert await client.get_access_token() == "TOKEN_1"
    assert counter["/v1.0/oauth2/accessToken"] == 2


async def test_access_token_concurrent_single_fetch():
    """并发 10 个协程同时取 token：互斥锁保证只刷新一次。"""
    counter = {}
    client = build_client(TOKEN_RESP, counter)
    tokens = await asyncio.gather(*[client.get_access_token() for _ in range(10)])
    assert all(t == "TOKEN_1" for t in tokens)
    assert counter["/v1.0/oauth2/accessToken"] == 1


async def test_jsapi_ticket_cached():
    """jsapiTicket 独立缓存，不重复请求。"""
    counter = {}
    client = build_client({**TOKEN_RESP,
                           "/v1.0/oauth2/jsapiTickets": Response(200, json={"jsapiTicket": "JT_1", "expireIn": 7200})},
                          counter)
    assert await client.get_jsapi_ticket() == "JT_1"
    assert await client.get_jsapi_ticket() == "JT_1"
    assert counter["/v1.0/oauth2/jsapiTickets"] == 1


# ---------------------------------------------------------------------------
# 新旧接口封装
# ---------------------------------------------------------------------------

async def test_new_api_uses_auth_header():
    """新版接口带 x-acs-dingtalk-access-token 请求头。"""
    seen = {}

    def handler(request):
        if request.url.path == "/v1.0/oauth2/accessToken":
            return Response(200, json={"accessToken": "HEADER_TOKEN", "expireIn": 7200})
        seen["auth_header"] = request.headers.get("x-acs-dingtalk-access-token")
        return Response(200, json={"ok": True})

    client = DingTalkClient(client_id="k", client_secret="s", transport=MockTransport(handler))
    await client._get_new("/v1.0/test/business")
    assert seen["auth_header"] == "HEADER_TOKEN"


async def test_oapi_success_and_result_extract():
    """旧版接口：access_token 走 query 参数、errcode==0 成功并提取 result。"""
    def handler(request):
        if request.url.path == "/v1.0/oauth2/accessToken":
            return Response(200, json={"accessToken": "OAPI_TOKEN", "expireIn": 7200})
        assert request.url.params.get("access_token") == "OAPI_TOKEN"
        if request.url.path == "/topapi/v2/user/getuserinfo":
            return Response(200, json={"errcode": 0, "result": {"userid": "user_001", "unionid": "uuu"}})
        return Response(200, json={"errcode": 1, "errmsg": "boom"})

    client = DingTalkClient(client_id="k", client_secret="s", transport=MockTransport(handler))
    info = await client.get_userinfo_by_code("authcode_abc")
    assert info["userid"] == "user_001"


async def test_get_user_by_unionid():
    """按 unionid 换 userid：成功取 result.userid。"""
    client = build_client({
        "/v1.0/oauth2/accessToken": Response(200, json={"accessToken": "T", "expireIn": 7200}),
        "/topapi/user/getbyunionid": Response(200, json={"errcode": 0, "result": {"userid": "u_by_union"}}),
    })
    assert await client.get_user_by_unionid("union_xxx") == "u_by_union"


async def test_get_sns_userinfo_bycode_oauth2_flow():
    """扫码登录（新版 OAuth2）：authorization_code 换用户 token → /v1.0/contact/users/me 拿 unionId。

    防止再退回到旧版 sns/getuserinfo_bycode（企业内部应用凭证签名 853004 失败）或误用
    不存在的 /oauth2/oauth2token 接口。"""
    seen = {}

    def handler(request):
        path = request.url.path
        if path == "/v1.0/oauth2/userAccessToken":
            seen["token_body"] = json.loads(request.content or b"{}")
            return Response(200, json={"accessToken": "USER_T", "expireIn": 7200})
        if path == "/v1.0/contact/users/me":
            seen["user_header"] = request.headers.get("x-acs-dingtalk-access-token")
            return Response(200, json={"unionId": "union_xxx", "nick": "张三"})
        return Response(404, json={})

    client = DingTalkClient(client_id="k", client_secret="s", transport=MockTransport(handler))
    info = await client.get_sns_userinfo_bycode("tmp_code_abc")
    assert info["unionId"] == "union_xxx"
    # 换 token 请求体：clientId/clientSecret/code/grantType=authorization_code
    assert seen["token_body"] == {
        "clientId": "k", "clientSecret": "s",
        "code": "tmp_code_abc", "grantType": "authorization_code",
    }
    # 用户信息接口必须带用户 token 请求头
    assert seen["user_header"] == "USER_T"


# ---------------------------------------------------------------------------
# 错误映射
# ---------------------------------------------------------------------------

async def test_error_mapping_no_permission():
    """60011 无权限 → 业务可读错误信息。"""
    client = build_client({**TOKEN_RESP,
                           "/v1.0/test": Response(400, json={"code": "60011", "message": "no permission"})})
    with pytest.raises(DingTalkError) as ei:
        await client._get_new("/v1.0/test")
    assert "无权限" in str(ei.value)
    assert ei.value.code == "60011"


async def test_error_40001_resets_token_and_refetch():
    """40001 token 失效 → 清缓存，下一次调用自动重取 token。"""
    counter = {}

    def handler(request):
        counter[request.url.path] = counter.get(request.url.path, 0) + 1
        if request.url.path == "/v1.0/oauth2/accessToken":
            return Response(200, json={"accessToken": "T", "expireIn": 7200})
        return Response(400, json={"code": "40001", "message": "token expired"})

    client = DingTalkClient(client_id="k", client_secret="s", transport=MockTransport(handler))
    with pytest.raises(DingTalkError):
        await client._get_new("/v1.0/x")
    assert client._access_token is None  # 缓存已清
    with pytest.raises(DingTalkError):
        await client._get_new("/v1.0/x")
    # 两次业务调用各触发一次重取 token
    assert counter["/v1.0/oauth2/accessToken"] == 2


async def test_oapi_error_raised():
    """旧版接口 errcode!=0 抛 DingTalkError。"""
    client = build_client({**TOKEN_RESP,
                           "/topapi/user/getbyunionid": Response(200, json={"errcode": 500, "errmsg": "bad"})})
    with pytest.raises(DingTalkError) as ei:
        await client.get_user_by_unionid("u")
    assert ei.value.code == "500"


# ---------------------------------------------------------------------------
# OA 审批接口（M4）
# ---------------------------------------------------------------------------

async def test_create_process_instance_success():
    """发起审批：请求体含 originatorUserId/processCode/deptId/formComponentValues，返回 instanceId。"""
    seen = {}

    def handler(request):
        if request.url.path == "/v1.0/oauth2/accessToken":
            return Response(200, json={"accessToken": "T", "expireIn": 7200})
        seen["json"] = json.loads(request.content or b"{}")
        seen["auth_header"] = request.headers.get("x-acs-dingtalk-access-token")
        return Response(200, json={"instanceId": "inst_123"})

    client = DingTalkClient(client_id="k", client_secret="s", transport=MockTransport(handler))
    pid = await client.create_process_instance(
        originator_user_id="user_a", process_code="PROC-X",
        dept_id=2, form_component_values=[{"name": "审批标题", "value": "t", "componentType": "TextField"}])
    assert pid == "inst_123"
    assert seen["json"]["originatorUserId"] == "user_a"
    assert seen["json"]["processCode"] == "PROC-X"
    assert seen["json"]["deptId"] == 2
    assert seen["json"]["formComponentValues"][0]["name"] == "审批标题"
    assert seen["auth_header"] == "T"


async def test_create_process_instance_with_agent_id():
    """传 microappAgentId 时写入请求体。"""
    seen = {}

    def handler(request):
        if request.url.path == "/v1.0/oauth2/accessToken":
            return Response(200, json={"accessToken": "T", "expireIn": 7200})
        seen["json"] = json.loads(request.content or b"{}")
        return Response(200, json={"instanceId": "inst"})

    client = DingTalkClient(client_id="k", client_secret="s", transport=MockTransport(handler))
    await client.create_process_instance("u", "PROC", 1, [], microapp_agent_id=456)
    assert seen["json"]["microappAgentId"] == 456


async def test_create_process_instance_missing_instance_id():
    """响应缺 instanceId 抛 DingTalkError。"""
    client = build_client({**TOKEN_RESP,
                           "/v1.0/workflow/processInstances": Response(200, json={"code": "invalidParameter"})})
    with pytest.raises(DingTalkError) as ei:
        await client.create_process_instance("u", "PROC", 1, [])
    assert ei.value.code == "invalidParameter"


async def test_create_process_instance_process_code_error():
    """processCodeError（模板不存在）→ 业务可读错误。"""
    client = build_client({**TOKEN_RESP,
                           "/v1.0/workflow/processInstances":
                               Response(400, json={"code": "processCodeError", "message": "no such process"})})
    with pytest.raises(DingTalkError) as ei:
        await client.create_process_instance("u", "PROC", 1, [])
    assert "审批模板不存在" in ei.value.message


async def test_get_process_instance_returns_result():
    """获取审批实例详情：返回 result（含 tasks[].mobileUrl/pcUrl）。"""
    client = build_client({
        **TOKEN_RESP,
        "/v1.0/workflow/processInstances":
            Response(200, json={"result": {"status": "RUNNING",
                                           "tasks": [{"mobileUrl": "https://m", "pcUrl": "https://p"}]}}),
    })
    result = await client.get_process_instance("inst_123")
    assert result["status"] == "RUNNING"
    assert result["tasks"][0]["mobileUrl"] == "https://m"
