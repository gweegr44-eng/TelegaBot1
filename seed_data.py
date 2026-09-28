"""Скрипт для добавления 9 точек МТС в БД. Запускается ОДИН раз."""
import asyncio
from sqlalchemy import select
from Database.database import init_db, async_session
from Database.models import Store

STORES = [
    ("070519168", "Комарова, 110"),
    ("070519169", "Советская, 86А"),
    ("070519170", "пр-т Карла Маркса, 107А"),
    ("070519171", "пр-т Карла Маркса, 74"),
    ("070519172", "Марченко, 13"),
    ("070518284", "Молодогвардейцев, 32"),
    ("070518861", "Комсомольский проспект, 78"),
    ("070521804", "Труда, 38"),
    ("070522878", "Новороссийская, 118В"),
]


async def seed():
    await init_db()
    async with async_session() as session:
        added = 0
        for code, addr in STORES:
            result = await session.execute(select(Store).where(Store.store_code == code))
            if result.scalar_one_or_none():
                print(f"  ⏭  {code} — уже есть")
                continue
            session.add(Store(store_code=code, address=addr))
            added += 1
            print(f"  ✅ {code} — {addr}")
        await session.commit()
    print(f"\nДобавлено точек: {added}")


if __name__ == "__main__":
    asyncio.run(seed())