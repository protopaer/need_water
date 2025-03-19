import asyncio
import os
from datetime import date, time
import re
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from sqlalchemy import and_, insert, select
from sqlalchemy.orm import Session

from constants import GET_LIST
from models import Offices, engine, TgAccounts, Order
from keyboards import (create_all_offices_keyboard, confirm_keyboard,
                       remove_keyboard)
from function import (check_order_today, check_user_today, collect_orders_for_interval,
                      get_datetime_in_timezone_for_message, get_slot_order, parse_hours_from_admin_message,
                      return_office, string_generate)


# Инициализация бота и диспетчера:
TOKEN: Optional[str] = os.getenv('bot_token')
dp = Dispatcher()


# Состояния для FSM
class RegistrationStates(StatesGroup):
    waiting_for_code = State()  # Состояние ожидания ввода кода


@dp.message(Command("start"))
async def command_start_handler(
    message: Message, state: FSMContext
) -> None:
    """
    Стартовая страница (страница авторизации или выбора кабинета).
    """
    with Session(engine) as session:
        # Проверяем авторизацию пользователя
        keyboard = create_all_offices_keyboard(message, session)

        if keyboard:
            # Если пользователь авторизован, показываем кнопки
            await message.answer(
                "Выберите кабинет:",
                reply_markup=keyboard
            )
        else:
            # Генерируем случайный код и сохраняем его в состоянии
            code = string_generate()  # рандом-код
            await state.update_data(code=code)
            await message.answer(
                f'(Заглушка) Укажите код в справочнике: {code}'
            )
            await state.set_state(RegistrationStates.waiting_for_code)


@dp.message(RegistrationStates.waiting_for_code)
async def process_code(message: Message, state: FSMContext) -> None:
    """
    (Заглушка) Обработчик ввода кода авторизации.
    """
    user_code = message.text  # Код, введенный пользователем
    data = await state.get_data()  # Получаем сохраненный код из состояния
    generated_code = str(data.get('code'))  # Преобразуем в строку

    if user_code == generated_code:
        # Если код верный, добавляем запись в таблицу TgAccounts
        with Session(engine) as session:
            # Добавляем запись в таблицу TgAccounts:
            session.execute(
                insert(TgAccounts).values(
                    account=str(message.chat.id),
                    blocked=False
                )
            )
            session.commit()

        keyboard = create_all_offices_keyboard(message, session)

        # Сбрасываем состояние
        await state.clear()
        await message.answer(
                'Выберите Ваш кабинет:',
                reply_markup=keyboard
            )
    else:
        await message.answer('Неверный код.')


async def check_office_exists(callback_query: CallbackQuery, office) -> bool:
    """
    Проверяет, существует ли кабинет.

    Найден - возвращает True.
    Нет - отправляет сообщение об ошибке и возвращает False.
    """
    if not office:
        await callback_query.message.answer('Кабинет пропал.')
        return False
    return True


@dp.callback_query(lambda c: c.data.startswith('button'))
async def process_callback_button(callback_query: CallbackQuery) -> None:
    """
    Обработчик нажатия на кнопку кабинета.

    Появляется, когда авторизованный пользователь нажан на кнопку кабинета.
    """
    office_id = int(callback_query.data.replace('button', ''))  # ID кабинета

    with Session(engine) as session:
        office = return_office(session, office_id)

        # Проверяем, существует ли кабинет
        if not await check_office_exists(callback_query, office):
            return  # Если кабинет не найден, завершаем выполнение

        # Удаляем клавиатуру после нажатия
        await remove_keyboard(callback_query.message)

        # Если найден - отправляем запрос на подтверждение:
        await callback_query.message.answer(
            f'Выбран кабинет {office.abbr}. Всё верно?',
            reply_markup=confirm_keyboard(office_id)
        )


@dp.callback_query(lambda c: c.data.startswith('confirm_'))
async def process_confirm_callback(callback_query: CallbackQuery) -> None:
    """
    Обработчик подтверждения выбора кабинета.
    """
    office_id = int(callback_query.data.replace('confirm_', ''))  # ID кабинета
    tg_account_id = callback_query.from_user.id  # ID пользователя

    with Session(engine) as session:
        office = return_office(session, office_id)

        # Проверяем, существует ли кабинет
        if not await check_office_exists(callback_query, office):
            return  # Если кабинет не найден, завершаем выполнение

        # Удаляем клавиатуру после нажатия
        await remove_keyboard(callback_query.message)

        localized_time = (
            await get_datetime_in_timezone_for_message(callback_query)
        )

        if await check_user_today(session, tg_account_id, callback_query):
            return

        if await check_order_today(session, office, callback_query):
            return

        # Создаем новую «заявку на воду» в таблице Order:
        session.execute(
            insert(Order).values(
                office_id=office_id,
                tg_account_id=tg_account_id,
                order_date=localized_time.date(),
                order_time=localized_time.time(),
                in_archive=False
            )
        )
        session.commit()

        order_in_time = get_slot_order(localized_time)

        # Отправляем подтверждение пользователю
        await callback_query.message.answer(
            f'Заказ воды для {office.abbr} создан.\n'
            f'Обработка {order_in_time}!\n'
            'Ожидайте…'
        )


@dp.callback_query(lambda c: c.data == 'cancel')
async def process_cancel_callback(callback_query: CallbackQuery) -> None:
    """
    Обработчик отмены выбора кабинета.
    """

    # Удаляем клавиатуру после нажатия
    await remove_keyboard(callback_query.message)

    await callback_query.message.answer('Выбор кабинета отменен.')


@dp.message(lambda message: message.text.startswith(f'{GET_LIST}_'))
async def list_orders_handler(message: Message) -> None:
    """
    Обработчик команды /list_orders. Выводит список заявок для отрезка времени.
    """
    with Session(engine) as session:

        hour_find = await parse_hours_from_admin_message(message)
        if not hour_find:
            return

        orders_list = await collect_orders_for_interval(session, hour_find)

        if not orders_list:
            # Если заявок нет, отправляем сообщение
            await message.answer(
                f'Заявок, созданных до {hour_find}, не найдено.'
            )
            return

        # Отправляем список заявок пользователю
        await message.answer(
            f'Список заявок, созданных до {hour_find} часов:\n'
            + ('-' * 41) + '\n'
            + '\n'.join(orders_list)
        )


# Run the bot
async def main() -> None:
    bot = Bot(token=TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
