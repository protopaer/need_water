import asyncio
import os
from typing import Optional
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import insert
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession

from constants import FIRST_SECTION, GET_LIST, OUR_TIMEZONE, SECOND_SECTION
from models import engine, TgAccounts, Order
from keyboards import (create_all_offices_keyboard, confirm_keyboard,
                       remove_keyboard)
from function import (add_orgers_in_archive, check_office_exists,
                      check_order_today, check_user_today,
                      collect_orders_for_interval, format_orders_message,
                      get_datetime_in_timezone_for_message,
                      get_slot_order, parse_hours_from_admin_message,
                      return_office, string_generate)


# Инициализация бота и диспетчера:
TOKEN: Optional[str] = os.getenv('bot_token')
dp = Dispatcher()

# Планировщик
scheduler = AsyncIOScheduler()

# Фабрика асинхронных сессий
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def on_startup(bot: Bot):
    """
    Настройка расписания с действиями при запуске бота.
    """
    scheduler.add_job(
        send_interval_message,
        CronTrigger(hour=FIRST_SECTION, minute=0, timezone=OUR_TIMEZONE),
        args=[bot, FIRST_SECTION],
        id='first_section'
    )
    scheduler.add_job(
        send_interval_message,
        CronTrigger(hour=SECOND_SECTION, minute=0, timezone=OUR_TIMEZONE),
        args=[bot, SECOND_SECTION],
        id='second_section'
    )
    scheduler.start()
    print('Планировщик стартовал!')


async def send_interval_message(bot: Bot, hour: int) -> None:
    """
    Отправляет сообщения администраторам для указанного интервала.
    """
    async with AsyncSessionLocal() as session:
        today = datetime.now().isoweekday()  # Находит день недели для сегодня.
        if today < 6 and hour < SECOND_SECTION:
            try:
                # Получаем данные о заказах для указанного интервала
                orders = await collect_orders_for_interval(session, hour)
                message_text = format_orders_message(hour, orders)

                # Отправляем сообщения администраторам:
                admins_id = list(map(int, os.getenv('admin_id').split(',')))
                for admin_id in admins_id:
                    await bot.send_message(admin_id, message_text)

                # Чистим базу (проставляем статус - в архиве):
                await add_orgers_in_archive(session, hour)

            except Exception as e:
                print(
                    f'Ошибка в send_interval_message для интервала {hour}: {e}'
                )
                await session.rollback()
        # TODO может быть здесь надо проставить сценарий для вечера пятницы
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!


async def scheduled_message(bot: Bot):
    """
    Отправка сообщения админам/подсобникам по расписанию.
    """
    async with AsyncSessionLocal() as session:
        try:
            first_interval_orders = (
                await collect_orders_for_interval(session, FIRST_SECTION)
            )
            second_interval_orders = (
                await collect_orders_for_interval(session, SECOND_SECTION)
            )

            message_text1 = format_orders_message(
                FIRST_SECTION, first_interval_orders
            )
            message_text2 = format_orders_message(
                SECOND_SECTION, second_interval_orders
            )

            # Получаем список администраторов:
            admins_id = list(map(int, os.getenv('admin_id').split(',')))
            for admin_id in admins_id:
                try:
                    await bot.send_message(admin_id, message_text1)
                    await bot.send_message(admin_id, message_text2)
                except Exception as e:
                    print(f'Ошибка отправки: {e}')
        except Exception as e:
            print(f'Ошибка в scheduled_message: {e}')


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
    async with AsyncSessionLocal() as session:
        # Проверяем авторизацию пользователя
        keyboard = await create_all_offices_keyboard(message, session)

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
        async with AsyncSessionLocal() as session:
            # Добавляем запись в таблицу TgAccounts:
            await session.execute(
                insert(TgAccounts).values(
                    account=str(message.chat.id),
                    blocked=False
                )
            )
            await session.commit()

        keyboard = await create_all_offices_keyboard(message, session)

        # Сбрасываем состояние
        await state.clear()
        await message.answer(
                'Выберите Ваш кабинет:',
                reply_markup=keyboard
            )
    else:
        await message.answer('Неверный код.')


@dp.callback_query(lambda c: c.data.startswith('button'))
async def process_callback_button(callback_query: CallbackQuery) -> None:
    """
    Обработчик нажатия на кнопку кабинета.

    Появляется, когда авторизованный пользователь нажан на кнопку кабинета.
    """
    office_id = int(callback_query.data.replace('button', ''))  # ID кабинета

    async with AsyncSessionLocal() as session:
        office = await return_office(session, office_id)

        # Проверяем, существует ли кабинет (TODO сомневаюсь, что это надо)
        if not await check_office_exists(callback_query, office):
            return  # Если кабинет не найден, завершаем выполнение

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

    async with AsyncSessionLocal() as session:
        office = await return_office(session, office_id)

        # TODO сомневаюсь, что это надо
        # Проверяем, существует ли кабинет
        if not await check_office_exists(callback_query, office):
            return  # Если кабинет не найден, завершаем выполнение

        # Удаляем клавиатуру после нажатия
        await remove_keyboard(callback_query.message)

        localized_time = (
            get_datetime_in_timezone_for_message(callback_query)
        )

        if await check_user_today(session, tg_account_id, callback_query):
            return

        if await check_order_today(session, office, callback_query):
            return

        # Создаем новую «заявку на воду» в таблице Order:
        await session.execute(
            insert(Order).values(
                office_id=office_id,
                tg_account_id=tg_account_id,
                order_date=localized_time.date(),
                order_time=localized_time.time(),
                in_archive=False
            )
        )
        await session.commit()

        order_in_time = get_slot_order(localized_time)

        # Отправляем подтверждение пользователю
        await callback_query.message.answer(
            f'Заказ воды для {office.abbr} создан.\n'
            f'Вода можна пить прям точна {order_in_time}!\n'
            'Ожидайте…'
        )


@dp.callback_query(lambda c: c.data == 'cancel')
async def process_cancel_callback(callback_query: CallbackQuery) -> None:
    """
    Обработчик отмены выбора кабинета.
    """
    await remove_keyboard(callback_query.message)
    await callback_query.message.answer('Выбор кабинета отменен.')


@dp.message(lambda message: message.text.startswith(f'{GET_LIST}_'))
async def list_orders_handler(message: Message) -> None:
    """
    Обработка команды админа направить список заявок до указанного часа.
    """
    async with AsyncSessionLocal() as session:

        hour_find = await parse_hours_from_admin_message(message)
        if not hour_find:
            return

        orders_list = await collect_orders_for_interval(session, hour_find)
        text_in_message = format_orders_message(hour_find, orders_list)

        await message.answer(text_in_message)


# Run the bot
async def main() -> None:
    bot = Bot(token=TOKEN)
    await on_startup(bot)
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
