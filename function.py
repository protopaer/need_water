from random import randint
from typing import Optional

from sqlalchemy import and_, select

from models import Offices, Order


def string_generate():
    """Генерирует случайное число в телефонном справочнике."""
    return randint(0, 9)


def return_office(session, office_id) -> Optional[Offices]:
    """Возвращает кабинет."""
    return session.query(Offices).filter(Offices.id == office_id).first()


async def check_order_today(session, office, today, callback_query):
    """
    Проверяем, есть ли уже заявка в выбранный кабинет на сегодня.
    """
    existing_order = session.execute(
        select(Order).where(
            and_(
                Order.office_id == office.id,
                Order.order_date == today
            )
        )
    ).scalars().first()

    if existing_order:
        # Если заявка уже существует, отправляем сообщение
        await callback_query.message.answer(
            f'Заявка для кабинета {office.abbr} на сегодня уже есть.'
        )
        return True
    return False


async def check_user_today(session, tg_account_id, today, callback_query):
    """
    Проверяем, есть ли уже заявка от этого пользователя на сегодня.
    """
    existing_user_order = session.execute(
        select(Order).where(
            and_(
                Order.tg_account_id == tg_account_id,  # Проверяем пользователя
                Order.order_date == today  # Проверяем дату
            )
        )
    ).scalars().first()

    if existing_user_order:
        # Если заявка уже существует, отправляем сообщение
        await callback_query.message.answer(
            'Отказано! Вы можете подать только одну заявку в день!'
        )
        return True
    return False
