from pydantic import BaseModel, Field

class QueryMarketingCampaignsArgs(BaseModel):
    status: str = Field(description="活动状态过滤：active=进行中、scheduled=待发布、ended=已结束。必填，仅支持这三个取值。")

DESCRIPTION = (
    "查询营销活动列表（可按状态过滤），返回活动概要：id、name、channel、budget、status。"
    "用于营销策划前了解现有活动、避免重复投放与预算冲突。\n"
    "【何时调用】用户询问现有营销活动、策划新活动前需要摸底现有活动、或想查看某状态的活动时。\n"
    "【何时不调用】用户询问销售数据、排班、订单等其他领域问题时；"
    "用户未说明要查看哪个状态的活动时（status 必填，可询问用户后确定）。\n"
    "【调用示例】\n"
    "- 「现在有哪些进行中的活动」→ status=active\n"
    "- 「看看待发布的活动」→ status=scheduled\n"
    "- 「历史已结束的活动有哪些」→ status=ended"
)

def query_marketing_campaigns(status: str) -> list[dict]:
    all_campaigns = [
        {"id": "C001", "name": "618大促", "channel": "全渠道", "budget": 50000, "status": "ended"},
        {"id": "C002", "name": "会员日营销", "channel": "短信+邮件", "budget": 12000, "status": "active"},
        {"id": "C003", "name": "新品预热", "channel": "社交媒体", "budget": 28000, "status": "scheduled"},
        {"id": "C004", "name": "老客回流", "channel": "推送", "budget": 8000, "status": "active"},
    ]
    return [c for c in all_campaigns if c["status"] == status]
