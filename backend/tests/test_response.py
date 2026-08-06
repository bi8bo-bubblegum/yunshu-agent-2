"""API 时间字段统一输出北京时间。"""
from app.core.response import convert_datetimes_to_beijing


def test_convert_created_at_to_beijing():
    out = convert_datetimes_to_beijing({
        "created_at": "2026-08-06T07:15:12.308822Z",
        "title": "x",
    })
    assert out["created_at"] == "2026-08-06T15:15:12.308822+08:00"
    assert out["title"] == "x"


def test_do_not_convert_message_content_dates():
    """消息正文里的日期字符串不应被误转换。"""
    out = convert_datetimes_to_beijing({
        "content": "活动时间 2024-10-01 至 2024-10-07",
        "created_at": "2026-08-06T07:15:12Z",
    })
    assert out["content"] == "活动时间 2024-10-01 至 2024-10-07"
    assert out["created_at"] == "2026-08-06T15:15:12+08:00"


def test_nested_list():
    out = convert_datetimes_to_beijing([
        {"submitted_at": "2026-08-06T02:00:00Z"},
        {"id": "1"},
    ])
    assert out[0]["submitted_at"] == "2026-08-06T10:00:00+08:00"
    assert out[1]["id"] == "1"
