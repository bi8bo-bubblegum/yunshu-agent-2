# backend/app/services/dingtalk/client.py
"""钉钉企业内部应用客户端（DingTalkClient）。

职责：
- token 缓存：accessToken / jsapiTicket（各 2 小时），过期前提前刷新，并发互斥防止击穿
- 统一封装两类接口：
  - 新版 OpenAPI（api.dingtalk.com）：x-acs-dingtalk-access-token 请求头，业务 JSON 直接返回
  - 旧版 OAPI（oapi.dingtalk.com）：access_token 参数（POST 表单），errcode==0 判定成功
- 统一错误映射：40001 / 60011 / 820008 等错误码 → 业务可读提示

进程内单例使用：不引入 Redis，缓存存在内存；进程重启后自动重新获取。
"""
import asyncio
import base64
import hashlib
import hmac
import logging
import time

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# accessToken / jsapiTicket 有效期 2 小时（钉钉侧值）
TOKEN_TTL = 7200
# 过期前提前刷新余量（秒）：避免临界点请求命中已过期 token
TOKEN_REFRESH_AHEAD = 300

# 错误码/错误信息 → 业务可读提示（覆盖内部应用常用场景，未命中返回原始信息）
ERROR_MESSAGES = {
    "40001": "access_token 失效或凭证错误，请检查 Client Secret",
    "400": "Client ID / Client Secret 无效",
    "invalidClientIdOrSecret": "Client ID / Client Secret 无效",
    "60011": "无权限调用该接口，请检查应用『权限管理』是否已申请对应权限",
    "820008": "无审批撤销权限，请在 OA 后台审批模板开启『允许提交人撤销』",
    "needAuth": "无发起审批权限",
    "processCodeError": "审批模板不存在（processCode 有误）",
    "formConverterError": "审批表单校验失败（模板字段与提交值不匹配）",
    "invalidParameter": "请求参数非法",
    "invalidAuthInfo": "企业未开通应用授权",
    "accessdenieddetail": "无权限调用该接口",
    "invalidCode": "授权码无效或已过期，请重新扫码登录",
    "invalidParameter.authCode.notFound": "授权码无效或已过期，请重新扫码登录",
}


class DingTalkError(Exception):
    """钉钉接口调用异常，携带业务可读 message 与原始错误码。"""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code


class DingTalkClient:
    """钉钉企业内部应用客户端。凭证缺省取全局配置，也可显式传入（便于测试）。"""

    def __init__(self, client_id: str | None = None, client_secret: str | None = None,
                 transport=None):
        self.client_id = client_id or settings.DINGTALK_CLIENT_ID
        self.client_secret = client_secret or settings.DINGTALK_CLIENT_SECRET
        # 可注入 httpx transport（单测用 MockTransport 拦截请求，生产为 None 走真实网络）
        self._transport = transport
        # token 缓存（进程内）
        self._access_token: str | None = None
        self._token_expire_at: float = 0.0
        self._jsapi_ticket: str | None = None
        self._ticket_expire_at: float = 0.0
        # 并发互斥锁：多个协程同时过期时只放行一个去刷新
        self._token_lock = asyncio.Lock()
        self._ticket_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # token 管理
    # ------------------------------------------------------------------

    async def get_access_token(self) -> str:
        """获取企业内部应用 accessToken（缓存 + 过期前刷新 + 并发互斥）。"""
        if self._access_token and time.monotonic() < self._token_expire_at:
            return self._access_token
        async with self._token_lock:
            # 双重检查：排队拿到锁后可能已被其他协程刷新
            if self._access_token and time.monotonic() < self._token_expire_at:
                return self._access_token
            token = await self._fetch_access_token()
            self._access_token = token
            self._token_expire_at = time.monotonic() + TOKEN_TTL - TOKEN_REFRESH_AHEAD
            logger.info("已刷新钉钉 accessToken，%d 秒后过期", TOKEN_TTL)
            return token

    async def _fetch_access_token(self) -> str:
        """POST /v1.0/oauth2/accessToken 换取企业内部应用 token（新版，无需鉴权头）。"""
        body = await self._post_new(
            "/v1.0/oauth2/accessToken",
            json={"appKey": self.client_id, "appSecret": self.client_secret},
            use_token=False,
        )
        token = body.get("accessToken")
        if not token:
            raise DingTalkError("获取 accessToken 失败：响应缺少 accessToken 字段", "invalidClientIdOrSecret")
        return token

    async def get_jsapi_ticket(self) -> str:
        """获取 jsapiTicket（缓存 + 互斥刷新，用于 H5 微应用 dd.config 鉴权）。"""
        if self._jsapi_ticket and time.monotonic() < self._ticket_expire_at:
            return self._jsapi_ticket
        async with self._ticket_lock:
            if self._jsapi_ticket and time.monotonic() < self._ticket_expire_at:
                return self._jsapi_ticket
            body = await self._post_new("/v1.0/oauth2/jsapiTickets")
            ticket = body.get("jsapiTicket")
            if not ticket:
                raise DingTalkError("获取 jsapiTicket 失败：响应缺少 jsapiTicket 字段")
            self._jsapi_ticket = ticket
            self._ticket_expire_at = time.monotonic() + TOKEN_TTL - TOKEN_REFRESH_AHEAD
            return ticket

    def reset_access_token(self) -> None:
        """清空缓存 token（供 40001 等失效场景强制重取）。"""
        self._access_token = None
        self._token_expire_at = 0.0

    # ------------------------------------------------------------------
    # 新版接口（api.dingtalk.com + x-acs-dingtalk-access-token 头）
    # ------------------------------------------------------------------

    async def _post_new(self, path: str, json: dict | None = None,
                        use_token: bool = True) -> dict:
        headers = {}
        if use_token:
            headers["x-acs-dingtalk-access-token"] = await self.get_access_token()
        async with httpx.AsyncClient(base_url="https://api.dingtalk.com",
                                     headers=headers, timeout=15,
                                     transport=self._transport) as c:
            resp = await c.post(path, json=json)
            return self._parse_new(resp)

    async def _get_new(self, path: str, params: dict | None = None,
                       use_token: bool = True) -> dict:
        headers = {}
        if use_token:
            headers["x-acs-dingtalk-access-token"] = await self.get_access_token()
        async with httpx.AsyncClient(base_url="https://api.dingtalk.com",
                                     headers=headers, timeout=15,
                                     transport=self._transport) as c:
            resp = await c.get(path, params=params)
            return self._parse_new(resp)

    def _parse_new(self, resp: httpx.Response) -> dict:
        """新版接口响应解析：HTTP 非 2xx 或 body 带 code 视为错误。"""
        body = resp.json()
        if resp.status_code >= 400 or body.get("code"):
            code = body.get("code") or str(resp.status_code)
            self._raise_error(body, code)
        return body

    # ------------------------------------------------------------------
    # 旧版接口（oapi.dingtalk.com + access_token 参数 + errcode 判定）
    # ------------------------------------------------------------------

    async def _post_oapi(self, path: str, json: dict | None = None) -> dict:
        """旧版 OAPI 调用：access_token 走 query 参数；errcode==0 判定成功。"""
        token = await self.get_access_token()
        async with httpx.AsyncClient(base_url="https://oapi.dingtalk.com", timeout=15,
                                     transport=self._transport) as c:
            resp = await c.post(path, params={"access_token": token}, json=json)
            body = resp.json()
            if body.get("errcode") != 0:
                self._raise_error(body, str(body.get("errcode", "unknown")))
            return body

    # ------------------------------------------------------------------
    # 错误处理
    # ------------------------------------------------------------------

    def _raise_error(self, body: dict, code: str) -> None:
        detail = (
            body.get("message") or body.get("errmsg")
            or body.get("msg") or body.get("error_description") or ""
        )
        msg = ERROR_MESSAGES.get(code, f"钉钉接口错误（{code}）：{detail}".rstrip("："))
        if code in ("40001", "400", "invalidClientIdOrSecret"):
            # token 失效：清缓存，下次调用自动重取
            self.reset_access_token()
        raise DingTalkError(msg, code)

    # ------------------------------------------------------------------
    # 代表性业务接口（M2 登录用，验证新旧封装闭环）
    # ------------------------------------------------------------------

    async def get_userinfo_by_code(self, auth_code: str) -> dict:
        """通过免登码获取用户信息（topapi/v2/user/getuserinfo，官方文档确认）。

        用于钉钉内 H5 工作台免登：前端 dd.getAuthCode() 得到免登码后，
        后端拿企业内部应用 token 换 userid。返回 result 含 userid/unionid/name。
        """
        body = await self._post_oapi("/topapi/v2/user/getuserinfo", json={"code": auth_code})
        return body.get("result") or {}

    async def get_user_by_unionid(self, unionid: str) -> str | None:
        """根据 unionid 获取钉钉 userid（topapi/user/getbyunionid，官方文档确认）。

        网页扫码登录链路：免登码 → unionid（sns 接口）→ 本接口换 userid。
        注意：文档明确必须用企业内部应用 token 调本接口，不能用免登用户 token。
        """
        body = await self._post_oapi("/topapi/user/getbyunionid", json={"unionid": unionid})
        result = body.get("result") or {}
        # contact_type: 0=企业内部员工 1=外部联系人
        return result.get("userid")

    async def get_sns_userinfo_bycode(self, tmp_auth_code: str) -> dict:
        """网页扫码登录：授权码换用户信息（新版 OAuth2，官方「实现登录第三方网站」文档确认）。

        前端 Login.vue 跳 login.dingtalk.com/oauth2/auth（scope=openid）获取 authCode 后：
        1. POST /v1.0/oauth2/userAccessToken 用 clientId/clientSecret/code/grantType
           换取用户级 accessToken（此接口不需要企业 accessToken 请求头）
        2. GET /v1.0/contact/users/me，请求头 x-acs-dingtalk-access-token=用户 token，
           返回用户信息（nick/unionId/openId；企业内部应用按权限可能含 userid/mobile）。

        注意：旧版 sns/getuserinfo_bycode（qrconnect）与企业内部应用凭证不配套
        （真实冒烟返回 853004 签名校验失败），且官方已推荐本流程，故前端授权链接
        与后端换票必须统一走新版 OAuth2，不可混用旧接口。
        """
        # Step 1: 授权码换用户级 accessToken
        token_body = await self._post_new(
            "/v1.0/oauth2/userAccessToken",
            json={
                "clientId": self.client_id,
                "clientSecret": self.client_secret,
                "code": tmp_auth_code,
                "grantType": "authorization_code",
            },
            use_token=False,
        )
        user_token = token_body.get("accessToken")
        if not user_token:
            raise DingTalkError("获取用户 accessToken 失败：响应缺少 accessToken 字段", "invalidParameter")
        # Step 2: 用户 token 调 /v1.0/contact/users/me（头与企业 accessToken 相同但值不同）
        headers = {"x-acs-dingtalk-access-token": user_token}
        async with httpx.AsyncClient(base_url="https://api.dingtalk.com", timeout=15,
                                     transport=self._transport) as c:
            resp = await c.get("/v1.0/contact/users/me", headers=headers)
            return self._parse_new(resp)

    # ------------------------------------------------------------------
    # 通讯录接口（M3 组织同步，全部走旧版 OAPI）
    # ------------------------------------------------------------------

    async def get_dept_detail(self, dept_id: int) -> dict:
        """部门详情（topapi/v2/department/get）：返回 name / parent_id / id 等。"""
        body = await self._post_oapi("/topapi/v2/department/get", json={"dept_id": dept_id, "language": "zh_CN"})
        return body.get("result") or {}

    async def list_sub_departments(self, dept_id: int) -> list[dict]:
        """获取指定部门的直属下级部门（topapi/v2/department/listsub）。

        只取下一级，不递归；返回元素含 dept_id / name / parent_id。
        """
        body = await self._post_oapi("/topapi/v2/department/listsub",
                                     json={"dept_id": dept_id, "language": "zh_CN"})
        return body.get("result") or []

    async def list_dept_users(self, dept_id: int, cursor: int = 0, size: int = 100) -> tuple[list[dict], bool, int]:
        """分页获取指定部门直属员工完整详情（topapi/v2/user/list，官方文档确认）。

        返回 (员工列表, has_more, next_cursor)；分页终止以 has_more=false 为准
        （官方文档明确，不能只看 next_cursor 是否为 0）。
        员工元素含 userid / unionid / name / avatar / mobile / job_number / title / email /
        dept_id_list(Number[]) / active / admin / leader。
        """
        body = await self._post_oapi("/topapi/v2/user/list", json={
            "dept_id": dept_id, "cursor": cursor, "size": size, "language": "zh_CN"})
        result = body.get("result") or {}
        return result.get("list") or [], bool(result.get("has_more")), int(result.get("next_cursor") or 0)

    async def list_all_dept_users(self, dept_id: int) -> list[dict]:
        """循环翻页拉取指定部门全部直属员工（has_more 终止，供全量同步用）。"""
        users: list[dict] = []
        cursor, has_more = 0, True
        while has_more:
            page, has_more, cursor = await self.list_dept_users(dept_id, cursor=cursor)
            users.extend(page)
        return users

    async def get_user_detail(self, userid: str) -> dict:
        """员工详情（topapi/v2/user/get）：供增量事件按 userid 拉取单条最新数据。"""
        body = await self._post_oapi("/topapi/v2/user/get", json={"userid": userid, "language": "zh_CN"})
        return body.get("result") or {}

    # ------------------------------------------------------------------
    # OA 审批接口（M4 审批对接，全部走新版 API）
    # ------------------------------------------------------------------

    async def create_process_instance(self, originator_user_id: str, process_code: str,
                                      dept_id: int, form_component_values: list[dict],
                                      microapp_agent_id: int | None = None) -> str:
        """发起钉钉 OA 审批实例（POST /v1.0/workflow/processInstances，官方文档确认）。

        不传 approvers（复用模板后台默认审批流），故 deptId 必填（无部门传 -1 根部门）。
        form_component_values 每项含 name(模板控件 label)/value/componentType。
        返回 processInstanceId；响应缺 instanceId 抛 DingTalkError。
        常见错误 needAuth/processCodeError/formConverterError 已在 ERROR_MESSAGES 映射。
        """
        body = {
            "originatorUserId": originator_user_id,
            "processCode": process_code,
            "deptId": dept_id,
            "formComponentValues": form_component_values,
        }
        if microapp_agent_id is not None:
            body["microappAgentId"] = microapp_agent_id
        resp = await self._post_new("/v1.0/workflow/processInstances", json=body)
        instance_id = resp.get("instanceId")
        if not instance_id:
            raise DingTalkError("发起审批成功但响应缺少 instanceId", "invalidParameter")
        return instance_id

    async def get_process_instance(self, process_instance_id: str) -> dict:
        """获取审批实例详情（GET /v1.0/workflow/processInstances，官方文档确认）。

        返回 result 字典，含 status(RUNNING/TERMINATED/COMPLETED)、result(agree/refuse)、
        approverUserIds、tasks[]（每项含 taskId/userId/mobileUrl/pcUrl）、formComponentValues[]。
        供审批事件回写解析结果 + 后台回填「去钉钉处理」跳转 URL 用。
        """
        resp = await self._get_new("/v1.0/workflow/processInstances",
                                   params={"processInstanceId": process_instance_id})
        return resp.get("result") or {}


# 进程内共享单例（避免各模块各自建 client、重复缓存 token）
dingtalk_client = DingTalkClient()
