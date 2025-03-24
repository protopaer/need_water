from aiogram.fsm.state import State, StatesGroup


# Состояния для FSM
class RegistrationStates(StatesGroup):
    waiting_for_code = State()  # Состояние ожидания ввода кода
