# from typing import Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from constants import OFFICE_IN_LINE, REPEAT_TEXT, START_TEXT
from function import get_favorite_office
from models import Offices, Builds


async def create_all_builds_keyboard(
    session,
    check_favorite=False,
    **kwargs
) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру со списком зданий (может вернуть None).
    """

    message = kwargs.get('message')  # <-- забыл зачем сделал так!

    # Создаем заготовку кнопок:
    buttons = []

    if message and check_favorite:  # TODO решить, нужно ли убрать message
        favorite_office = await get_favorite_office(session, message)
        if favorite_office is not None:
            # Добавляем избранный кабинет (если есть) в клавиатуру:
            buttons.append([
                InlineKeyboardButton(
                    text=f'⭐ {favorite_office.abbr}',
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
    buttons.extend([
        [InlineKeyboardButton(
            text=f'{build.name}',
            callback_data=f'building_{build.id}'  # как работает building_Х ?
        )]
        for build in builds
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# # По сути дубль!!!
# async def create_builds_keyboard(session) -> InlineKeyboardMarkup:
#     """
#     Создает inline клавиатуру со списком зданий.
#     """
#     # Получаем список всех зданий из базы данных
#     result = await session.execute(select(Builds))
#     builds = result.scalars().all()

#     # Создаем кнопки для каждого здания
#     keyboard = InlineKeyboardMarkup(inline_keyboard=[
#         [InlineKeyboardButton(
#             text=build.name, callback_data=f'build_{build.id}'
#         )]
#         for build in builds
#     ])
#     return keyboard


async def create_all_offices_keyboard(session: AsyncSession, build_id: int):
    """
    Создает inline-клавиатуру с кабинетами выбранного здания и кнопкой ← .
    """
    result = await session.execute(
        select(Offices)
        .where(Offices.build_id == build_id)
        .order_by(func.lower(Offices.abbr))
    )
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
    Создаем клавиатуру для подтверждения выбора.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text='✅ Верно!',
                callback_data=f'confirm_{office_id}'
            ),
            InlineKeyboardButton(
                text='❌ Мимо)',
                callback_data='cancel'
            )
        ]
    ])


async def remove_keyboard(message) -> None:
    """
    Удаляет клавиатуру из сообщения после нажатия Пользователем на кнопку.
    """
    await message.edit_reply_markup(reply_markup=None)
