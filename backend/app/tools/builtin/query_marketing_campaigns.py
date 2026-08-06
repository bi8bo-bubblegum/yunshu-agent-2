from pydantic import BaseModel, Field

class QueryMarketingCampaignsArgs(BaseModel):
    status: str = Field(description="活动状态过滤：active=进行中、scheduled=待发布、ended=已结束。必填，仅支持这三个取值。")

DESCRIPTION = (
    "查询营销活动列表，可按状态过滤，返回活动概要：id（活动ID）、name（名称）、"
    "channel（投放渠道）、budget（预算，元）、status（状态）。"
    "用于营销策划前了解现有活动、避免重复投放与预算冲突。"
    "注意：status 为必填参数，仅支持 active（进行中）/ scheduled（待发布）/ ended（已结束）。"
)

def query_marketing_campaigns(status: str) -> list[dict]:
    all_campaigns = [
        {"id": "C001", "name": "618大促", "channel": "全渠道", "budget": 50000, "status": "ended"},
        {"id": "C002", "name": "会员日营销", "channel": "短信+邮件", "budget": 12000, "status": "active"},
        {"id": "C003", "name": "新品预热", "channel": "社交媒体", "budget": 28000, "status": "scheduled"},
        {"id": "C004", "name": "老客回流", "channel": "推送", "budget": 8000, "status": "active"},
    ]
    return [c for c in all_campaigns if c["status"] == status]
