import logging
from typing import Optional
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select, update, delete

from admins.admins_fcm import AddOfficeStates, AddBuildStates
from admins.admins_loading_dataset import create_office_object
from config import AsyncSessionLocal, dp
from constants import (ABBR_OFFICE_COUNT, ADD_BOOTLES, ADD_BUILD, ADD_OFFICE,
                       BOOTLES_ZERO, CONSTANT_WATER_SUPPLY, DELETE_BOOTLES,
                       DELETE_OFFICE, DELETE_ORDER, MAX_BOOTLE_ACCEPT,
                       MIN_BOOTLE_ACCEPT, MIN_BOOTLE_DELETE, NAME_OFFICE_COUNT,
                       NAME_BUILD_COUNT, OUR_TIMEZONE, TOTAL_BOOTLES)
from function import (check_user_in_admins_list, collect_orders_for_interval,
                      get_id_from_callback_query,
                      format_orders_message,
                      parse_element_from_admin_message,
                      return_last_order)
from keyboards import create_all_builds_keyboard, confirm_def_keyboard
from models import Builds, Order, Offices


# Создание роутеров для команд администратора и регистрация в диспетчере:
router_add_office = Router()
router_get_list = Router()
router_add_bootles = Router()
router_delete_bootles = Router()
router_delete_office = Router()
router_total_bootles = Router()
router_delete_order = Router()

url_for_add_office = dp.include_router(router_add_office)
url_for_get_list = dp.include_router(router_get_list)
url_for_add_bootles = dp.include_router(router_add_bootles)
url_for_delete_bootles = dp.include_router(router_delete_bootles)
url_for_delete_office = dp.include_router(router_delete_office)
url_for_total_bootles = dp.include_router(router_total_bootles)
url_for_delete_order = dp.include_router(router_delete_order)


async def update_last_order(
    message, session, how_much=1, need_response=None, **kwargs
):
    """
    Обновляем общее количество бутылей в последнем заказе.

    Args:
        how_much (int): отвечает за величину изменения количества.
            По умолчанию 1 - для случая удаление записи
        need_response (bool, optional): если указано True - функция
            подготавливает ответ.
    """

    # Получаем последний заказ:
    last_order = await return_last_order(session)
    if not last_order:
        await message.answer('❌ Не найдено ни одного заказа')
        return

    # Если удаляемый заказ и последний заказ совпадают - минус не нужен
    if kwargs.get('order_number') == last_order.id:
        return

    # Обновляем количество бутылей:
    new_quantity = last_order.bootles_left + how_much

    # Выполняем обновление записи в базе данных и сохраняемся:
    await session.execute(
        update(Order)
        .where(Order.id == last_order.id)
        .values(bootles_left=new_quantity)
    )
    await session.commit()

    # Подготавливаем ответ (опционально):
    if need_response is not None:
        return last_order, new_quantity


# Обработчик команды /add_office
@router_add_office.message(Command(f'{ADD_OFFICE}'))
async def command_add_office(message: Message, state: FSMContext) -> None:

    # Проверяем права администратора:
    if not await check_user_in_admins_list(trigger=message):
        return

    await message.answer(
        f'Введите аббревиатуру кабинета (до {ABBR_OFFICE_COUNT} символов):'
    )
    await state.set_state(AddOfficeStates.waiting_for_abbr)


# Обработчик ввода аббревиатуры
@router_add_office.message(AddOfficeStates.waiting_for_abbr)
async def process_abbr(message: Message, state: FSMContext) -> None:
    if len(message.text) > ABBR_OFFICE_COUNT:
        await message.answer(
            'Аббревиатура слишком длинная!'
            f'Максимум {ABBR_OFFICE_COUNT} символов.'
        )
        return

    await state.update_data(abbr=message.text)
    await message.answer(
        f'Введите название кабинета (до {NAME_OFFICE_COUNT} символов):'
    )
    await state.set_state(AddOfficeStates.waiting_for_name)


# Обработчик ввода названия
@router_add_office.message(AddOfficeStates.waiting_for_name)
async def process_name(message: Message, state: FSMContext) -> None:
    if len(message.text) > NAME_OFFICE_COUNT:
        await message.answer(
            f'Название слишком длинное! Максимум {NAME_OFFICE_COUNT} символов.'
        )
        return

    await state.update_data(name=message.text)
    await message.answer('Введите номер кабинета (цифра):')
    await state.set_state(AddOfficeStates.waiting_for_office_number)


@router_add_office.message(AddOfficeStates.waiting_for_office_number)
async def process_office_number(message: Message, state: FSMContext) -> None:
    """
    Обработка указанного номера кабинета при создании Office.
    """
    if not message.text.isdigit():
        await message.answer('Номер кабинета должен быть числом!')
        return

    await state.update_data(office_number=int(message.text))
    async with AsyncSessionLocal() as session:
        keyboard = await create_all_builds_keyboard(session, path='build')
        await message.answer('Выберите здание:', reply_markup=keyboard)
        await state.set_state(AddOfficeStates.waiting_for_build_id)


@router_add_office.callback_query(AddOfficeStates.waiting_for_build_id)
async def process_build_selection(
    callback_query: CallbackQuery, state: FSMContext
) -> None:
    """
    Обработка выбора Build при создании Office.
    """
    build_id = get_id_from_callback_query(callback_query, 'build_')
    await state.update_data(build_id=build_id)

    # Получаем данные из состояния
    data = await state.get_data()

    async with AsyncSessionLocal() as session:

        # Получаем название здания по его ID
        build = await session.get(Builds, build_id)
        build_name = build.name if build else "Неизвестное здание"
        office_abbr, office_name, office_number = (
            data['abbr'], data['name'], int(data['office_number'])
        )

        # Отправляем администратору данные для подтверждения
        await callback_query.message.answer(
            'Проверим:\n\n'
            f'Номер кабинета: {office_number}\n'
            f'Название кабинета: {office_name}\n'
            f'Аббревиатура: {office_abbr}\n'
            f'Здание: {build_name}',
            reply_markup=confirm_def_keyboard()
        )

        # Переводим состояние в ожидание подтверждения
        await state.set_state(AddOfficeStates.waiting_for_confirmation)
        await state.update_data(
            office_abbr=office_abbr,
            office_name=office_name,
            office_number=office_number,
            build_id=build_id,
            build_name=build_name
        )

        # Очищаем клавиатуру:
        await callback_query.message.edit_reply_markup(reply_markup=None)


@router_add_office.callback_query(AddOfficeStates.waiting_for_confirmation)
async def process_confirmation(
    callback_query: CallbackQuery, state: FSMContext
) -> None:
    """
    Обработка подтверждения создания кабинета администратором.
    """
    data = await state.get_data()

    if callback_query.data == 'save':
        # Админ подтвердил - сохраняем в БД:
        async with AsyncSessionLocal() as session:
            try:
                new_office = create_office_object(data)
                session.add(new_office)
                await session.commit()

                await callback_query.message.edit_text(
                    f'✅ Кабинет «{new_office.name}» успешно добавлен!\n'
                    f'Аббревиатура: {new_office.abbr}\n'
                    f'Номер кабинета: {new_office.office_number}\n'
                    f'Здание: {data["build_name"]}'
                )
            except Exception as e:
                await session.rollback()
                await callback_query.message.edit_text(
                    f'❌ Ошибка при добавлении кабинета: {str(e)}'
                )
    elif callback_query.data == 'delete':
        # Админ отменил - удаляем сообщение
        await callback_query.message.edit_text(
            '❌ Добавление кабинета отменено',
            reply_markup=None
        )

    await state.clear()


# -----------------------------------------------------------------------------


@router_add_office.message(Command(f'{ADD_BUILD}'))
async def command_add_build(message: Message, state: FSMContext) -> None:
    """
    Обработчик комманды Админа по добавлению Здания.
    """

    # Проверяем права администратора:
    if not await check_user_in_admins_list(trigger=message):
        return

    await message.answer(
        f'Введите название здания (до {NAME_BUILD_COUNT} символов):'
    )
    await state.set_state(AddBuildStates.waiting_for_name)


@router_add_office.message(AddBuildStates.waiting_for_name)
async def process_build_name(message: Message, state: FSMContext) -> None:
    """
    Обработчик ввода названия Здания.
    """
    if len(message.text) > NAME_BUILD_COUNT:
        await message.answer(
            f'Название слишком длинное! Максимум {NAME_BUILD_COUNT} символов.'
        )
        return

    async with AsyncSessionLocal() as session:
        # Создаем новое здание
        new_build = Builds(name=message.text)
        session.add(new_build)
        await session.commit()

    await message.answer(
        f'✅ Здание «{message.text}» успешно добавлено!'
    )
    await state.clear()


# -----------------------------------------------------------------------------


@router_get_list.message(Command('get_list'))
async def list_orders_handler(message: Message) -> None:
    """
    Обработка команды вручную направить список активных Заявок.
    """
    async with AsyncSessionLocal() as session:

        # Собираем данные (час запроса и user_id):
        message_date = message.date.astimezone(ZoneInfo(OUR_TIMEZONE)).hour
        user_id = message.from_user.id

        orders_list = await collect_orders_for_interval(session)
        text_in_message = format_orders_message(message_date + 1, orders_list)

        await message.answer(text_in_message)
        logging.info(f'{user_id} вручную запросил список активных заявок')


# -----------------------------------------------------------------------------


@router_add_bootles.message(
    lambda message: message.text.startswith(f'{ADD_BOOTLES}_')
)
async def add_bootles_in_db(message: Message):
    """
    Добавляем поступление бутылей к их фактическому количеству.
    """
    async with AsyncSessionLocal() as session:

        # Проверяем права администратора:
        if not await check_user_in_admins_list(trigger=message):
            return

        try:
            # Парсим количество бутылей из сообщения
            add_bootles = await parse_element_from_admin_message(
                message,
                'bootles_up',
                MIN_BOOTLE_ACCEPT,
                MAX_BOOTLE_ACCEPT
            )
            if not add_bootles:
                return

            # Обновляем количество бутылей из поступления:
            # TODO подумать, что будет, если не будет найден заказ:
            last_order, new_quantity = (
                await update_last_order(
                    message,
                    session,
                    how_much=add_bootles,
                    need_response=True)
            )

            # Отправляем подтверждение админу:
            await message.answer(
                f'📈 Добавлено бутылей: {add_bootles}.\n'
                f'Теперь общее количество: {new_quantity}'
            )
            logging.info(
                f'Админ добавил {add_bootles} бутылей к заказу {last_order.id}'
            )

            await session.commit()

        except Exception as e:
            await session.rollback()
            await message.answer('❌ Произошла ошибка при обновлении данных')
            logging.error(
                f'Ошибка в add_bootles_in_db: {str(e)}', exc_info=True
            )


@router_delete_bootles.message(
    lambda message: message.text.startswith(f'{DELETE_BOOTLES}_')
)
async def delete_bootles_in_db(message: Message):
    """
    Удаляет (списывает) бутыли относительно их фактического количества.
    """
    async with AsyncSessionLocal() as session:

        # Проверяем права администратора:
        if not await check_user_in_admins_list(trigger=message):
            return

        try:

            # TODO ЭТО МОЖНО ЗАТОЛКАТЬ В ФУНКЦИЮ update_last_order:

            # Получаем последний заказ:
            last_order = await return_last_order(session)
            if not last_order:
                await message.answer('❌ Не найдено ни одного заказа')
                return

            # Расчитываем лимит на списание бутылей
            # (не больше, чем есть сейчас):
            max_bootle_delete = int(last_order.bootles_left)

            # Парсим количество бутылей из сообщения
            delete_bootles = await parse_element_from_admin_message(
                message,
                'bootles_down',
                MIN_BOOTLE_DELETE,
                max_bootle_delete
            )
            if not delete_bootles:
                return

            # Количество бутылей уже должно быть указано (в последнем заказе):
            # Обновляем количество бутылей
            new_quantity = max_bootle_delete - delete_bootles
            await session.execute(
                update(Order)
                .where(Order.id == last_order.id)
                .values(bootles_left=new_quantity)
            )
            await session.commit()

            # TODO -> здесь заканчивается рефакторинг.

            # Отправляем подтверждение админу:
            await message.answer(
                f'📉 Списано бутылей: {delete_bootles}.\n'
                f'Осталось: {new_quantity}.'
            )
            logging.info(
                f'Админ списал {delete_bootles} '
                f'бутылей с заказа {last_order.id}.'
            )

            await session.commit()

        except Exception as e:
            await session.rollback()
            await message.answer('❌ Произошла ошибка при обновлении данных')
            logging.error(
                f'Ошибка в delete_bootles_in_db: {str(e)}', exc_info=True
            )


@router_delete_office.message(F.text.regexp(rf'^{DELETE_OFFICE}_(\d+)$'))
async def delete_office_by_id(message: Message) -> None:
    """
    Удаление кабинета по его номеру через команду /delete_office_<id> .
    """
    async with AsyncSessionLocal() as session:

        # Проверяем права администратора:
        if not await check_user_in_admins_list(trigger=message):
            return

        try:
            # Извлечение и валидация номера кабинета:
            office_number: Optional[int] = None
            try:
                office_number = int(message.text.split('_')[-1])
                if office_number <= 0:
                    raise ValueError('Номер должен быть положительным числом')
            except (IndexError, ValueError):
                await message.answer('❌ Неверный формат команды')
                return

            # Проверка существования кабинета:
            existing_office = await session.scalar(
                select(Offices).where(Offices.office_number == office_number)
            )
            if not existing_office:
                await message.answer(f'❌ Кабинет №{office_number} не найден!')
                return

            # Удаление кабинета:
            await session.execute(
                delete(Offices).where(Offices.office_number == office_number)
            )
            await session.commit()

            await message.answer(
                f'✅ Кабинет "{existing_office.name}" (№{office_number}) '
                'успешно удалён!'
            )
            logging.info(
                f'UserID {message.from_user.id} удалил кабинет {office_number}'
            )

        except Exception as e:
            await session.rollback()
            error_msg = (
                f'🚨 Ошибка при удалении кабинета №{office_number}: {str(e)}'
            )
            logging.error(error_msg)
            await message.answer('❌ Произошла ошибка при выполнении операции')

        finally:
            await session.close()


@router_total_bootles.message(F.text.regexp(rf'^{TOTAL_BOOTLES}$'))
async def get_total_bootles(message: Message) -> None:
    """
    Показывает текущее количество бутылей на складе.

    Для админа - сообщение расширенное.
    Для пользователя - выводится кол-во бутылей за минусом минимального запаса.
    """
    async with AsyncSessionLocal() as session:
        last_order = await return_last_order(session)

        if last_order:
            total_for_admin = last_order.bootles_left
            total_for_user = total_for_admin - BOOTLES_ZERO

            # Проверяем права администратора:
            if not await check_user_in_admins_list(
                trigger=message, built_in_msg=False
            ):
                msg = f'🫙 Общее кол-во бутылей: {total_for_user}'
            else:
                msg = (
                    f'🫙 Общее кол-во бутылей: {total_for_admin}\n'
                    f'⏏️ Неснижаемый запас: {BOOTLES_ZERO}\n'
                    '📨 Поступление уведомлений админам - при снижении до '
                    f'{CONSTANT_WATER_SUPPLY}'
                )
        else:
            # FIXME: заглушка на старте
            msg = 'Отсутствует последний заказ.'
        await message.answer(msg)


@url_for_delete_order.message(F.text.regexp(rf'^{DELETE_ORDER}_(\d+)$'))
async def delete_order_by_id(message: Message) -> None:
    """
    Удаление заявки по ее номеру через команду /delete_order_<id> .
    """
    async with AsyncSessionLocal() as session:

        # Проверяем права администратора:
        if not await check_user_in_admins_list(trigger=message):
            return

        # TODO Если это будет делать пользователь:
        # ПОДУМАТЬ

        try:
            # Извлечение и валидация номера кабинета:
            order_number: Optional[int] = None
            try:
                order_number = int(message.text.split('_')[-1])
                if order_number <= 0:
                    raise ValueError('Номер должен быть положительным числом')
            except (IndexError, ValueError):
                await message.answer('❌ Неверный формат команды')
                return

            # Проверка существования заказа с данным номером (id)
            # Заказ должен находиться в статусе "Активная заявка":
            existing_order = await session.scalar(
                select(Order).where(
                    Order.id == order_number,
                    Order.in_archive == False)
            )
            if not existing_order:
                await message.answer(f'❌ Заказ №{order_number} не найден!')
                return

            # Возвращаем одну бутыль к общему количеству (в последнем заказе):
            await update_last_order(
                message, session, order_number=order_number
            )

            # Удаление заказа:
            await session.execute(
                delete(Order).where(Order.id == order_number)
            )
            await session.commit()

            await message.answer(
                f'✅ Заказ №{existing_order.id} успешно удалён!'
            )
            logging.info(
                f'UserID {message.from_user.id} '
                f'удалил заказ {existing_order.id}'
            )

        except Exception as e:
            await session.rollback()
            error_msg = (
                f'🚨 Ошибка при удалении заказа №{order_number}: {str(e)}'
            )
            logging.error(error_msg)
            await message.answer('❌ Произошла ошибка при выполнении операции')

        finally:
            await session.close()
