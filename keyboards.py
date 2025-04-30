from random import choice
from typing import Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from constants import BOOTLES_ZERO, OFFICE_IN_LINE, SORRY
from filters import select_all_offices_in_build
from function import get_favorite_office, return_bootles
from models import Builds


async def create_all_builds_keyboard(
    session,
    check_favorite=False,
    **kwargs
) -> Optional[InlineKeyboardMarkup]:
    """
    Создает клавиатуру со списком зданий.
    """
    message = kwargs.get('message')  # <-- забыл зачем сделал так!
    path = kwargs.get('path')

    # Проверка, что вода доступна для заказа или ответ «извините»:

    # Получаем кол-во бутылей в последнем заказе:
    bootles_left_now = await return_bootles(session)

    # изменил на меньше или равно (на случай, если перед этим списали партию)
    if bootles_left_now and bootles_left_now <= BOOTLES_ZERO and message:
        await message.answer(f'❌ {choice(SORRY)}')
        return None

    # Создаем заготовку кнопок:
    buttons = []

    if message and check_favorite:  # TODO решить, нужно ли убрать message
        favorite_office = await get_favorite_office(session, message)
        if favorite_office is not None:
            # Добавляем избранный кабинет (если есть) в клавиатуру:
            buttons.append([
                InlineKeyboardButton(
                    text=f'⭐ {favorite_office.abbr} [ повторить ]',
                    callback_data=f'button{favorite_office.id}'
                )
            ])

    # Получаем отсортированный список всех зданий:
    result = await session.execute(
        select(Builds)
        .order_by(
            func.lower(Builds.name)
        )
    )
    builds = result.scalars().all()

    # Добавляем все здания в клавиатуру:
    for build in builds:
        button = InlineKeyboardButton(
                    callback_data=f'{path}_{build.id}',
                    text=build.name
                )
        buttons.append([button])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def create_all_offices_keyboard(session: AsyncSession, build_id: int):
    """
    Создает inline-клавиатуру с кабинетами выбранного здания и кнопкой ← .
    """
    result = await session.execute(select_all_offices_in_build(build_id))
    offices = result.scalars().all()

    rows = []
    current_row = []
    for office in offices:
        current_row.append(
            InlineKeyboardButton(
                text=str(office.abbr),
                callback_data=f'button{office.id}'
            )
        )
        if len(current_row) == OFFICE_IN_LINE:
            rows.append(current_row)
            current_row = []

    if current_row:
        rows.append(current_row)

    # Кнопка "Назад к зданиям"
    rows.append(
        [InlineKeyboardButton(
            text='← назад',
            callback_data='back_to_builds'
        )]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_keyboard(office_id: int) -> InlineKeyboardMarkup:
    """
    Создаем клавиатуру для подтверждения выбора Кабинета. (ниже дубль)
    """
    # TODO сделать универсальную клавиатуру

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text='✅ Верно',
                callback_data=f'confirm_{office_id}'
            ),
            InlineKeyboardButton(
                text='❌ Отмена',
                callback_data=f'back_up_from_office_{office_id}'
            )
        ]
    ])


def confirm_def_keyboard() -> InlineKeyboardMarkup:
    """
    Создаем абстрактную клавиатуру для подтверждения выбора.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text='✅ Верно',
                callback_data='save'
            ),
            InlineKeyboardButton(
                text='❌ Отмена',
                callback_data='delete'
            )
        ]
    ])


async def remove_keyboard(message) -> None:
    """
    Удаляет клавиатуру из сообщения после нажатия Пользователем на кнопку.
    """
    await message.edit_reply_markup(reply_markup=None)
