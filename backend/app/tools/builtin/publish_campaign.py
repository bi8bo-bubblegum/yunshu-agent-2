from pydantic import BaseModel, Field

class PublishCampaignArgs(BaseModel):
    campaign_id: str = Field(description="要发布的活动 ID")
    channels: list[str] = Field(description="发布渠道列表")

DESCRIPTION = "正式发布营销活动到指定渠道。Mock 返回发布结果。"

def publish_campaign(campaign_id: str, channels: list[str]) -> dict:
    return {"campaign_id": campaign_id, "channels": channels,
            "status": "published", "published_at": "2026-08-01T10:00:00Z"}