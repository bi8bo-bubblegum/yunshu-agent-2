from pydantic import BaseModel, Field

class PublishCampaignArgs(BaseModel):
    campaign_id: str = Field(description="要发布的活动 ID，必须来自 create_marketing_campaign 的返回结果。必填。")
    channels: list[str] = Field(description="发布渠道名称数组，如 [\"社交媒体\", \"短信\"]。必填，至少一个渠道。")

DESCRIPTION = (
    "正式发布营销活动到指定渠道（critical 高风险操作，需进入审批中心审批通过后才会执行）。"
    "返回发布结果：campaign_id、channels、status、published_at。"
    "注意：campaign_id 必须来自 create_marketing_campaign 的返回结果；"
    "channels 为渠道名称数组（如 [\"社交媒体\", \"短信\"]），不允许为空。"
)

def publish_campaign(campaign_id: str, channels: list[str]) -> dict:
    return {"campaign_id": campaign_id, "channels": channels,
            "status": "published", "published_at": "2026-08-01T10:00:00Z"}
