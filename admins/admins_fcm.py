from aiogram.fsm.state import State, StatesGroup


# Состояния для FSM
class AddOfficeStates(StatesGroup):
    waiting_for_abbr = State()  # Ожидание ввода аббревиатуры
    waiting_for_name = State()  # Ожидание ввода названия
    waiting_for_office_number = State()  # Ожидание ввода номера кабинета
    waiting_for_build_id = State()  # Ожидание выбора здания
