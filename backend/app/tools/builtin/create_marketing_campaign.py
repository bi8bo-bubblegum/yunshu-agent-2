from pydantic import BaseModel, Field

class CreateMarketingCampaignArgs(BaseModel):
    name: str = Field(description="活动名称，简短明确。必填。")
    budget: float = Field(description="活动预算（人民币元），必须为正数。必填。")
    channel: str = Field(description="投放渠道名称，如 社交媒体 / 短信 / 邮件 / 推送 / 全渠道。必填。")
    start_date: str = Field(description="活动开始日期，格式 YYYY-MM-DD。必填。")
    end_date: str = Field(description="活动结束日期，格式 YYYY-MM-DD，不得早于开始日期。必填。")

DESCRIPTION = (
    "创建新的营销活动（高风险操作，执行前需用户确认），返回创建结果 campaign_id、name、budget、"
    "channel、start_date、end_date、status。创建成功后如需正式发布，需将返回的 campaign_id 传给 publish_campaign。\n"
    "【何时调用】用户明确要求新建营销活动，且活动名称、预算、渠道、起止日期齐全或可合理推导时。\n"
    "【何时不调用】用户只是询问/查看现有活动（应调 query_marketing_campaigns）时；"
    "活动信息不完整时；用户未明确要创建活动时。\n"
    "【调用示例】\n"
    "- 「帮我建一个618大促活动，预算3万，投社交媒体，8月1日到8月18日」→ "
    "name=618大促, budget=30000, channel=社交媒体, start_date=2026-08-01, end_date=2026-08-18"
)

def create_marketing_campaign(name: str, budget: float, channel: str, start_date: str, end_date: str) -> dict:
    return {"campaign_id": f"C{int(budget):05d}", "name": name, "budget": budget,
            "channel": channel, "start_date": start_date, "end_date": end_date, "status": "created"}
