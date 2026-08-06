from pydantic import BaseModel, Field

class CreateMarketingCampaignArgs(BaseModel):
    name: str = Field(description="活动名称，简短明确。必填。")
    budget: float = Field(description="活动预算（人民币元），必须为正数。必填。")
    channel: str = Field(description="投放渠道名称，如 社交媒体 / 短信 / 邮件 / 推送 / 全渠道。必填。")
    start_date: str = Field(description="活动开始日期，格式 YYYY-MM-DD。必填。")
    end_date: str = Field(description="活动结束日期，格式 YYYY-MM-DD，不得早于开始日期。必填。")

DESCRIPTION = (
    "创建新的营销活动（高风险操作，执行前需用户确认）。"
    "返回创建结果：campaign_id（活动ID）、name、budget、channel、start_date、end_date、status。"
    "创建成功后如需正式发布，请将返回的 campaign_id 传给 publish_campaign。"
    "注意：budget 单位为元且必须为正数；start_date/end_date 格式 YYYY-MM-DD；"
    "channel 填写投放渠道名称。"
)

def create_marketing_campaign(name: str, budget: float, channel: str, start_date: str, end_date: str) -> dict:
    return {"campaign_id": f"C{int(budget):05d}", "name": name, "budget": budget,
            "channel": channel, "start_date": start_date, "end_date": end_date, "status": "created"}
