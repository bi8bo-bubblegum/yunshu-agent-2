# backend/app/services/experience_service.py
from fastapi import HTTPException
from app.models.experience import Experience
from app.models.trace import Approval
from app.repositories.experience_repo import ExperienceRepository
from app.repositories.trace_repo import ApprovalRepository
from app.services.embedding import embed_texts

class ExperienceService:
    def __init__(self, db):
        self.experience_repo = ExperienceRepository(db)
        self.approval_repo = ApprovalRepository(db)

    async def create(self, user_id: str, department_id: str | None, data) -> Experience:
        vec = (await embed_texts([f"{data.title} {data.summary}"]))[0]
        exp = Experience(owner_id=user_id, scope="personal", status="draft", title=data.title,
                         summary=data.summary, content=data.content, tags=data.tags,
                         event_time=data.event_time, result_metrics=data.result_metrics,
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
        await self.approval_repo.add(Approval(
            category="experience_promotion", mode="async",
            ref_type="experience", ref_id=exp.id,
            title=f"经验晋升：{exp.title}",
            context={"experience_id": exp.id, "from_scope": "personal", "to_scope": to_scope},
            status="pending", requester_id=user_id, approver_role=approver_role,
        ))
        await self.approval_repo.commit()
        return exp

    async def list_visible(self, user_id: str, department_id: str | None) -> list[Experience]:
        return await self.experience_repo.list_visible(user_id, department_id)