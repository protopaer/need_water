import asyncio
import os
from datetime import date
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from sqlalchemy import insert, and_, select
from sqlalchemy.orm import Session

from models import engine, TgAccounts, Order
from keyboards import create_all_offices_keyboard, confirm_keyboard
from function import string_generate, return_office


# Инициализация бота и диспетчера:
TOKEN: Optional[str] = os.getenv('bot_token')
dp = Dispatcher()


# Состояния для FSM
class RegistrationStates(StatesGroup):
    waiting_for_code = State()  # Состояние ожидания ввода кода


@dp.message(Command("start"))
async def command_start_handler(
    message: Message, state: FSMContext
) -> None:
    """Стартовая страница (страница авторизации или выбора кабинета)."""
    with Session(engine) as session:
        # Проверяем авторизацию пользователя
        keyboard = create_all_offices_keyboard(message, session)

        if keyboard:
            # Если пользователь авторизован, показываем кнопки
            await message.answer(
                "Выберите кабинет:",
                reply_markup=keyboard
            )
        else:
            # Генерируем случайный код и сохраняем его в состоянии
            code = string_generate()  # рандом-код
            await state.update_data(code=code)
            await message.answer(
                f'(Заглушка) Укажите код в справочнике: {code}'
            )
            await state.set_state(RegistrationStates.waiting_for_code)


@dp.message(RegistrationStates.waiting_for_code)
async def process_code(message: Message, state: FSMContext) -> None:
    """Обработчик ввода кода авторизации (пока заглушка)."""
    user_code = message.text  # Код, введенный пользователем
    data = await state.get_data()  # Получаем сохраненный код из состояния
    generated_code = str(data.get('code'))  # Преобразуем в строку

    if user_code == generated_code:
        # Если код верный, добавляем запись в таблицу TgAccounts
        with Session(engine) as session:
            # Добавляем запись в таблицу TgAccounts:
            session.execute(
                insert(TgAccounts).values(
                    account=str(message.chat.id),
                    blocked=False
                )
            )
            session.commit()

        keyboard = create_all_offices_keyboard(message, session)

        # Сбрасываем состояние
        await state.clear()
        await message.answer(
                'Выберите Ваш кабинет:',
                reply_markup=keyboard
            )
    else:
        await message.answer('Неверный код.')


async def check_office_exists(callback_query: CallbackQuery, office) -> bool:
    """
    Проверяет, существует ли кабинет.

    Найден - возвращает True.
    Нет - отправляет сообщение об ошибке и возвращает False.
    """
    if not office:
        await callback_query.message.answer('Кабинет пропал.')
        return False
    return True


@dp.callback_query(lambda c: c.data.startswith('button'))
async def process_callback_button(callback_query: CallbackQuery) -> None:
    """Обработчик нажатия на кнопку кабинета.

    Появляется, когда авторизованный пользователь нажан на кнопку кабинета."""
    office_id = int(callback_query.data.replace('button', ''))  # ID кабинета

    with Session(engine) as session:
        office = return_office(session, office_id)

        # Проверяем, существует ли кабинет
        if not await check_office_exists(callback_query, office):
            return  # Если кабинет не найден, завершаем выполнение

        # Если найден - отправляем запрос на подтверждение:
        await callback_query.message.answer(
            f'Выбран кабинет {office.abbr}. Всё верно?',
            reply_markup=confirm_keyboard(office_id)
        )


@dp.callback_query(lambda c: c.data.startswith('confirm_'))
async def process_confirm_callback(callback_query: CallbackQuery) -> None:
    """Обработчик подтверждения выбора кабинета."""
    office_id = int(callback_query.data.replace('confirm_', ''))  # ID кабинета
    tg_account_id = callback_query.from_user.id  # ID пользователя
    today = date.today()  # Текущая дата

    with Session(engine) as session:
        office = return_office(session, office_id)

        # Проверяем, существует ли кабинет
        if not await check_office_exists(callback_query, office):
            return  # Если кабинет не найден, завершаем выполнение

        # Проверяем, есть ли уже заявка на сегодня
        existing_order = session.execute(
            select(Order).where(
                and_(
                    Order.office_id == office_id,
                    Order.order_date == today
                )
            )
        ).scalars().first()

        if existing_order:
            # Если заявка уже существует, отправляем сообщение
            await callback_query.message.answer(
                f'Заявка для кабинета {office.abbr} на сегодня уже есть.'
            )
            return

        # Создаем новую «заявку на воду» в таблице Order:
        session.execute(
            insert(Order).values(
                office_id=office_id,
                tg_account_id=tg_account_id,
                order_date=today,
                in_archive=False
            )
        )
        session.commit()

        # Отправляем подтверждение пользователю
        await callback_query.message.answer(
            f'Заказ воды для {office.abbr} создан. Ожидайте!'
        )


@dp.callback_query(lambda c: c.data == 'cancel')
async def process_cancel_callback(callback_query: CallbackQuery) -> None:
    """Обработчик отмены выбора кабинета."""
    # FIXME: если сначала создать, а потом нажать отмену - получаешь сообщение
    # с отменой, при этом в базе экземпляр создается
    await callback_query.message.answer('Выбор кабинета отменен.')


# Run the bot
async def main() -> None:
    bot = Bot(token=TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
