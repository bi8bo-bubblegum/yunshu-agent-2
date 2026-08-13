"""钉钉 Stream 事件处理器单测：process 返回值必须符合 SDK 约定。

真实事故：process 返回 AckMessage 对象而非 (code, message) 元组，SDK raw_process
解包时抛「cannot unpack non-iterable AckMessage object」，确认帧发不出去，
钉钉反复重推事件、日志持续刷屏。
"""
from dingtalk_stream import AckMessage, EventMessage

from app.services.dingtalk.client import DingTalkClient
from app.services.dingtalk.stream import DingTalkStreamSubscriber


async def test_process_returns_sdk_tuple():
    """process 返回 (STATUS_OK, 'OK') 元组，供 SDK raw_process 解包构造 AckMessage。"""
    calls = []

    async def fake_handle(data):
        calls.append(data)

    sub = DingTalkStreamSubscriber(DingTalkClient(client_id="k", client_secret="s"))
    sub._handle_approval_instance = fake_handle
    event = EventMessage()
    event.headers.event_type = "bpms_instance_change"
    event.data = {"processInstanceId": "inst_1", "type": "finish", "result": "agree"}

    result = await sub.process(event)
    assert result == (AckMessage.STATUS_OK, "OK")
    assert calls == [{"processInstanceId": "inst_1", "type": "finish", "result": "agree"}]


async def test_process_unknown_event_still_acks():
    """未订阅事件类型也返回 200 元组，不抛异常。"""
    sub = DingTalkStreamSubscriber(DingTalkClient(client_id="k", client_secret="s"))
    event = EventMessage()
    event.headers.event_type = "some_unknown_event"
    event.data = {}
    assert await sub.process(event) == (AckMessage.STATUS_OK, "OK")
