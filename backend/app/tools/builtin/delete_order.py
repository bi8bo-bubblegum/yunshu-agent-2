from pydantic import BaseModel, Field

class DeleteOrderArgs(BaseModel):
    order_id: str = Field(description="要删除的订单 ID。必填，删除前请确认订单号正确。")
    reason: str = Field(description="删除原因，需明确具体（如 用户误下单 / 重复订单）。必填。")

DESCRIPTION = (
    "删除指定订单（critical 高风险操作，需进入审批中心审批通过后才会执行），返回删除结果 order_id、reason、status。\n"
    "【何时调用】用户明确要求删除某个订单，且订单号明确、删除原因具体（如 用户误下单 / 重复订单）时。\n"
    "【何时不调用】订单号不确定、需要先核实订单信息时；用户未明确表达删除意图时；"
    "删除原因不明确时。\n"
    "【调用示例】\n"
    "- 「把订单 20260801 删掉，用户误下单了」→ order_id=20260801, reason=用户误下单"
)

def delete_order(order_id: str, reason: str) -> dict:
    return {"order_id": order_id, "reason": reason, "status": "deleted"}
