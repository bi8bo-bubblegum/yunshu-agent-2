from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """通用原子 CRUD：一个方法一个数据库操作，不自行 commit（保证 service 层事务原子性）。
    service 层组合多个 repo 操作后统一调用 commit()。"""
    model = None

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, pk):
        return await self.db.get(self.model, pk)

    async def get_by(self, **filters):
        return (await self.db.scalars(select(self.model).filter_by(**filters))).first()

    async def list(self, **filters):
        return (await self.db.scalars(select(self.model).filter_by(**filters))).all()

    async def add(self, obj):
        """加入会话并 flush（拿到 id），不 commit。"""
        self.db.add(obj)
        await self.db.flush()

    async def add_all(self, objs):
        self.db.add_all(objs)
        await self.db.flush()

    async def delete(self, obj):
        await self.db.delete(obj)
        await self.db.flush()

    async def commit(self):
        """service 组合多个 repo 操作后统一提交事务。"""
        await self.db.commit()

    async def count(self, **filters) -> int:
        stmt = select(func.count()).select_from(self.model)
        if filters:
            stmt = stmt.where(*[getattr(self.model, k) == v for k, v in filters.items()])
        return (await self.db.scalar(stmt)) or 0
