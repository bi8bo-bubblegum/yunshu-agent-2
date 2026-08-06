# backend/app/tools/builtin/query_sales_data.py
"""Mock 工具：查询销售指标。不连真实数据库，返回固定 mock 数据。"""
from pydantic import BaseModel, Field

class QuerySalesDataArgs(BaseModel):
    metric: str = Field(description="要查询的指标：revenue=营收（元）、orders=订单量（单）、customers=客户数（人）。必填，一次只能查询一个指标，多指标请多次调用。")
    period: str = Field(description="统计时间范围：7d=近7天、30d=近30天、90d=近90天。必填，仅支持这三个取值。")

DESCRIPTION = (
    "查询企业销售指标：营收（revenue）/ 订单量（orders）/ 客户数（customers）在指定时间范围"
    "（7d=近7天、30d=近30天、90d=近90天）的汇总值、上期对比值与环比变化率。"
    "用于经营分析、营销效果复盘与趋势判断。"
    "返回 JSON 字段：metric（指标）、period（时间范围）、total（本期总量）、"
    "prev_period（上期总量）、change_pct（环比变化百分比）。"
    "注意：metric 与 period 均为必填；一次查询一个指标，需要多指标时请分多次调用。"
)

def query_sales_data(metric: str, period: str) -> dict:
    base = {"revenue": 1280000, "orders": 3420, "customers": 856}
    factor = {"7d": 0.25, "30d": 1.0, "90d": 2.8}[period]
    total = int(base[metric] * factor)
    return {"metric": metric, "period": period, "total": total,
            "prev_period": int(total * 0.92), "change_pct": 8.7}
