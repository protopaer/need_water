from typing import Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from constants import OFFICE_IN_LINE
from models import Offices, TgAccounts, Builds


async def check_authorization(session, message) -> bool:
    """
    Проверяет, авторизован ли Пользователь.
    """
    tg_account = str(message.chat.id)  # Аккаунт из запроса

    # Проверяем, есть ли запись в таблице TgAccounts
    result = await session.execute(
        select(TgAccounts).where(
            TgAccounts.account == tg_account,
            TgAccounts.blocked == False
        )
    )
    check_authorization = result.scalars().first()

    # Возвращаем True, если пользователь авторизован, иначе False
    return bool(check_authorization)


async def create_all_builds_keyboard(
    session, **kwargs
) -> Optional[InlineKeyboardMarkup]:
    """
    Создает клавиатуру со списком зданий.
    """

    message = kwargs.get('message')
    # Создаем кнопки
    buttons = []

    # Проблема были здесь:
    if message:
        if not await check_authorization(session, message):
            return None

        user_account = await session.execute(
            select(TgAccounts)
            .where(TgAccounts.account == str(message.chat.id))
        )
        user_account = user_account.scalar_one_or_none()
        favorite_office = await session.get(Offices, user_account.last_office)

        # Добавляем избранный кабинет (если есть) в клавиатуру:
        if favorite_office:
            buttons.append([
                InlineKeyboardButton(
                    text=f'⭐ {favorite_office.abbr}',
                    callback_data=f'button{favorite_office.id}'
                )
            ])

    # Получаем список всех зданий:
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
            callback_data=f'building_{build.id}'
        )]
        for build in builds
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


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


async def create_builds_keyboard(session) -> InlineKeyboardMarkup:
    """
    Создает inline клавиатуру со списком зданий.
    """
    # Получаем список всех зданий из базы данных
    result = await session.execute(select(Builds))
    builds = result.scalars().all()

    # Создаем кнопки для каждого здания
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=build.name, callback_data=f'build_{build.id}'
        )]
        for build in builds
    ])
    return keyboard
