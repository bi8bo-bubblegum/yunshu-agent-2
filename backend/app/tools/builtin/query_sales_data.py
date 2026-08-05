# backend/app/tools/builtin/query_sales_data.py
"""Mock 工具：查询销售指标。不连真实数据库，返回固定 mock 数据。"""
from pydantic import BaseModel, Field

class QuerySalesDataArgs(BaseModel):
    metric: str = Field(description="指标类型：revenue（营收）/ orders（订单量）/ customers（客户数）")
    period: str = Field(description="时间范围：7d / 30d / 90d")

DESCRIPTION = "查询企业销售指标（营收/订单/客户）。返回指定时间范围的汇总数据与环比变化。供经营分析 agent 使用。"

def query_sales_data(metric: str, period: str) -> dict:
    base = {"revenue": 1280000, "orders": 3420, "customers": 856}
    factor = {"7d": 0.25, "30d": 1.0, "90d": 2.8}[period]
    total = int(base[metric] * factor)
    return {"metric": metric, "period": period, "total": total,
            "prev_period": int(total * 0.92), "change_pct": 8.7}