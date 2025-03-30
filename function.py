import asyncio
import logging
import os
import re
from aiohttp import ClientSession, ClientError
from collections import defaultdict
from datetime import time, datetime
from email.message import EmailMessage
from typing import Optional
from zoneinfo import ZoneInfo

import aiosmtplib
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from dotenv import load_dotenv
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import joinedload

from constants import (API_PHONEBOOK_AWAIT,
                       GET_LIST,
                       FIRST_SECTION,
                       FIRST_SECTION_EMOJI,
                       GIVE_ME_ADDRESS_CODE,
                       OUR_TIMEZONE,
                       SECOND_SECTION,
                       SECOND_SECTION_EMOJI,
                       NEXT_WEEKDAY_EMOJI,
                       SECTION_MINUTES)
from models import Offices, Order, TgAccounts
from users.users_fcm import RegistrationStates


load_dotenv()


def get_datetime_in_timezone_for_message(message_callback):
    """
    Получаем дататайм сообщения с учетом часового пояса.
    """
    message_date = message_callback.message.date
    return message_date.astimezone(ZoneInfo(OUR_TIMEZONE))


def get_workday_or_not(hour=None, last_delivery=SECOND_SECTION) -> bool:
    """
    Проверяет, рабочий ли сегодня день и время (если передано).

    Вернёт True если:
        - (нет hour) сегодня рабочий день
        - (указан hour) сегодня рабочий день и возможна доставка
    """
    today = datetime.now().isoweekday()  # 1-7 (пн-вс)
    is_workday = today < 6  # Пн-Пт

    if not is_workday:
        return False  # False если сегодня выходной

    if hour is None:
        return True  # True если сегодня будни, а время не учитывается

    return hour < last_delivery  # True если будни и впереди есть доставка.


def get_slot_order(localized_time: datetime):
    """
    Определяет время обработки заказа для подготовки ответа пользователю.

    Args:
        localized_time: Время заказа в виде datetime объекта.

    Returns:
        Кортеж из двух элементов:
        - emoji (📅, 🕙 или 🕐)
        - текст с описанием времени доставки

    Примеры возвращаемых значений:
        ('📅', 'на следующий рабочий день в 10 часов')
        ('🕙', 'в 10 часов')
        ('🕐', 'в 13 часов')
    """
    order_time = localized_time.time()

    if not get_workday_or_not(order_time.hour):
        return (
            NEXT_WEEKDAY_EMOJI,
            f'на следующий рабочий день в {FIRST_SECTION} часов'
        )
    if order_time < time(FIRST_SECTION, SECTION_MINUTES):
        return (FIRST_SECTION_EMOJI, f'в {FIRST_SECTION} часов')
    elif (
        time(FIRST_SECTION, SECTION_MINUTES)
        <= order_time
        < time(SECOND_SECTION, SECTION_MINUTES)
    ):
        return (SECOND_SECTION_EMOJI, f'в {SECOND_SECTION} часов')


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
                await message.answer(GIVE_ME_ADDRESS_CODE)
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

    # Как правильно получать записи из БД в асинхроне?!?!?! Таких у меня дофига!
    order = select(Order).where(
        and_(
            Order.office_id == office.id,
            or_(
                Order.in_archive == False,  # <-- проверяет выходный
                and_(
                    Order.order_date == today,  # <-- проверяет сегодня
                    Order.in_archive == True
                )
            )
        )
    )
    result = await session.execute(order)
    existing_order = result.scalars().first()

    if existing_order:  # Если заявка уже существует, отправляем сообщение
        await callback_query.message.answer(
            '❌ Отказано!\n'
            f'Активная заявка для кабинета {office.abbr} уже есть.'
        )
        # TODO: добавить кнопку назад к выбору кабинета (подумать, надо ли)!!!!!
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


async def send_email(message):
    """
    Выполнение рассылки (отправка писем администраторам).
    """
    # Загрузка из .env:
    smtp_mmk_server = str(os.getenv('smtp_mmk_server'))
    smtp_mmk_port = int(os.getenv('smtp_mmk_port'))

    sender_email = str(os.getenv('sender'))
    sender_password = str(os.getenv('pass_water'))
    subject = 'Доставка воды'

    # Получение списка адресатов:
    recipient_email = str(os.getenv('recipient_address'))
    recipient_stack = recipient_email.split(',')

    # Создаем задачи для каждого получателя
    tasks = []
    for email in recipient_stack:
        try:
            msg = EmailMessage()
            msg['From'] = sender_email
            msg['To'] = email
            msg['Subject'] = subject
            msg.set_content(message)

            # Создаем задачу для отправки
            task = asyncio.create_task(
                send_single_email(
                    msg=msg,
                    sender_email=sender_email,
                    password=sender_password,
                    hostname=smtp_mmk_server,
                    port=smtp_mmk_port,
                    recipient=email
                )
            )
            tasks.append(task)
        except Exception as e:
            logging.error(f'Ошибка при подготовке письма для {email}: {e}')

    # Ожидаем завершения всех задач:
    await asyncio.gather(*tasks, return_exceptions=True)


async def send_single_email(
        msg, sender_email, password, hostname, port, recipient
):
    """
    Отправка письма администратору.
    """
    try:
        await aiosmtplib.send(
            msg,
            sender=sender_email,
            hostname=hostname,
            port=port,
            username=sender_email,
            password=password,
            recipients=[recipient],
            use_tls=True  # Использование шифрование
        )
        logging.info(f'Письмо {recipient} успешно отправлено!')
    except Exception as e:
        logging.error(f'Ошибка при отправке письма {recipient}: {e}')
