import asyncio
import logging
import os
import re
from aiohttp import ClientSession, ClientError
from collections import defaultdict
from datetime import time, datetime
from http import HTTPStatus
from random import choice
from typing import Optional, Union
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from dotenv import load_dotenv
from sqlalchemy import insert, select

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from constants import (ADD_BOOTLES,
                       API_PHONEBOOK_AWAIT,
                       BOOTLES_ZERO,
                       CONSTANT_WATER_SUPPLY,
                       DELETE_BOOTLES,
                       ENCODING_IN_UTF,
                       ERROR_WHEN_GET_CODE,
                       FIRST_SECTION,
                       FIRST_SECTION_EMOJI,
                       GET_LIST,
                       GIVE_ME_ADDRESS_CODE,
                       HOLIDAY,
                       KEYBOARD_DELETE_FROM_SECONDS,
                       NOT_DAY_OFF,
                       OUR_TIMEZONE,
                       SECOND_SECTION,
                       SECOND_SECTION_EMOJI,
                       NEXT_WEEKDAY_EMOJI,
                       SECTION_MINUTES,
                       SORRY,
                       SUCCESSFUL_AUTH_IN_SMTP_STATUS_CODE)
from filters import (check_active_orders,
                     check_active_orders_for_current_tg_account,
                     check_tg_account_auth,
                     find_last_office,
                     joinedload_building_and_office_with_active_order,
                     joinedload_last_office_with_auth_tg_account,
                     transfers_orders_status_to_archive)
from models import Offices, Order
from users.users_fcm import RegistrationStates


load_dotenv()  # Загрузка переменных окружения:


def get_datetime_in_timezone_for_message(message_callback):
    """
    Получаем дататайм сообщения с учетом часового пояса.
    """
    message_date = message_callback.message.date
    return message_date.astimezone(ZoneInfo(OUR_TIMEZONE))


def is_workday_today(concrete_hour: Optional[int] = None) -> bool:
    """
    Проверяет, рабочий ли сегодня день и время (если передано).

    Upd (переменные живут в constants.py):
    - Добавлены праздничныме дни (в дальнейшем - придется расширять список).
    - Добавлены рабочие смены в выходные дни (тоже расширять для 2026, ...)

    args:
        - concrete_hour - указывается конкретный час

    Вернёт True если:
        - (нет hour) сегодня рабочий день
        - (указан hour) сегодня рабочий день и возможна доставка
    """
    today = datetime.now()  # сегодня
    today_weekday = today.isoweekday()  # 1-7 (пн-вс)

    # Проверяем праздничные дни (согласно производственного календаря-2025):
    if today.date() in HOLIDAY:
        return False

    # Проверяем день недели (учитываются рабочие смены в выходные дни):
    if today_weekday > 5 and today.date() not in NOT_DAY_OFF:
        return False  # если сб|вс

    if concrete_hour is None:
        return True  # если сегодня - будни, а время не учитывается.

    # Вернёт True, если сегодня будни и впереди есть доставка:
    return concrete_hour < SECOND_SECTION


def get_admins_account() -> Optional[list]:
    """
    Проверка наличия списка ТГ-аккаунтов админов в окружении.
    """
    if admins_in_env := os.getenv('admin_id'):
        admins_id = [int(admin) for admin in admins_in_env.split(',')]
        logging.info(f'Составлен список админов из env: {admins_id}')
        return admins_id

    logging.error('Проблемы со списком админов.')
    return None


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

    if not is_workday_today(order_time.hour):
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
    """Формирование сообщения с заявками до указанного часа."""
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
    result = await session.execute(check_tg_account_auth(tg_account))
    check_authorization = result.scalar_one_or_none()

    # Возвращаем True, если пользователь авторизован, иначе False
    return False if check_authorization is None else True


async def check_user_in_admins_list(trigger, built_in_msg=True) -> bool:
    """
    Проверяет, является ли Пользователь администратором.
    """
    if not (admins_id := get_admins_account()):
        return False
    if trigger.from_user.id not in admins_id:
        if built_in_msg:
            await trigger.answer('❌ Недостаточно прав')
        return False
    return True


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

            if response.status == HTTPStatus.CREATED:
                data = await response.json()  # данные
                code = str(data.get('number'))  # код
                logging.info(f'{user_in_chat} получил код {code}')
                # Сохраняем код в состоянии
                await state.update_data(code=code)
                await message.answer(GIVE_ME_ADDRESS_CODE)
                await state.set_state(RegistrationStates.waiting_for_code)
            else:
                await message.answer(ERROR_WHEN_GET_CODE)
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
            joinedload_last_office_with_auth_tg_account(message.chat.id)
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


async def return_last_order(session) -> Optional[Order]:
    """Возвращает крайний заказ."""
    last_order = await session.scalar(find_last_office())
    return last_order if last_order else None


async def return_bootles(session) -> Optional[int]:
    """Возвращает количество бутылей из крайнего заказа."""
    last_order = await return_last_order(session)
    if last_order is None:
        return None
    # Возвращаем количество бутылей, если заказ существует
    return last_order.bootles_left


async def return_sorry_if_no_bootles(
    session,
    message_elem,
    **kwargs
) -> bool:
    """Направляет сообщение с извинениями, если достигли минимума."""
    # Получаем кол-во бутылей в последнем заказе:
    if not (bootles_left_now := kwargs.get('bootles_left_now')):
        bootles_left_now = await return_bootles(session)

    # если кол-во существует (есть записи в базе) и кол-во бутылей меньше min:
    if bootles_left_now is not None and bootles_left_now <= BOOTLES_ZERO:
        await message_elem.answer(f'❌ {choice(SORRY)}')
        return True
    return False


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
    order = check_active_orders(office, today)
    result = await session.execute(order)
    existing_order = result.scalars().first()

    if existing_order:  # Если заявка уже существует, отправляем сообщение
        await callback_query.message.answer(
            '❌ Отказано!\n'
            f'Активная заявка для кабинета {office.abbr} уже есть.'
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
        check_active_orders_for_current_tg_account(tg_account_id, today)
    )
    existing_user_order = result.scalars().first()

    if existing_user_order:  # Если заявка уже существует
        await callback_query.message.answer(
            '❌ Отказано!\nВы можете подать только одну заявку в день!'
        )
        logging.info(f'{chat_user_id} пытался подать еще одну заявку')
        return True
    return False


async def create_new_order_in_db(
    session,
    office_id: int,
    tg_account_id: int,
    localized_time: datetime,
    bootles_left: int
) -> Order:
    """
    Формирует (создаёт) новую заявку для таблицы Order базы данных.
    """
    return await session.execute(
        insert(Order)
        .values(
            office_id=office_id,
            tg_account_id=tg_account_id,
            order_date=localized_time.date(),
            order_time=localized_time.time(),
            in_archive=False,
            bootles_left=bootles_left - 1
        )
        .returning(Order.id)
    )


async def collect_orders_for_interval(
    session, hour_find: Optional[int] = None
) -> Optional[list]:
    """
    Формируем список заявок по времени и выдает их список или ничего.
    """
    try:
        result = await session.execute(
            joinedload_building_and_office_with_active_order()
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
            # Формируем шапку блока:
            text_title = f'Объект: {building}'
            formatted_orders.append(f'{"-" * len(text_title)}\n{text_title}')

            # Формируем каждый блок:
            formatted_orders.extend(f'🫙 {office}' for office in offices)

        return formatted_orders

    except Exception as e:
        logging.error(
            f'Ошибка при формировании списка заявок: {e}', exc_info=True
        )
        await session.rollback()
        return None


async def parse_element_from_admin_message(
        message: Message,
        element: str,
        min_in_range: int,
        max_in_range: int
) -> Union[int, bool]:
    """
    Захватывает указанное админом в message количество элементов.
    """
    # Получение шаблона исходящего сообщения:
    text_in_message = {
        'hour': ('', 'час'),
        'bootles_up': (', чтобы привезли', 'бутылей сразу'),
        'bootles_down': (', чтобы увезли', 'бутылей сразу'),
    }

    # Поиск команды для паттерна re (можно расширить):
    command = {
        'hour': GET_LIST,
        'bootles_up': ADD_BOOTLES,  # админ добавляет бутыли (поступление)
        'bootles_down': DELETE_BOOTLES  # админ списывает бутыли
        # добавление команд
    }

    # Проверяем наличие элемента в ожидаемом словаре:
    if element not in text_in_message:
        await message.answer('❌ Неподдерживаемый тип элемента')
        return False

    first_part_msg, second_part_msg = text_in_message[element]

    # Проверяем соответствие указанного числа ожидаемому диапазону:
    pattern = fr'{command[element]}_(?P<{element}>\d+)$'
    element_in_message = re.search(pattern, message.text)

    if not element_in_message:
        await message.answer('❌ Некорректный формат введенного количества.')
        return False

    element_find = int(element_in_message.group(element))

    if element_find not in range(min_in_range, max_in_range + 1):
        await message.answer(
            f'❌ Где вы видели{first_part_msg} '
            f'{element_find} {second_part_msg}.'
        )
        return False

    return element_find


async def add_orgers_in_archive(session, hour):
    """
    Проставляет статус В АРХИВЕ заявкам после отправки сообщения админам.
    """
    await session.execute(transfers_orders_status_to_archive())
    await session.commit()


async def send_email(message):
    """
    Выполнение рассылки (отправка писем администраторам).
    """
    # Параметры сервера ММК:
    server = str(os.getenv('smtp_mmk_server'))
    port = int(os.getenv('smtp_mmk_port'))

    # Отправитель письма-рассылки:
    sender = str(os.getenv('sender'))
    login_name = str(os.getenv('login_water'))
    login = rf'hq\{login_name}'
    password = str(os.getenv('pass_water'))
    subject = 'Доставка воды'

    # Получение списка адресатов:
    recipient_email = str(os.getenv('recipient_address'))
    recipient_stack = recipient_email.split(',')

    # Создание объекта сообщения:
    msg = MIMEMultipart()
    msg['From'] = sender
    msg['Subject'] = subject
    msg.attach(MIMEText(message, 'plain', ENCODING_IN_UTF))

    try:
        server = smtplib.SMTP(host=server, port=port)

        # Проверка успешности авторизации на почтовом сервере:
        code_response, response = server.login(login, password)

        if code_response != SUCCESSFUL_AUTH_IN_SMTP_STATUS_CODE:
            logging.error(f'Ошибка при логине: {response}')
            return
        for email in recipient_stack:
            msg['To'] = email
            server.sendmail(sender, email, msg.as_string())
            logging.info(f'Письмо отправлено на почту {email}')
    except Exception as e:
        logging.info(f'Ошибка при отправке письма: {e}')
    finally:
        if server is not None:
            try:
                server.quit()
            except smtplib.SMTPServerDisconnected:
                logging.info('Подключение к серверу рассылки email разорвано.')


async def send_message_when_water_left(bot: Bot, bootles_left) -> None:
    """
    Направление уведомлений админам о заканчивающейся воде (по триггеру).
    """
    if bootles_left <= CONSTANT_WATER_SUPPLY:
        # Проверка наличия списка ТГ-аккаунтов админов в окружении:
        if not (admins_id := get_admins_account()):
            return

        # Отправляем сообщения в ТГ-аккаунты админам:
        for admin_id in admins_id:
            try:
                await bot.send_message(
                    admin_id,
                    f'Количество воды снизилось до {bootles_left} ед. '
                    'Необходимо оформить новую заявку на партию воды.'
                )
                logging.info(
                    'Админам направлено предупреждение об остатках воды.'
                )
            except Exception as e:
                logging.error(f'Ошибка отправки: {e}')


async def create_task_for_delete_message_after_delay(
        message: Message,
        delay: int = KEYBOARD_DELETE_FROM_SECONDS
):
    """Удаляет сообщение (в т.ч. с клавой через указанное количество секунд."""
    async def delete_message(
        message: Message,
        delay: int
    ):
        await asyncio.sleep(delay)
        await message.delete()

    asyncio.create_task(await delete_message(message, delay))
