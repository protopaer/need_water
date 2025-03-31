import asyncio
import logging
import os

from aiogram import Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import insert, update

from admins.admins_action import url_for_add_office, url_for_get_list
from admins.admins_loading_dataset import all_upload
from bot_logging import configure_logging
from config import AsyncSessionLocal, dp, engine, scheduler
from constants import (AWAIT_DISABLE_NOTIFICATION, FIRST_SECTION,
                       OUR_TIMEZONE,
                       REGISTRATION_DONE,
                       REPEAT_TEXT, RULES,
                       SECOND_SECTION,
                       SECTION_MINUTES,
                       START_AGAIN_BUILD,
                       START_AGAIN_OFFICE,
                       START_TEXT)
from function import (add_orgers_in_archive,
                      check_office_exists,
                      check_order_today,
                      check_user_today,
                      check_authorization,
                      collect_orders_for_interval,
                      create_user_attrs,
                      format_orders_message,
                      get_admins_account,
                      get_datetime_in_timezone_for_message,
                      get_id_from_callback_query,
                      get_slot_order,
                      get_favorite_office,
                      get_workday_or_not,
                      return_office,
                      # send_email,
                      start_registration)
from keyboards import (create_all_builds_keyboard,
                       create_all_offices_keyboard,
                       confirm_keyboard,
                       remove_keyboard)
from models import Base, Offices, Order, TgAccounts
from users.users_fcm import RegistrationStates


async def on_startup(bot: Bot):
    """
    Настройка расписания с действиями при запуске бота.
    """
    scheduler.add_job(
        send_interval_message,
        CronTrigger(
            hour=FIRST_SECTION, minute=SECTION_MINUTES, timezone=OUR_TIMEZONE
        ),
        args=[bot, FIRST_SECTION],
        id='first_section'
    )
    scheduler.add_job(
        send_interval_message,
        CronTrigger(
            hour=SECOND_SECTION, minute=SECTION_MINUTES, timezone=OUR_TIMEZONE
        ),
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
        if get_workday_or_not():
            try:
                # Получаем данные о заказах для указанного интервала
                orders = await collect_orders_for_interval(session, hour)
                message_text = format_orders_message(hour, orders)

                # Отправка email (временно отложено):
                # await send_email(message_text)

                # Проверка наличия списка ТГ-аккаунтов админов в окружении:
                admins_id = get_admins_account()
                if not admins_id:
                    logging.error('Проблемы со списком админов.')
                    return

                # Отправляем сообщения в ТГ-аккаунты админам:
                for admin_id in admins_id:
                    await bot.send_message(admin_id, message_text)
                    logging.info(
                        f'Админу {admin_id} направлен список заявок.'
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

            # Проверка наличия списка ТГ-аккаунтов админов в окружении:
            admins_id = get_admins_account()
            if not admins_id:
                logging.error('Проблемы со списком админов.')
                return
            logging.debug(f'Список админов: {admins_id}')

            # Отправляем сообщения в ТГ-аккаунты админам:
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
async def command_start_handler(message: Message, state: FSMContext) -> None:
    """
    Стартовая страница (страница авторизации или выбора кабинета).
    """
    async with AsyncSessionLocal() as session:
        # Проверяем авторизацию пользователя...:
        if not await check_authorization(session, message):
            # если нет - запускаем регистрацию:
            registration_complete = await start_registration(message, state)
            if not registration_complete:
                return  # Прерываем (если регистрация не завершена)

        # FIXME попробовать убрать favorite_office:
        favorite_office = await get_favorite_office(session, message)

        keyboard = await create_all_builds_keyboard(
            session,
            check_favorite=True,
            message=message,
            path='building')

        # FIXME если уберу favorite_office - надо переделать это:
        all_text = START_TEXT if favorite_office is None else (
            REPEAT_TEXT + START_TEXT[1:]
        )

        await message.answer(all_text, reply_markup=keyboard)


@dp.message(Command('rules'))
async def command_rules_handler(message: Message) -> None:
    """
    Страница с указанием правил пользования сервисом.
    """
    await message.answer(RULES, parse_mode="HTML")


@dp.message(RegistrationStates.waiting_for_code)
async def process_code(message: Message, state: FSMContext) -> None:
    """
    Обработчик ввода кода авторизации.
    """
    user_in_chat = create_user_attrs(message)

    user_code = message.text  # Код, введенный пользователем
    data = await state.get_data()
    generated_code = str(data.get('code'))  # Получаем код из состояния

    if user_code == generated_code:
        # Если код верный, добавляем запись в таблицу TgAccounts
        async with AsyncSessionLocal() as session:
            # Создаем запись TgAccounts:
            new_account = insert(TgAccounts).values(
                account=str(message.chat.id),
                blocked=False
            )
            # Добавляем запись в базу данных:
            await session.execute(new_account)
            await session.commit()

            await message.answer(REGISTRATION_DONE)
            logging.info(
                f'{user_in_chat} успешно авторизовался и сохранен в базе'
            )
            keyboard = await create_all_builds_keyboard(
                session,
                check_favorite=True,
                message=message,
                path='building'
            )
            # Сбрасываем состояние
            await state.clear()
            await message.answer(START_TEXT, reply_markup=keyboard)

    else:
        await message.answer('❌ Неверный код.')
        logging.info(f'{user_in_chat} ввел неверный код')


@dp.callback_query(lambda c: c.data.startswith('building_'))
async def process_building_selection(
    callback_query: CallbackQuery, state: FSMContext
):
    """
    Обработка выбора Здания Пользователем.
    """
    # разделить данные и забрать всё что справа:
    build_id = int(str(callback_query.data).split('_')[-1])

    async with AsyncSessionLocal() as session:
        keyboard = await create_all_offices_keyboard(session, build_id)
        await callback_query.message.edit_text(
            'Выберите кабинет:',
            reply_markup=keyboard
        )
    await state.update_data(selected_build_id=build_id)


@dp.callback_query(lambda c: c.data == 'back_to_builds')
async def process_back_to_builds(callback_query: CallbackQuery):
    """
    Обработка возврата к списку Зданий.

    Проверено!
    """
    async with AsyncSessionLocal() as session:
        keyboard = await create_all_builds_keyboard(
            session,
            check_favorite=True,
            message=callback_query.message,
            path='building'
        )
        await callback_query.message.edit_text(
            START_AGAIN_BUILD, reply_markup=keyboard
        )


@dp.callback_query(lambda c: c.data.startswith('button'))
async def process_callback_button(callback_query: CallbackQuery) -> None:
    """
    Обработчик нажатия на кнопку кабинета.

    Появляется, когда авторизованный пользователь нажал на кнопку кабинета.
    """
    office_id = get_id_from_callback_query(callback_query, 'button')

    user_in_chat = create_user_attrs(callback_query)

    async with AsyncSessionLocal() as session:
        office = await return_office(session, office_id)

        # Проверяем, существует ли кабинет (TODO сомневаюсь, что это надо)
        if not await check_office_exists(callback_query, office):
            return  # Если кабинет не найден, завершаем выполнение

        await remove_keyboard(callback_query.message)

        # Если найден - отправляем запрос на подтверждение:
        await callback_query.message.answer(
            f'Выбран кабинет:\n\n{str(office.abbr)} '
            f'\n{str(office.name)}\n\nВсё верно?',
            reply_markup=confirm_keyboard(office_id)
        )
        logging.info(f'{user_in_chat} нажал кнопку кабинета {office}.')


@dp.callback_query(lambda c: c.data.startswith('confirm_'))
async def process_confirm_callback(callback_query: CallbackQuery) -> None:
    """
    Обработчик подтверждения выбора кабинета.
    """
    office_id = get_id_from_callback_query(callback_query, 'confirm_')
    tg_account_id = callback_query.from_user.id  # ID пользователя
    user_in_chat = create_user_attrs(callback_query)

    async with AsyncSessionLocal() as session:
        office = await return_office(session, office_id)

        # TODO сомневаюсь, что это надо
        # Проверяем, существует ли кабинет
        if not await check_office_exists(callback_query, office):
            return  # Если кабинет не найден, завершаем выполнение

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
            .where(TgAccounts.account == str(tg_account_id))
            .values(
                last_office=office_id
            )
        )

        await session.commit()

        logging.info(
            f'{user_in_chat} создал заявку {new_order_id} для {office}'
        )

        emoji, order_in_time = get_slot_order(localized_time)  # Ближ доставка.

        # Отправляем подтверждение пользователю
        await callback_query.message.answer(
            f'✅ Заказ воды №{new_order_id} создан.\n\n'
            f'Место: {office.abbr}\n'
            f'Доставка: {emoji} {order_in_time}!\n\n'
            'Ожидайте…'
        )

        # Встать на паузу и отправить инструкцию, как сделать новую заявку:
        await asyncio.sleep(AWAIT_DISABLE_NOTIFICATION)
        await callback_query.message.answer(
            'Как подать новую заявку:\n'
            ' - /start\n'
            ' - кнопка «🟰Меню» слева от строки ввода сообщения',
            disable_notification=True
        )


@dp.callback_query(lambda c: c.data.startswith('back_up_from_office_'))
async def process_cancel_callback(callback_query: CallbackQuery):
    """
    Обработчик отмены выбора Кабинета и возврата клавиатуры Кабинетов Здания.
    """
    # Сбор данных:
    office_id = get_id_from_callback_query(
        callback_query, 'back_up_from_office_')
    # office_id = json.loads(callback_query.data).get('office_id')

    # Очистка:
    await remove_keyboard(callback_query.message)
    await callback_query.message.answer('❌ Выбор кабинета отменен.')

    # Логгирование:
    user_in_chat = create_user_attrs(callback_query)
    logging.info(f'{user_in_chat} отменил выбор кабинета.')

    # Формирование клавиатуры кабинетов в здании:
    async with AsyncSessionLocal() as session:
        office = await session.get(Offices, office_id)
        keyboard = await create_all_offices_keyboard(session, office.build_id)
        await callback_query.message.answer(
            START_AGAIN_OFFICE, reply_markup=keyboard
        )


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

        # Загрузка дб:
        if bool(os.getenv('create_db')):
            await all_upload()

    token = str(os.getenv('bot_token'))
    bot = await setup_bot(token)
    await on_startup(bot)
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
