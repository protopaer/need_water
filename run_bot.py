import aiohttp
import asyncio
import logging
import os
from datetime import datetime
# from typing import Optional

from aiogram import Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import insert, update

from bot_logging import configure_logging
from constants import (FIRST_SECTION, OUR_TIMEZONE, SECOND_SECTION,
                       API_PHONEBOOK_AWAIT)
from function import (add_orgers_in_archive, check_office_exists,
                      check_order_today, check_user_today,
                      collect_orders_for_interval, create_user_attrs,
                      format_orders_message,
                      get_datetime_in_timezone_for_message,
                      get_slot_order,
                      return_office)
from keyboards import (create_all_builds_keyboard, create_all_offices_keyboard,
                       confirm_keyboard, remove_keyboard)
from models import TgAccounts, Order, Base
from config import AsyncSessionLocal, dp, engine, scheduler
from admins.admins_action import url_for_add_office, url_for_get_list
from users.users_fcm import RegistrationStates


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
    logging.info('Планировщик стартовал!')


async def send_interval_message(bot: Bot, hour: int) -> None:
    """
    Отправляет сообщения администраторам для указанного интервала.
    """
    async with AsyncSessionLocal() as session:
        today = datetime.now().isoweekday()  # Находит день недели для сегодня.
        if today < 6 and hour < SECOND_SECTION + 1:  # костыль с 1!!!!!!!!!!!!!!!
            try:
                # Получаем данные о заказах для указанного интервала
                orders = await collect_orders_for_interval(session, hour)
                message_text = format_orders_message(hour, orders)

                # Отправляем сообщения администраторам:
                admins_id = list(
                    map(int, str(os.getenv('admin_id')).split(','))
                )
                for admin_id in admins_id:
                    await bot.send_message(admin_id, message_text)
                    logging.info(
                        f'Отправка сообщения выполнена для админа: {admin_id}'
                    )

                # Чистим базу (проставляем статус - в архиве):
                await add_orgers_in_archive(session, hour)
                logging.info('Заявки переведены в архив')

            except Exception as e:
                logging.error(
                    f'Ошибка в send_interval_message для интервала {hour}: {e}'
                )
                await session.rollback()
                logging.info('Сессия откатилась назад')
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
            admins_id = list(
                map(int, str(os.getenv('admin_id')).split(','))
                )
            for admin_id in admins_id:
                try:
                    await bot.send_message(admin_id, message_text1)
                    logging.info(f'Письма в {FIRST_SECTION} ушли')
                    await bot.send_message(admin_id, message_text2)
                    logging.info(f'Письма в {SECOND_SECTION} ушли')
                except Exception as e:
                    logging.error(f'Ошибка отправки: {e}')
        except Exception as e:
            logging.error(f'Ошибка в scheduled_message: {e}')


@dp.message(Command('start'))
async def command_start_handler(
    message: Message, state: FSMContext
) -> None:
    """
    Стартовая страница (страница авторизации или выбора кабинета).
    """
    async with AsyncSessionLocal() as session:
        # Проверяем авторизацию пользователя
        keyboard = await create_all_builds_keyboard(session, message=message)

        if keyboard:
            # Если пользователь авторизован, показываем кнопки
            await message.answer(
                'Повторить ⭐ заказ или начнём с выбора здания:',
                reply_markup=keyboard
            )
        else:
            url_tg_code = str(os.getenv('url_tg_code'))
            try:
                # Запрашиваем код через API
                # (выполняется POST запрос в справочник):
                async with aiohttp.ClientSession() as http_session:
                    async with http_session.post(
                        url_tg_code, timeout=API_PHONEBOOK_AWAIT
                    ) as response:
                        user_in_chat = create_user_attrs(message)
                        logging.info(
                            f'{user_in_chat} '
                            'запросил обновление кода на сайте АТУ.'
                        )
                        if response.status == 201:
                            data = await response.json()  # данные
                            code = str(data.get('number'))  # код
                            logging.info(f'{user_in_chat} получил код {code}')
                            # Сохраняем код в состоянии
                            await state.update_data(code=code)
                            await message.answer('Введите код из системы:')
                            await state.set_state(
                                RegistrationStates.waiting_for_code
                            )

                        else:
                            await message.answer('Ошибка получения кода')
                            logging.error(
                                f'Ошибка получения кода для {user_in_chat}'
                            )

            except aiohttp.ClientError as e:
                await message.answer(f'Ошибка подключения: {e}')
                logging.error(f'Ошибка в {__name__} - {e}')


@dp.callback_query(lambda c: c.data.startswith('building_'))
async def process_building_selection(
    callback_query: CallbackQuery, state: FSMContext
):
    """Обработка выбора здания"""
    build_id = int(str(callback_query.data).split('_')[1])  # <-- непонятная 1

    async with AsyncSessionLocal() as session:
        keyboard = await create_all_offices_keyboard(session, build_id)
        await callback_query.message.edit_text(
            'Выберите кабинет:',
            reply_markup=keyboard
        )
    await state.update_data(selected_build_id=build_id)


@dp.callback_query(lambda c: c.data == 'back_to_builds')
async def process_back_to_builds(callback_query: CallbackQuery):
    """Обработка возврата к списку зданий"""
    async with AsyncSessionLocal() as session:
        keyboard = await create_all_builds_keyboard(session)
        await callback_query.message.edit_text(
            'Теперь выберите здание:',
            reply_markup=keyboard
        )


@dp.message(RegistrationStates.waiting_for_code)
async def process_code(message: Message, state: FSMContext) -> None:
    """
    Обработчик ввода кода авторизации.
    """
    user_code = message.text  # Код, введенный пользователем
    data = await state.get_data()
    generated_code = str(data.get('code'))  # Получаем код из состояния

    user_in_chat = create_user_attrs(message)

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
            await message.answer('Вот и вся регистрация!')
            logging.info(
                f'{user_in_chat} успешно авторизовался и сохранен в базе'
            )

            keyboard = await create_all_builds_keyboard(
                session, message=message
            )

            # Сбрасываем состояние
            await state.clear()
            await message.answer(
                    'Выберите здание:',
                    reply_markup=keyboard
                )
    else:
        await message.answer('❌ Неверный код.')
        logging.info(f'{user_in_chat} ввел неверный код')


@dp.callback_query(lambda c: c.data.startswith('button'))
async def process_callback_button(callback_query: CallbackQuery) -> None:
    """
    Обработчик нажатия на кнопку кабинета.

    Появляется, когда авторизованный пользователь нажал на кнопку кабинета.
    """
    office_id = int(str(callback_query.data).replace('button', ''))  # ID кабинета

    user_in_chat = create_user_attrs(callback_query)

    async with AsyncSessionLocal() as session:
        office = await return_office(session, office_id)

        # Проверяем, существует ли кабинет (TODO сомневаюсь, что это надо)
        if not await check_office_exists(callback_query, office):
            return  # Если кабинет не найден, завершаем выполнение

        await remove_keyboard(callback_query.message)

        # Если найден - отправляем запрос на подтверждение:
        await callback_query.message.answer(
            f'Выбран кабинет {str(office.abbr)}. Всё верно?',
            reply_markup=confirm_keyboard(office_id)
        )
        # TODO надо добавить логгирование нажатия на кнопку кабинета
        logging.info(f'{user_in_chat} нажал кнопку кабинета {office}.')


@dp.callback_query(lambda c: c.data.startswith('confirm_'))
async def process_confirm_callback(callback_query: CallbackQuery) -> None:
    """
    Обработчик подтверждения выбора кабинета.
    """
    office_id = int(str(callback_query.data).replace('confirm_', ''))  # ID кабинета
    tg_account_id = callback_query.from_user.id  # ID пользователя
    user_in_chat = create_user_attrs(callback_query)

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
        result = await session.execute(
            insert(Order)
            .values(
                office_id=office_id,
                tg_account_id=tg_account_id,
                order_date=localized_time.date(),
                order_time=localized_time.time(),
                in_archive=False
            )
            .returning(Order.id)
        )
        new_order_id = result.scalar()

        # Перезаписываем последний выбор пользователя:
        await session.execute(
            update(TgAccounts)
            .values(
                account=tg_account_id,
                blocked=False,
                last_office=office_id
            )
        )

        await session.commit()

        logging.info(
            f'{user_in_chat} создал заявку {new_order_id} для {office}'
        )

        order_in_time = get_slot_order(localized_time)  # Ближайшая доставка.

        # Отправляем подтверждение пользователю
        await callback_query.message.answer(
            f'✅ Заказ воды №{new_order_id} создан.\n\n'
            f'Место: {office.abbr}\n'
            f'Доставка: {order_in_time}!\n\n'
            'Ожидайте…'
        )


@dp.callback_query(lambda c: c.data == 'cancel')
async def process_cancel_callback(callback_query: CallbackQuery) -> None:
    """
    Обработчик отмены выбора кабинета.
    """
    user_in_chat = create_user_attrs(callback_query)

    await remove_keyboard(callback_query.message)
    await callback_query.message.answer('❌ Выбор кабинета отменен.')
    logging.info(f'{user_in_chat} отменил выбор кабинета.')


async def setup_bot(token: str) -> Bot:
    # Инициализация бота, диспетчера и роутеров:
    bot = Bot(
        token=token,
        can_edit_messages=True
    )

    # Добавляем роутеры:
    url_for_get_list
    url_for_add_office

    return bot


# Run the bot
async def main() -> None:

    configure_logging()  # Запускаем сконфигурированный логгер

    # Создаём таблицы, если они ещё не существуют
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logging.info('Движок создан, база подключена')

    token = str(os.getenv('bot_token'))
    bot = await setup_bot(token)
    await on_startup(bot)
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
