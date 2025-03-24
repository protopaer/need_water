from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


DATABASE_URL = "sqlite+aiosqlite:///water.db"  # для SQLite в async
engine = create_async_engine(DATABASE_URL, echo=False)

# Фабрика асинхронных сессий
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

dp = Dispatcher(storage=MemoryStorage())

# Планировщик
scheduler = AsyncIOScheduler()
