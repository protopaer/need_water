from sqlalchemy import (Column,
                        Integer,
                        String,
                        Boolean,
                        ForeignKey,
                        Date,
                        Time)
from sqlalchemy.orm import (declared_attr,
                            declarative_base,
                            relationship)

from constants import (ABBR_OFFICE_COUNT,
                       NAME_OFFICE_COUNT,
                       NAME_BUILD_COUNT,
                       TG_ACCOUNT_LEN)


class BaseModel:
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()

    id = Column(Integer, primary_key=True, nullable=False)


# Функция declarative_base() возвращает класс,
# от которого наследуются модели при декларативном подходе.
Base = declarative_base(cls=BaseModel)


class Builds(Base):
    """Модель зданий."""
    name = Column(String(NAME_BUILD_COUNT), nullable=False)

    offices = relationship(
        "Offices",
        backref="building",
        cascade="all, delete-orphan"
    )  # получаем build для конкретного office


class Offices(Base):
    """Модель кабинетов."""
    abbr = Column(String(ABBR_OFFICE_COUNT), nullable=False)
    name = Column(String(NAME_OFFICE_COUNT), nullable=False)
    office_number = Column(Integer, nullable=True)
    build_id = Column(
        Integer, ForeignKey('builds.id'), nullable=False
    )

    def __repr__(self):
        return f'{self.abbr} /каб. {self.office_number}/'


class TgAccounts(Base):
    """Модель аккаунтов в Telegram."""
    account = Column(String(TG_ACCOUNT_LEN), nullable=False)
    blocked = Column(Boolean, default=False)
    last_office = Column(
        Integer, ForeignKey('offices.id'), default=None
    )

    # Отношения для доступа к связанным объектам
    office = relationship(
        'Offices',
        backref='office_accounts'
    )  # получаем все tgaccounts для конкретного office / зачем только?

    orders = relationship(
        'Order',
        backref='account',
        cascade='all, delete-orphan',  # Добавляем каскадное удаление
        passive_deletes=True  # Опционально: оптимизация для удаления
    )  # получаем все заявки конкретного tgaccount


class Order(Base):
    """Модель Заказов воды."""
    office_id = Column(Integer, ForeignKey('offices.id'), nullable=False)
    tg_account_id = Column(
        Integer, ForeignKey('tgaccounts.id'), nullable=False
    )
    order_date = Column(Date, nullable=False)
    order_time = Column(Time, nullable=False)
    in_archive = Column(Boolean, default=False)
