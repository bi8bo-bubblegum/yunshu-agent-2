
from pydantic import BaseModel, Field

class QueryScheduleArgs(BaseModel):
    department: str = Field(description="部门名称，如 仓储部 / 配送部 / 客服部。必填，需与系统内部门名称一致。")
    date: str = Field(description="查询日期，格式 YYYY-MM-DD。必填。")

DESCRIPTION = (
    "查询指定部门在指定日期的排班情况，返回班次列表（shift_id、employee、time、role、department），"
    "用于排班诊断与调度优化。\n"
    "【何时调用】用户询问某部门某天的人员排班/班次情况，或准备调整排班前需要先查看当前排班时。\n"
    "【何时不调用】用户询问销售/营销/订单等其他领域问题时；"
    "用户未给出部门或日期时（department、date 均为必填）。\n"
    "【调用示例】\n"
    "- 「仓储部 2026-08-10 怎么排班的」→ department=仓储部, date=2026-08-10\n"
    "- 「看看客服部今天的班次」→ department=客服部, date=当天日期（YYYY-MM-DD）"
)

def query_schedule(department: str, date: str) -> list[dict]:
    return [
        {"shift_id": "S001", "employee": "张三", "time": "08:00-16:00", "role": "早班", "department": department},
        {"shift_id": "S002", "employee": "李四", "time": "16:00-24:00", "role": "晚班", "department": department},
        {"shift_id": "S003", "employee": "王五", "time": "08:00-16:00", "role": "早班", "department": department},
    ]
