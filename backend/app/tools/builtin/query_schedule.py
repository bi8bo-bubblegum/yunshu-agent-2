from pydantic import BaseModel, Field

class QueryScheduleArgs(BaseModel):
    department: str = Field(description="部门名称，如 '仓储部' / '配送部' / '客服部'")
    date: str = Field(description="查询日期，格式 YYYY-MM-DD")

DESCRIPTION = "查询指定部门某天的排班情况。返回班次、人员、时间段等信息。供调度优化 agent 使用。"

def query_schedule(department: str, date: str) -> list[dict]:
    return [
        {"shift_id": "S001", "employee": "张三", "time": "08:00-16:00", "role": "早班", "department": department},
        {"shift_id": "S002", "employee": "李四", "time": "16:00-24:00", "role": "晚班", "department": department},
        {"shift_id": "S003", "employee": "王五", "time": "08:00-16:00", "role": "早班", "department": department},
    ]