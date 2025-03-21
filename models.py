from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, Date, Time,
    # create_engine
)
from sqlalchemy.orm import (declared_attr, declarative_base, relationship)
# from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import create_async_engine


class Base:
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()

    id = Column(Integer, primary_key=True)


# Функция declarative_base() возвращает класс,
# от которого наследуются модели при декларативном подходе.
Base = declarative_base(cls=Base)


class Builds(Base):
    """Модель зданий."""
    name = Column(String(40), nullable=False)


class Offices(Base):
    """Модель кабинетов."""
    abbr = Column(String(7), nullable=False)
    name = Column(String(40), nullable=False)
    office_number = Column(Integer, nullable=True)
    build_id = Column(
        Integer, ForeignKey('builds.id'), nullable=False
    )

    build = relationship("Builds", backref="orders")

    def __repr__(self):
        return f'{self.abbr} /каб. {self.office_number}/'


class TgAccounts(Base):
    """Модель аккаунтов в Telegram."""
    account = Column(String(20), nullable=False)
    blocked = Column(Boolean, default=False)


class Order(Base):
    """Модель заказов воды."""
    office_id = Column(Integer, ForeignKey('offices.id'), nullable=False)
    tg_account_id = Column(
        Integer, ForeignKey('tgaccounts.id'), nullable=False
    )
    order_date = Column(Date, nullable=False)
    order_time = Column(Time, nullable=False)
    in_archive = Column(Boolean, default=False)

    # Опционально: отношения для удобства доступа к связанным объектам
    office = relationship("Offices", backref="orders")
    tg_account = relationship("TgAccounts", backref="orders")


# engine = create_engine('sqlite:///water.db', echo=False)

DATABASE_URL = "sqlite+aiosqlite:///water.db"  # Пример для SQLite
engine = create_async_engine(DATABASE_URL, echo=False)


# # Когда нужно создать модели - раскомментируй
# Base.metadata.create_all(engine)
