from pydantic import BaseModel, Field

class QueryMarketingCampaignsArgs(BaseModel):
    status: str = Field(description="活动状态：active（进行中）/ scheduled（待发布）/ ended（已结束）")

DESCRIPTION = "查询营销活动列表。返回活动的名称、渠道、预算、状态等概要信息。供营销助手 agent 使用。"

def query_marketing_campaigns(status: str) -> list[dict]:
    all_campaigns = [
        {"id": "C001", "name": "618大促", "channel": "全渠道", "budget": 50000, "status": "ended"},
        {"id": "C002", "name": "会员日营销", "channel": "短信+邮件", "budget": 12000, "status": "active"},
        {"id": "C003", "name": "新品预热", "channel": "社交媒体", "budget": 28000, "status": "scheduled"},
        {"id": "C004", "name": "老客回流", "channel": "推送", "budget": 8000, "status": "active"},
    ]
    return [c for c in all_campaigns if c["status"] == status]