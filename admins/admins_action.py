import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from admins.admins_fcm import AddOfficeStates, AddBuildStates
from config import AsyncSessionLocal, dp
from constants import (ABBR_OFFICE_COUNT,
                       ADD_BUILD,
                       ADD_OFFICE,
                       GET_LIST,
                       NAME_OFFICE_COUNT,
                       NAME_BUILD_COUNT)
from function import (collect_orders_for_interval,
                      get_id_from_callback_query,
                      format_orders_message,
                      parse_hours_from_admin_message)
from keyboards import create_all_builds_keyboard
from models import Offices, Builds


# Создание роутеров для команд администратора и регистрация в диспетчере:
router_add_office = Router()
router_get_list = Router()

url_for_add_office = dp.include_router(router_add_office)
url_for_get_list = dp.include_router(router_get_list)


# Обработчик команды /add_office
@router_add_office.message(Command(f'{ADD_OFFICE}'))
async def command_add_office(message: Message, state: FSMContext) -> None:
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
    await callback_query.answer()  # Обязательно! с чего вдруг?
    await state.update_data(
        build_id=get_id_from_callback_query(callback_query, 'build_')
    )
    build_id = get_id_from_callback_query(callback_query, 'build_')

    # Получаем данные из состояния
    data = await state.get_data()

    async with AsyncSessionLocal() as session:
        # Создаем новый кабинет
        new_office = Offices(
            abbr=data['abbr'],
            name=data['name'],
            office_number=int(data['office_number']),
            build_id=build_id
        )
        session.add(new_office)
        await session.commit()

        # Получаем название здания по его ID
        build = await session.get(Builds, build_id)
        build_name = build.name if build else "Неизвестное здание"

    await callback_query.message.answer(
        f'✅ Кабинет «{new_office.name}» успешно добавлен!\n'
        f'Аббревиатура: {new_office.abbr}\n'
        f'Номер кабинета: {new_office.office_number}\n'
        f'Здание: {build_name}'
    )
    await state.clear()  # Очищаем состояние


# -----------------------------------------------------------------------------


@router_add_office.message(Command(f'{ADD_BUILD}'))
async def command_add_build(message: Message, state: FSMContext) -> None:
    """
    Обработчик комманды Админа по добавлению Здания.
    """
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


@router_get_list.message(
    lambda message: message.text.startswith(f'{GET_LIST}_')
)
async def list_orders_handler(message: Message) -> None:
    """
    Обработка команды Админа вручную направить список Заявок ко времени.
    """
    async with AsyncSessionLocal() as session:

        hour_find = await parse_hours_from_admin_message(message)
        if not hour_find:
            return

        orders_list = await collect_orders_for_interval(session, hour_find)
        text_in_message = format_orders_message(hour_find, orders_list)

        await message.answer(text_in_message)
        logging.info(
            f'Админ вручную запросил список заявок для {hour_find} часов'
        )
