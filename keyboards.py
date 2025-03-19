from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from models import Offices, TgAccounts


# session = Session(engine)
# office_list = session.query(Offices).all()
# valid_account = session.query(TgAccounts)


def check_authorization(message, session) -> bool:
    """Проверяет, авторизован ли Пользователь."""
    tg_account = str(message.chat.id)  # Аккаунт из запроса

    # Проверяем, есть ли запись в таблице TgAccounts
    check_authorization = session.execute(
        select(TgAccounts).where(
            TgAccounts.account == tg_account,
            TgAccounts.blocked == False
        )
    ).scalars().first()

    # Возвращаем True, если пользователь авторизован, иначе False
    return bool(check_authorization)


def create_all_offices_keyboard(message, session):
    """Создание клавиатуры для подачи заявки (возвращает список кабинетов)."""
    # TODO: подумать, надо ли создавать сессию внутри функции?
    if check_authorization(message, session):
        # Получаем список всех кабинетов (может это должно быть вне)
        office_list = session.query(Offices).all()

        office_stack_buttons = []  # Заготовка для кнопок с кабинетами
        for office in office_list:
            office_stack_buttons.append(
                InlineKeyboardButton(
                    text=office.abbr,
                    callback_data=f'button{office.id}'
                )
            )
        return InlineKeyboardMarkup(inline_keyboard=[office_stack_buttons])

    return None


def confirm_keyboard(office_id: int) -> InlineKeyboardMarkup:
    """Создаем клавиатуру для подтверждения выбора."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Верно!",
                callback_data=f"confirm_{office_id}"
            ),
            InlineKeyboardButton(
                text="Мимо)",
                callback_data="cancel"
            )
        ]
    ])


async def remove_keyboard(message) -> None:
    """
    Удаляет клавиатуру из сообщения после нажатия Пользователем на кнопку.
    """
    await message.edit_reply_markup(reply_markup=None)
