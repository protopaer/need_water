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


async def get_datetime_in_timezone_for_message(message_callback):
    """
    Получаем дататайм сообщения с учетом часового пояса.
    """
    message_date = message_callback.message.date
    return message_date.astimezone(ZoneInfo(OUR_TIMEZONE))


async def check_order_today(session, office, callback_query):
    """
    Проверяем, есть ли уже заявка в выбранный кабинет на сегодня.
    """
    # Получаем дату с учетом часового пояса
    localized_time = await get_datetime_in_timezone_for_message(callback_query)
    today = localized_time.date()  # Извлекаем дату

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
            'Отказано!\n'
            f'Заявка для кабинета {office.abbr} на сегодня уже есть.'
        )
        return True
    return False


async def check_user_today(session, tg_account_id, callback_query):
    """
    Проверяем, есть ли уже заявка от этого Пользователя на сегодня.
    """
    # Получаем дату с учетом часового пояса
    localized_time = await get_datetime_in_timezone_for_message(callback_query)
    today = localized_time.date()  # Извлекаем дату

    existing_user_order = session.execute(
        select(Order).where(
            and_(
                Order.tg_account_id == tg_account_id,  # Проверяем пользователя
                Order.order_date == today
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
    Определяем время обработки заказа для подготовки ответа Пользователю.
    """
    order_time = localized_time.time()

    if order_time < time(FIRST_SECTION, 0):
        return f'в {FIRST_SECTION} часов'
    elif time(FIRST_SECTION, 0) <= order_time < time(SECOND_SECTION, 0):
        return f'в {SECOND_SECTION} часов'
    else:
        return f'на следующий рабочий день в {FIRST_SECTION} часов'
