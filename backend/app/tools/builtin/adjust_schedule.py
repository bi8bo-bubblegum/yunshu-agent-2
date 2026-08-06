from pydantic import BaseModel, Field

class AdjustScheduleArgs(BaseModel):
    shift_id: str = Field(description="要调整的班次 ID，须来自 query_schedule 的返回结果。必填。")
    employee_id: str = Field(description="员工 ID。必填。")
    new_date: str = Field(description="调整后的日期，格式 YYYY-MM-DD。必填。")
    new_time: str = Field(description="调整后的时间段，格式如 08:00-16:00。必填。")

DESCRIPTION = (
    "调整员工排班班次（高风险操作，执行前需用户确认）。"
    "返回调整结果：shift_id、employee_id、new_date、new_time、status。"
    "注意：调整前必须先调用 query_schedule 获取真实班次，shift_id 须来自查询结果；"
    "new_time 格式为 HH:mm-HH:mm（如 08:00-16:00）。"
)

def adjust_schedule(shift_id: str, employee_id: str, new_date: str, new_time: str) -> dict:
    return {"shift_id": shift_id, "employee_id": employee_id,
            "new_date": new_date, "new_time": new_time, "status": "adjusted"}
