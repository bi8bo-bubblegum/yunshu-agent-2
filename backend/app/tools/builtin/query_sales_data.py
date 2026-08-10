# backend/app/tools/builtin/query_sales_data.py
"""Mock 工具：查询销售指标。不连真实数据库，返回固定 mock 数据。"""
from pydantic import BaseModel, Field

class QuerySalesDataArgs(BaseModel):
    metric: str = Field(description="要查询的指标：revenue=营收（元）、orders=订单量（单）、customers=客户数（人）。必填，一次只能查询一个指标，多指标请多次调用。")
    period: str = Field(description="统计时间范围：7d=近7天、30d=近30天、90d=近90天。必填，仅支持这三个取值。")

DESCRIPTION = (
    "查询企业销售指标（营收/订单量/客户数）在指定时间范围的汇总值、上期对比值与环比变化率，"
    "用于经营分析、营销效果复盘与趋势判断。\n"
    "【何时调用】用户询问销售额、订单量、客户数等经营数据，或要求用数据支撑分析结论时。\n"
    "【何时不调用】用户询问营销活动、排班、订单等其他领域的问题时；"
    "用户一次要查多个指标时（本工具一次只能查一个指标，需分多次调用）。\n"
    "【调用示例】\n"
    "- 「最近30天的营收是多少」→ metric=revenue, period=30d\n"
    "- 「近7天订单量怎么样」→ metric=orders, period=7d\n"
    "- 「对比近90天客户数」→ metric=customers, period=90d"
)

def query_sales_data(metric: str, period: str) -> dict:
    base = {"revenue": 1280000, "orders": 3420, "customers": 856}
    factor = {"7d": 0.25, "30d": 1.0, "90d": 2.8}[period]
    total = int(base[metric] * factor)
    return {"metric": metric, "period": period, "total": total,
            "prev_period": int(total * 0.92), "change_pct": 8.7}
