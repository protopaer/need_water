from datetime import time
from random import randint
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select

from constants import FIRST_SECTION, OUR_TIMEZONE, SECOND_SECTION
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
                Order.order_date == (
                    callback_query.message.date.astimezone().date()
                )
            )
        )
    ).scalars().first()

    if existing_order:
        # Если заявка уже существует, отправляем сообщение
        await callback_query.message.answer(
            'Отказано!\n'
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
                Order.order_date == (
                    callback_query.message.date.astimezone().date()
                )
            )
        )
    ).scalars().first()

    if existing_user_order:
        # Если заявка уже существует, отправляем сообщение
        await callback_query.message.answer(
            'Отказано!\nВы можете подать только одну заявку в день!'
        )
        return True
    return False


def get_slot_order(localized_time):
    """"
    Определяем время обработки заказа.
    """
    order_time = localized_time.time()

    if order_time < time(FIRST_SECTION, 0):
        return f'в {FIRST_SECTION} часов!'
    elif time(FIRST_SECTION, 0) <= order_time < time(SECOND_SECTION, 0):
        return f'в {SECOND_SECTION} часов.'
    else:
        return 'на следующий рабочий день.'


async def get_datetime_in_timezone_for_message(message_callback):
    """
    Получаем дататайм сообщения с учетом часового пояса.
    """
    message_date = message_callback.message.date
    return message_date.astimezone(ZoneInfo(OUR_TIMEZONE))
