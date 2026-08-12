# backend/app/services/experience_service.py
from datetime import date
from uuid import UUID

from fastapi import HTTPException
from app.models.experience import Experience
from app.repositories.experience_repo import ExperienceRepository
from app.services.approval_service import ApprovalService
from app.services.embedding import embed_texts


def _valid_uuid(value: str) -> bool:
    try:
        UUID(str(value))
    except ValueError:
        return False
    return True

class ExperienceService:
    def __init__(self, db):
        self.experience_repo = ExperienceRepository(db)
        self.approval_svc = ApprovalService(db)

    async def create(self, user_id: str, department_id: str | None, data) -> Experience:
        vec = (await embed_texts([f"{data.title} {data.summary}"]))[0]
        event_time = date.fromisoformat(data.event_time) if data.event_time else None
        exp = Experience(owner_id=user_id, scope="personal", status="draft", title=data.title,
                         summary=data.summary, content=data.content, tags=data.tags,
                         event_time=event_time, result_metrics=data.result_metrics,
                         department_id=department_id, embedding=vec)
        await self.experience_repo.add(exp)
        await self.experience_repo.commit()
        return exp

    async def submit(self, user_id: str, exp_id: str, to_scope: str) -> Experience:
        exp = await self.experience_repo.get(exp_id)
        if not exp or exp.owner_id != user_id or exp.scope != "personal":
            raise HTTPException(404, "经验不存在或不可提交")
        if to_scope not in ("dept", "company"):
            raise HTTPException(400, "目标层级无效")
        exp.status = "pending"
        # 创建统一审批单（经验晋升，非阻塞）
        approver_role = "dept_owner" if to_scope == "dept" else "admin"
        await self.approval_svc.create_approval(
            category="experience_promotion", risk=None, mode="async",
            ref_type="experience", ref_id=exp.id,
            title=f"经验晋升：{exp.title}",
            context={"experience_id": exp.id, "from_scope": "personal", "to_scope": to_scope},
            requester_id=user_id, approver_role=approver_role,
        )
        return exp

    async def list_visible(self, user_id: str, department_id: str | None) -> list[Experience]:
        return await self.experience_repo.list_visible(user_id, department_id)

    async def delete(self, user_id: str, exp_id: str, role_code: str | None = None) -> None:
        """删除经验：仅作者本人或 admin 可删（含已晋升到部门/公司层级的本人经验）。"""
        if not _valid_uuid(exp_id):
            raise HTTPException(404, "经验不存在")
        exp = await self.experience_repo.get(exp_id)
        if not exp:
            raise HTTPException(404, "经验不存在")
        if exp.owner_id != user_id and role_code != "admin":
            raise HTTPException(403, "无权删除该经验")
        await self.experience_repo.delete(exp)
        await self.experience_repo.commit()

    async def get_detail(self, user_id: str, exp_id: str, department_id: str | None) -> Experience:
        """查看经验详情：个人=本人、部门=同部门、公司=全员可见，其余返回 404。"""
        if not _valid_uuid(exp_id):
            raise HTTPException(404, "经验不存在")
        exp = await self.experience_repo.get(exp_id)
        if not exp:
            raise HTTPException(404, "经验不存在")
        visible = (
            exp.owner_id == user_id
            or exp.scope == "company"
            or (exp.scope == "dept" and exp.department_id == department_id)
        )
        if not visible:
            raise HTTPException(404, "经验不存在")
        return exp

    async def update_metrics(self, user_id: str, exp_id: str, role_code: str | None,
                             event_time: str | None, result_metrics: dict | None) -> Experience:
        """更新经验的活动时间与效果指标（作者本人或 admin）。

        这两个字段不参与 embedding（向量由 title+summary 生成），修改无需重算向量；
        也只允许改这两个字段，标题/内容等改动的编辑入口后续再按需扩展。"""
        if not _valid_uuid(exp_id):
            raise HTTPException(404, "经验不存在")
        exp = await self.experience_repo.get(exp_id)
        if not exp:
            raise HTTPException(404, "经验不存在")
        if exp.owner_id != user_id and role_code != "admin":
            raise HTTPException(403, "无权编辑该经验")
        # event_time 为空串/None 表示清空活动时间
        exp.event_time = date.fromisoformat(event_time) if event_time else None
        exp.result_metrics = result_metrics
        await self.experience_repo.commit()
        return exp
