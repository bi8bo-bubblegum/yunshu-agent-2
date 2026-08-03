# backend/scripts/seed.py
import asyncio
from app.core.database import SessionLocal
from app.services.seed import seed_roles

async def main():
    async with SessionLocal() as db:
        await seed_roles(db)
    print("seeded")

if __name__ == "__main__":
    asyncio.run(main())