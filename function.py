import logging
import os
import re
from aiohttp import ClientSession, ClientError
from collections import defaultdict
from datetime import time
from typing import Optional
from zoneinfo import ZoneInfo

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import and_, select, update
from sqlalchemy.orm import selectinload, joinedload

from constants import (API_PHONEBOOK_AWAIT,
                       GET_LIST,
                       FIRST_SECTION,
                       OUR_TIMEZONE,
                       SECOND_SECTION)
from models import Offices, Order, TgAccounts
from users.users_fcm import RegistrationStates


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


def create_user_attrs(obj) -> str:
    """Создание записи о пользователе вида «ID (name fullname)»."""
    chat = obj.from_user if isinstance(obj, CallbackQuery) else obj.chat
    return f'{chat.id} ({chat.first_name} {chat.full_name})'


def get_id_from_callback_query(callback_query, part: str) -> int:
    """
    Возвращает id кабинета из callback запроса.
    """
    return int(str(callback_query.data).replace(part, ''))


async def check_authorization(session, message) -> bool:
    """
    Проверяет, авторизован ли Пользователь.
    """
    tg_account = str(message.chat.id)  # Аккаунт из запроса

    # Проверяем, есть ли запись в таблице TgAccounts
    result = await session.execute(
        select(TgAccounts).where(
            TgAccounts.account == tg_account,
            TgAccounts.blocked == False
        )
    )
    check_authorization = result.scalar_one_or_none()

    # Возвращаем True, если пользователь авторизован, иначе False
    return False if check_authorization is None else True


async def generate_code_for_registration_and_waiting_answer(
    message: Message,
    state: FSMContext,
    external_resource_url: str,
):
    """
    Проверяе статус запроса к внешнему ресурсу, сохраняет код и ждет ответа.
    """
    async with ClientSession() as http_session:
        async with http_session.post(
            external_resource_url, timeout=API_PHONEBOOK_AWAIT
        ) as response:

            # Логгирую запрос пользователя:
            user_in_chat = create_user_attrs(message)
            logging.info(
                f'{user_in_chat} запросил обновление кода на сайте АТУ.'
            )

            if response.status == 201:
                data = await response.json()  # данные
                code = str(data.get('number'))  # код
                logging.info(f'{user_in_chat} получил код {code}')
                # Сохраняем код в состоянии
                await state.update_data(code=code)
                await message.answer('Введите код из системы:')
                await state.set_state(RegistrationStates.waiting_for_code)
            else:
                await message.answer('Ошибка получения кода')
                logging.error(f'Ошибка получения кода для {user_in_chat}')


async def start_registration(message: Message, state: FSMContext):
    """
    Запускает регистрацию (генерирует и сравнивает коды).
    """
    url_tg_code = str(os.getenv('url_tg_code'))
    try:
        # Запрашиваем код через API (выполняется POST запрос в справочник):
        await generate_code_for_registration_and_waiting_answer(
            message=message,
            state=state,
            external_resource_url=url_tg_code
        )

    except ClientError as e:
        await message.answer(f'Ошибка подключения: {e}')
        logging.error(f'Ошибка в {__name__} - {e}')


async def get_favorite_office(session, message) -> Optional[Offices]:
    """
    Возвращает Кабинет последнего Заказа (если Заказ для конкретного ТГ-А был).

    Проверено!
    """
    try:
        result = await session.execute(
            select(TgAccounts)
            .where(TgAccounts.account == str(message.chat.id))
            .options(joinedload(TgAccounts.office))  # Жадная загрузка офиса
        )

        user_account = result.scalar_one_or_none()

        print(f'Проверяю тип {type(user_account.office)}')  # Проверка

        # Возвращаем связанный офис (если есть):
        return user_account.office if user_account else None

    except Exception as e:
        logging.error(f'Ошибка при получении кабинета: {e}', exc_info=True)
        return None


async def return_office(session, office_id) -> Offices:
    """Получив office_id - возвращает экземпляр Кабинета."""
    office = select(Offices).where(Offices.id == office_id)
    result = await session.execute(office)
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
    # Получаем дату с учетом часового пояса:
    localized_time = get_datetime_in_timezone_for_message(callback_query)
    today = localized_time.date()  # Извлекаем дату
    chat_user_id = create_user_attrs(callback_query.message)

    # Как правильно получать записи из БД в асинхроне?!!!!!!!!!!!!!!!!!!!!!!!!!! Таких у меня дофига!
    order = select(Order).where(
        and_(
            Order.office_id == office.id,
            Order.order_date == today
        )
    )
    result = await session.execute(order)
    existing_order = result.scalars().first()

    if existing_order:  # Если заявка уже существует, отправляем сообщение
        await callback_query.message.answer(
            '❌ Отказано!\n'
            f'Заявка для кабинета {office.abbr} на сегодня уже есть.'
        )
        logging.info(
            f'{chat_user_id} пытался создать заявку для {office}'
            ', а она уже есть'
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
    chat_user_id = create_user_attrs(callback_query.message)

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
            '❌ Отказано!\nВы можете подать только одну заявку в день!'
        )
        logging.info(f'{chat_user_id} пытался подать еще одну заявку')
        return True
    return False


async def collect_orders_for_interval(session, hour_find) -> Optional[list]:
    """
    Формируем список заявок по времени и выдает их список или ничего.
    """
    try:
        result = await session.execute(
            select(Order)
            .where(
                and_(
                    Order.order_time < time(hour_find, 0),
                    Order.in_archive == False
                )
            ).options(
                joinedload(Order.office).joinedload(Offices.building)
            )
        )
        orders = result.scalars().all()

        if not orders:
            logging.info('Заявок пока нет')
            return None

        buildings = defaultdict(list)

        for order in orders:
            # Проверка на существование связанных объектов
            if order.office and order.office.building:
                building_name = order.office.building.name.upper()
                buildings[building_name].append(str(order.office))

        formatted_orders = []
        for building, offices in sorted(buildings.items()):
            formatted_orders.append(('-' * 41) + '\n' + f'Здание: {building}')
            formatted_orders.extend(f'🫙 {office}' for office in offices)

        return formatted_orders

    except Exception as e:
        logging.error(
            f'Ошибка при формировании списка заявок: {e}', exc_info=True
        )
        await session.rollback()
        return None


async def parse_hours_from_admin_message(message):
    """
    Захватывает указанный админом в message час для формирования списка заявок.
    """
    pattern = fr'{GET_LIST}_(?P<hour>\d+)$'
    hour_in_message = re.search(pattern, message.text)

    if not hour_in_message:
        await message.answer('❌ Некорректный формат при отправке команды.')
        return False

    hour_find = int(hour_in_message.group('hour'))

    if hour_find not in range(0, 25):
        await message.answer(f'❌ Где вы видели {hour_find} час.')
        return False
    return hour_find


async def add_orgers_in_archive(session, hour):
    """
    Проставляет статус В АРХИВЕ заявкам после отправки сообщения админам.
    """
    orders_in_archive = update(Order).where(
        and_(
            Order.order_time < time(hour, 0),
            Order.in_archive == False
        )
    ).values(in_archive=True)

    await session.execute(orders_in_archive)
    await session.commit()
