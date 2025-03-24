from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, func

from constants import OFFICE_IN_LINE
from models import Offices, TgAccounts, Builds


async def check_authorization(message, session) -> bool:
    """Проверяет, авторизован ли Пользователь."""
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


async def create_all_offices_keyboard(message, session):
    """Создание клавиатуры для подачи заявки (возвращает список кабинетов)."""
    # TODO: подумать, надо ли создавать сессию внутри функции?
    if await check_authorization(message, session):
        # Получаем список всех кабинетов (может это должно быть вне)
        result = await session.execute(
            select(Offices)
            .order_by(
                func.lower(Offices.abbr)
            )
        )
        office_list = result.scalars().all()

        rows = []
        current_row = []
        for office in office_list:
            # Создаем кнопку
            button = InlineKeyboardButton(
                text=office.abbr,
                callback_data=f'button{office.id}'
            )
            current_row.append(button)
            
            # Когда набирается 3 кнопки в ряду, добавляем его
            if len(current_row) == OFFICE_IN_LINE:
                rows.append(current_row)
                current_row = []
        
        # Добавляем оставшиеся кнопки (если есть)
        if current_row:
            rows.append(current_row)

        return InlineKeyboardMarkup(inline_keyboard=rows)

    return None


def confirm_keyboard(office_id: int) -> InlineKeyboardMarkup:
    """Создаем клавиатуру для подтверждения выбора."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Верно!",
                callback_data=f"confirm_{office_id}"
            ),
            InlineKeyboardButton(
                text="❌ Мимо)",
                callback_data="cancel"
            )
        ]
    ])


async def remove_keyboard(message) -> None:
    """
    Удаляет клавиатуру из сообщения после нажатия Пользователем на кнопку.
    """
    await message.edit_reply_markup(reply_markup=None)


async def create_builds_keyboard(session) -> InlineKeyboardMarkup:
    """Создает inline клавиатуру со списком зданий."""
    # Получаем список всех зданий из базы данных
    result = await session.execute(select(Builds))
    builds = result.scalars().all()

    # Создаем кнопки для каждого здания
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=build.name, callback_data=f"build_{build.id}"
        )]
        for build in builds
    ])
    return keyboard
