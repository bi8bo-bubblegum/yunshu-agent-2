from pydantic import BaseModel, Field

class AdjustScheduleArgs(BaseModel):
    shift_id: str = Field(description="要调整的班次 ID，须来自 query_schedule 的返回结果。必填。")
    employee_id: str = Field(description="员工 ID。必填。")
    new_date: str = Field(description="调整后的日期，格式 YYYY-MM-DD。必填。")
    new_time: str = Field(description="调整后的时间段，格式如 08:00-16:00。必填。")

DESCRIPTION = (
    "调整员工排班班次（高风险操作，执行前需用户确认），返回调整结果 shift_id、employee_id、"
    "new_date、new_time、status。\n"
    "【何时调用】用户明确要求调整某员工某次班次，且已通过 query_schedule 查询到真实班次拿到 shift_id 时。\n"
    "【何时不调用】尚未查询排班、拿不到 shift_id 时；缺少员工、日期或时间信息时；"
    "用户未确认要调整时。\n"
    "【调用示例】\n"
    "- 「把张三 8月10日的早班改成晚班」→ 先用 query_schedule 查到该班次得到 shift_id，"
    "再 shift_id=S001, employee_id=张三的员工ID, new_date=2026-08-10, new_time=16:00-24:00"
)

def adjust_schedule(shift_id: str, employee_id: str, new_date: str, new_time: str) -> dict:
    return {"shift_id": shift_id, "employee_id": employee_id,
            "new_date": new_date, "new_time": new_time, "status": "adjusted"}
