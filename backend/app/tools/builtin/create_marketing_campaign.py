from pydantic import BaseModel, Field

class CreateMarketingCampaignArgs(BaseModel):
    name: str = Field(description="活动名称")
    budget: float = Field(description="预算金额（元）")
    channel: str = Field(description="投放渠道")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")

DESCRIPTION = "创建新的营销活动。Mock 返回创建结果，不写真实数据库。"

def create_marketing_campaign(name: str, budget: float, channel: str, start_date: str, end_date: str) -> dict:
    return {"campaign_id": f"C{int(budget):05d}", "name": name, "budget": budget,
            "channel": channel, "start_date": start_date, "end_date": end_date, "status": "created"}