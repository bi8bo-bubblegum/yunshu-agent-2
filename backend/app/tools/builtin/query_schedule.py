from pydantic import BaseModel, Field

class QueryScheduleArgs(BaseModel):
    department: str = Field(description="部门名称，如 仓储部 / 配送部 / 客服部。必填，需与系统内部门名称一致。")
    date: str = Field(description="查询日期，格式 YYYY-MM-DD。必填。")

DESCRIPTION = (
    "查询指定部门在某天的排班情况，返回班次列表，每项含 shift_id（班次ID）、"
    "employee（员工）、time（时间段）、role（班次类型）、department（部门）。"
    "用于排班诊断与调度优化，进行任何排班调整前必须先查询真实排班。"
    "注意：department 必填（如 仓储部/配送部/客服部），date 必填且格式为 YYYY-MM-DD。"
)

def query_schedule(department: str, date: str) -> list[dict]:
    return [
        {"shift_id": "S001", "employee": "张三", "time": "08:00-16:00", "role": "早班", "department": department},
        {"shift_id": "S002", "employee": "李四", "time": "16:00-24:00", "role": "晚班", "department": department},
        {"shift_id": "S003", "employee": "王五", "time": "08:00-16:00", "role": "早班", "department": department},
    ]
