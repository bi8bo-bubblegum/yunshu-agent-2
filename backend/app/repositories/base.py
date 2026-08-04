from typing import ClassVar, Generic, Type, TypeVar
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    """通用原子 CRUD：一个方法一个数据库操作，不自行 commit（保证 service 层事务原子性）。
    service 层组合多个 repo 操作后统一调用 commit()。"""
    model: ClassVar[Type[ModelType]]

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, pk) -> ModelType | None:
        return (await self.db.scalars(select(self.model).where(self.model.id == pk))).first()

    async def get_by(self, **filters) -> ModelType | None:
        return (await self.db.scalars(select(self.model).filter_by(**filters))).first()

    async def list(self, **filters) -> list[ModelType]:
        return list((await self.db.scalars(select(self.model).filter_by(**filters))).all())

    async def add(self, obj) -> None:
        """加入会话并 flush（拿到 id），不 commit。"""
        self.db.add(obj)
        await self.db.flush()

    async def add_all(self, objs) -> None:
        self.db.add_all(objs)
        await self.db.flush()

    async def delete(self, obj) -> None:
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
