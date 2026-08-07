"""当前日期上下文：按北京时间(Asia/Shanghai)生成，注入 agent/supervisor 提示词。

大模型训练数据不含实时日期，回答"今天/本月/去年同期"等表述时只能靠猜，
在提示词中显式注入当前日期可避免日期幻觉。
"""
from datetime import datetime
from zoneinfo import ZoneInfo

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def current_date_context() -> str:
    """返回如「当前日期：2026年8月7日（星期五）」的北京时间日期描述。"""
    now = datetime.now(BEIJING_TZ)
    return f"当前日期：{now.year}年{now.month}月{now.day}日（{_WEEKDAYS[now.weekday()]}）"
