from sqlalchemy import String, cast, select
from app.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_username(self, username: str):
        return await self.get_by(username=username)

    async def list_by_ids(self, ids: list[str]) -> list[User]:
        """按 id 批量取用户（审批列表展示发起人/审批人 username 用）。
        User.id 是 UUID 列，参数为字符串，需 cast 后 in_ 避免类型不匹配报错。"""
        if not ids:
            return []
        return list((await self.db.scalars(
            select(User).where(cast(User.id, String).in_(ids))
        )).all())
