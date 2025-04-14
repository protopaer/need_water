import atexit
import asyncio
import fcntl
import logging
import os
import sys

from aiogram import Bot
from aiogram.exceptions import TelegramConflictError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.utils.backoff import BackoffConfig
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import insert, update

from admins.admins_action import (url_for_add_office,
                                  url_for_get_list,
                                  url_for_add_bootles,
                                  url_for_delete_office,
                                  url_for_total_bootles)
from admins.admins_loading_dataset import all_upload
from bot_logging import configure_logging
from config import AsyncSessionLocal, dp, engine, scheduler
from constants import (AWAIT_DISABLE_NOTIFICATION,
                       BOOTLES_LEFT,
                       FIRST_SECTION,
                       INSTRUCTION_NEW_ORDER,
                       OUR_TIMEZONE,
                       REGISTRATION_DONE,
                       REPEAT_TEXT, RULES,
                       SECOND_SECTION,
                       SECTION_MINUTES,
                       START_AGAIN_BUILD,
                       START_AGAIN_OFFICE,
                       START_TEXT,
                       TIMEOUT_AIOGRAM)
from function import (add_orgers_in_archive,
                      check_office_exists,
                      check_order_today,
                      check_user_today,
                      check_authorization,
                      collect_orders_for_interval,
                      create_new_order_in_db,
                      create_user_attrs,
                      format_orders_message,
                      get_admins_account,
                      get_datetime_in_timezone_for_message,
                      get_id_from_callback_query,
                      get_slot_order,
                      get_favorite_office,
                      get_workday_or_not,
                      return_bootles,
                      return_office,
                      send_email,
                      send_message_when_water_left,
                      start_registration)
from keyboards import (create_all_builds_keyboard,
                       create_all_offices_keyboard,
                       confirm_keyboard,
                       remove_keyboard)
from models import Base, Offices, TgAccounts
from users.users_fcm import RegistrationStates


all_media_dir = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'image'
)


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
        # Если сегодня рабочий день:
        if get_workday_or_not():
            try:
                # Получаем данные о заказах для указанного интервала
                orders = await collect_orders_for_interval(session, hour)
                message_text = format_orders_message(hour, orders)

                # Отправка email (временно отложено):
                await send_email(message_text)

                # Проверка наличия списка ТГ-аккаунтов админов в окружении:
                if not (admins_id := get_admins_account()):
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
            if not (admins_id := get_admins_account()):
                return

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
            if not await start_registration(message, state):
                return  # Прерываем (если регистрация не завершена)

        keyboard = await create_all_builds_keyboard(
            session,
            check_favorite=True,
            message=message,
            path='building')

        # Клавиатура не будет сформирована, если воды нет:
        if not keyboard:
            return

        # FIXME попробовать убрать favorite_office:
        # эта проверка уже есть внутри функции get_favorite_office
        favorite_office = await get_favorite_office(session, message)

        # FIXME если уберу favorite_office - надо переделать это:
        all_text = START_TEXT if favorite_office is None else (
            REPEAT_TEXT + START_TEXT[1:]
        )

        await message.answer(all_text, reply_markup=keyboard)


@dp.message(Command('map'))
async def send_photo(message: Message):
    try:
        map_atu = FSInputFile(path=os.path.join(all_media_dir, 'bashik.jpg'))
        await message.answer_photo(
            photo=map_atu,
            caption='Схема подъехала:'
        )
    except FileNotFoundError:
        await message.answer('Схема не найдена. Проверьте путь к файлу!')
    except Exception as e:
        await message.answer(f"Произошла ошибка: {str(e)}")


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

            # Клавиатура не будет сформирована, если воды нет:
            if not keyboard:
                return

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
async def process_confirm_callback(callback_query: CallbackQuery, bot) -> None:
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

        # Считаем количество оставшихся бутылей:
        bootles_left = await return_bootles(session)

        # 🔥 Критически важная часть:
        # На случай, если мы только создаем базу - количество оставшихся
        # бутылей подтягивается из константы:
        if bootles_left is None or not isinstance(bootles_left, int):
            bootles_left = BOOTLES_LEFT
            logging.warning(
                f'Задано дефолтное значение кол-ва бутылей ({BOOTLES_LEFT}).'
            )

        # Создаем новую «заявку на воду» в таблице Order:
        result = await create_new_order_in_db(
            session, office_id, tg_account_id, localized_time, bootles_left
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

        # # FIXME Есть ли какая-то разница, ведь сессия одна
        # # Что если в это время был совершен еще один заказ (более быстрый)

        # Считает кол-во воды опять:
        bootles_left_again = await return_bootles(session)

        # Проверка и направление уведомления админам о снижении остатков воды:
        await send_message_when_water_left(bot, bootles_left_again)

        # Встать на паузу и отправить инструкцию, как сделать новую заявку:
        await asyncio.sleep(AWAIT_DISABLE_NOTIFICATION)
        await callback_query.message.answer(
            INSTRUCTION_NEW_ORDER, disable_notification=True
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
    """
    Инициализация бота, диспетчера и роутеров.
    """
    bot = Bot(
        token=token,
        can_edit_messages=True,
        timeout=TIMEOUT_AIOGRAM
    )

    # Добавляем роутеры:
    url_for_get_list
    url_for_add_office
    url_for_add_bootles
    url_for_delete_office
    url_for_total_bootles
    return bot


async def check_single_instance() -> bool:
    """
    Проверяет, что бот запущен в единственном экземпляре через файл-локер.
    Возвращает True, если блокировка получена, False если бот уже запущен.
    """
    lock_file = "/tmp/bot.lock"

    try:
        # Открываем файл для блокировки
        fd = os.open(lock_file, os.O_CREAT | os.O_WRONLY, 0o644)

        # Пытаемся получить эксклюзивную блокировку
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # Записываем PID текущего процесса
        os.write(fd, str(os.getpid()).encode())
        os.fsync(fd)  # Синхронизируем запись на диск

        # Функция для освобождения блокировки
        def release_lock() -> None:
            """Корректно освобождает файловую блокировку"""
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
                try:
                    os.unlink(lock_file)
                except FileNotFoundError:
                    pass  # Файл уже удален
            except Exception as e:
                logging.warning(f'Ошибка при освобождении блокировки: {e}')

        # Регистрируем освобождение при завершении программы
        atexit.register(release_lock)
        return True

    except (BlockingIOError, PermissionError, OSError) as e:
        logging.error(f'Не удалось получить блокировку: {e}')
        if 'fd' in locals():
            try:
                os.close(fd)  # Закрываем файловый дескриптор
            except OSError:
                pass
        return False


# Запуск бота:
async def main() -> None:
    # 1. Проверка единственного экземпляра
    try:
        if not await check_single_instance():
            logging.error('Бот уже запущен в другом процессе/контейнере')
            sys.exit(1)
    except Exception as e:
        logging.critical(f'Ошибка при проверке блокировки: {e}')
        sys.exit(1)

    # 2. Настройка логгирования
    configure_logging()  # Запускаем сконфигурированный логгер
    logging.info('Запуск бота...')

    # 3. Инициализация БД
    # Создаём таблицы, если они ещё не существуют
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if os.getenv('create_db', '').lower() == 'true':
                await all_upload()
            logging.info('База данных готова')
    except Exception as e:
        logging.critical(f'Ошибка инициализации БД: {e}')
        sys.exit(1)

    # 4. Настройка бота
    try:
        token = os.getenv('bot_token')
        if not token:
            raise ValueError('Не указан токен бота в переменных окружения')

        bot = await setup_bot(token)
    except Exception as e:
        logging.critical(f'Ошибка настройки бота: {e}')
        sys.exit(1)

    # 5. Настройка экспоненциальной задержки при ошибках подключения к API:
    backoff_config = BackoffConfig(
        min_delay=1.0,    # Начальная задержка 1 сек
        max_delay=80.0,    # Максимальная задержка 80 сек
        jitter=0.3,        # Добавляем 30% случайности
        factor=2          # Экспоненциальный множитель
    )

    # 6. Основной цикл работы бота
    try:
        logging.info('Запуск планировщика...')
        await on_startup(bot)

        logging.info('Старт выполнения процедуры polling...')
        await dp.start_polling(
            bot,
            skip_updates=True,
            relax=0.5,
            allowed_updates=['message', 'callback_query'],
            backoff_config=backoff_config
        )
    except TelegramConflictError as e:
        logging.critical(f'Конфликт доступа к боту: {e}')
    except asyncio.CancelledError:
        logging.info('Работа бота прервана по запросу')
    except Exception as e:
        logging.critical(f'Неожиданная ошибка: {e}', exc_info=True)
    finally:
        # 7. Корректное завершение работы
        logging.info('Завершение работы...')
        try:
            await bot.session.close()
        except Exception as e:
            logging.error(f'Ошибка при закрытии сессии бота: {e}')

        try:
            await engine.dispose()
        except Exception as e:
            logging.error(f'Ошибка при освобождении ресурсов БД: {e}')

        logging.info('Бот остановлен')
        sys.exit(0)

if __name__ == '__main__':
    asyncio.run(main())
