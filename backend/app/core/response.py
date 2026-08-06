"""统一响应序列化：API 返回的时间字段按 Asia/Shanghai(+08:00) 输出。

数据库存储仍是 UTC(timestamptz 绝对时间),但 API 层把常见时间字段
转换为北京时间,避免开发者在 Swagger/Postman/网络面板里看到"少了 8 小时"。
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

BEIJING_TZ = ZoneInfo("Asia/Shanghai")

# 常见时间字段名白名单,避免误转换消息内容等正文中的日期字符串
_DT_FIELDS = {"created_at", "updated_at", "started_at", "submitted_at", "decided_at", "event_time"}


def _convert(obj):
    if isinstance(obj, dict):
        return {
            k: _convert(v) if k not in _DT_FIELDS else _to_beijing(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_convert(x) for x in obj]
    return obj


def _to_beijing(v):
    if not isinstance(v, str):
        return v
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return v
    if dt.tzinfo is None:
        return v
    return dt.astimezone(BEIJING_TZ).isoformat()


def convert_datetimes_to_beijing(content):
    """递归转换响应内容中的时间字段为北京时间字符串。"""
    return _convert(content)
