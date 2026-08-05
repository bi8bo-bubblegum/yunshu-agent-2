from pydantic import BaseModel, Field

class DeleteOrderArgs(BaseModel):
    order_id: str = Field(description="要删除的订单 ID")
    reason: str = Field(description="删除原因")

DESCRIPTION = "删除指定订单。Mock 返回删除结果。"

def delete_order(order_id: str, reason: str) -> dict:
    return {"order_id": order_id, "reason": reason, "status": "deleted"}