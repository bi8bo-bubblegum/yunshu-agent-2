from pydantic import BaseModel, Field

class PublishCampaignArgs(BaseModel):
    campaign_id: str = Field(description="要发布的活动 ID，必须来自 create_marketing_campaign 的返回结果。必填。")
    channels: list[str] = Field(description="发布渠道名称数组，如 [\"社交媒体\", \"短信\"]。必填，至少一个渠道。")

DESCRIPTION = (
    "正式发布营销活动到指定渠道（critical 高风险操作，需进入审批中心审批通过后才会执行），"
    "返回发布结果 campaign_id、channels、status、published_at。\n"
    "【何时调用】用户明确确认要发布某个已创建成功的活动时"
    "（campaign_id 须来自 create_marketing_campaign 的返回结果）。\n"
    "【何时不调用】活动尚未创建（拿不到 campaign_id）时；用户只是创建活动、并未要求发布时；"
    "channels 为空或用户未说明发布渠道时。\n"
    "【调用示例】\n"
    "- 「把刚才创建的 C00042 活动发布到社交媒体和短信」→ "
    "campaign_id=C00042, channels=[\"社交媒体\", \"短信\"]"
)

def publish_campaign(campaign_id: str, channels: list[str]) -> dict:
    return {"campaign_id": campaign_id, "channels": channels,
            "status": "published", "published_at": "2026-08-01T10:00:00Z"}
