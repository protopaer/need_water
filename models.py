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
        'Offices',
        back_populates='building',  # Изменено с backref на back_populates
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return self.name


class Offices(Base):
    """Модель кабинетов."""
    abbr = Column(String(ABBR_OFFICE_COUNT), nullable=False)
    name = Column(String(NAME_OFFICE_COUNT), nullable=False)
    # FIXME это не очень, получается он может быть пустым и(или) не уникальным:
    office_number = Column(Integer, nullable=True)
    build_id = Column(Integer, ForeignKey('builds.id'), nullable=False)

    # Отношения
    building = relationship('Builds', back_populates='offices')
    orders = relationship('Order', back_populates='office')
    tg_accounts = relationship('TgAccounts', back_populates='office')

    def __repr__(self):
        return f'{self.abbr} /каб. {self.office_number}/'


class TgAccounts(Base):
    """Модель аккаунтов в Telegram."""
    account = Column(String(TG_ACCOUNT_LEN), nullable=False, unique=True)
    blocked = Column(Boolean, default=False)
    last_office = Column(Integer, ForeignKey('offices.id'), default=None)

    # Отношения
    office = relationship('Offices', back_populates='tg_accounts')

    user_orders = relationship(  # Изменено имя с orders на user_orders
        'Order',
        back_populates='user_account',
        cascade='all, delete-orphan',
        passive_deletes=True
    )


class Order(Base):
    """Модель Заказов воды."""
    office_id = Column(Integer, ForeignKey('offices.id'), nullable=False)
    tg_account_id = Column(
        Integer, ForeignKey('tgaccounts.id'), nullable=False
    )
    order_date = Column(Date, nullable=False)
    order_time = Column(Time, nullable=False)
    in_archive = Column(Boolean, default=False)
    bootles_left = Column(Integer, nullable=False)

    # Отношения
    office = relationship('Offices', back_populates='orders')
    user_account = relationship('TgAccounts', back_populates='user_orders')
