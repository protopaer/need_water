import re
from collections import defaultdict
from datetime import time
from random import randint
from typing import Optional
from zoneinfo import ZoneInfo

from aiogram.types import CallbackQuery
from sqlalchemy import and_, select, update
from sqlalchemy.orm import selectinload

from constants import GET_LIST, FIRST_SECTION, OUR_TIMEZONE, SECOND_SECTION
from models import Offices, Order


def string_generate():
    """Генерирует случайное число в телефонном справочнике."""
    return randint(0, 9)


def get_datetime_in_timezone_for_message(message_callback):
    """
    Получаем дататайм сообщения с учетом часового пояса.
    """
    message_date = message_callback.message.date
    return message_date.astimezone(ZoneInfo(OUR_TIMEZONE))


def get_slot_order(localized_time):
    """
    Определяем время обработки заказа для подготовки ответа Пользователю.
    """
    order_time = localized_time.time()

    if order_time < time(FIRST_SECTION, 0):
        return f'в {FIRST_SECTION} часов'
    elif time(FIRST_SECTION, 0) <= order_time < time(SECOND_SECTION, 0):
        return f'в {SECOND_SECTION} часов'
    else:
        return f'на следующий рабочий день в {FIRST_SECTION} часов'


def format_orders_message(hour: int, orders: Optional[list]) -> str:
    """Формирование сообщения с заявками до указанного часа"""
    if orders:
        header = f'Список заявок, созданных до {hour} часов:\n'
        message = header + '\n'.join(orders)
    else:
        message = f'Заявок, созданных до {hour}, не найдено.'

    return message


async def return_office(session, office_id) -> Optional[Offices]:
    """Получив office_id - возвращает экземпляр Кабинета."""
    result = await session.execute(
        select(Offices).where(Offices.id == office_id)
    )
    return result.scalars().first()


async def check_office_exists(callback_query: CallbackQuery, office) -> bool:
    """
    Проверяет, существует ли кабинет.

    Найден - возвращает True.
    Нет - отправляет сообщение об ошибке и возвращает False.
    """
    # TODO сомневаюсь, что это надо
    if not office:
        await callback_query.message.answer('Кабинет пропал.')
        return False
    return True


async def check_order_today(session, office, callback_query):
    """
    Проверяем, есть ли уже заявка в выбранный кабинет на сегодня.
    """
    # Получаем дату с учетом часового пояса
    localized_time = get_datetime_in_timezone_for_message(callback_query)
    today = localized_time.date()  # Извлекаем дату

    result = await session.execute(
        select(Order).where(
            and_(
                Order.office_id == office.id,
                Order.order_date == today
            )
        )
    )
    existing_order = result.scalars().first()

    if existing_order:  # Если заявка уже существует, отправляем сообщение
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
    localized_time = get_datetime_in_timezone_for_message(callback_query)
    today = localized_time.date()  # Извлекаем дату

    result = await session.execute(
        select(Order).where(
            and_(
                Order.tg_account_id == tg_account_id,  # Проверяем пользователя
                Order.order_date == today
            )
        )
    )
    existing_user_order = result.scalars().first()

    if existing_user_order:  # Если заявка уже существует
        await callback_query.message.answer(
            'Отказано!\nВы можете подать только одну заявку в день!'
        )
        return True
    return False


async def collect_orders_for_interval(session, hour_find) -> Optional[list]:
    """
    Формируем список заявок по времени и выдает их список или ничего.
    """
    result = await session.execute(
        select(Order)
        .where(
            and_(
                Order.order_time < time(hour_find, 0),
                Order.in_archive == False
            )
        ).options(selectinload(Order.office).selectinload(Offices.build))
    )
    orders = result.scalars().all()

    if not orders:
        return None

    buildings = defaultdict(list)

    for order in orders:
        office = await session.get(Offices, order.office_id)
        if office and office.build:
            building_name = office.build.name.upper()
            buildings[building_name].append(office.__repr__())

    formatted_orders = []
    for building, offices in sorted(buildings.items()):
        formatted_orders.append(('-' * 41) + '\n' + f'Здание: {building}')
        for office in offices:
            formatted_orders.append(f' - {office}')
    return formatted_orders


async def parse_hours_from_admin_message(message):
    """
    Захватывает указанный админом в message час для формирования списка заявок.
    """
    pattern = fr'{GET_LIST}_(?P<hour>\d+)$'
    hour_in_message = re.search(pattern, message.text)

    if not hour_in_message:
        await message.answer('Некорректный формат при отправке команды.')
        return False

    hour_find = int(hour_in_message.group('hour'))

    if hour_find not in range(0, 25):
        await message.answer(f'Где вы видели {hour_find} час.')
        return False
    return hour_find


async def add_orgers_in_archive(session, hour):
    """
    Проставляет статус В АРХИВЕ заявкам после отправки сообщения админам.
    """
    await session.execute(
        update(Order).where(
            and_(
                Order.order_time < time(hour, 0),
                Order.in_archive == False
            )
        ).values(in_archive=True)
    )

    # Сохраняем изменения в базе данных
    await session.commit()
