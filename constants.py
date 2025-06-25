from datetime import datetime
import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


# Настройка графика работы:
FIRST_SECTION = 10
FIRST_SECTION_EMOJI = '🕙'
SECOND_SECTION = 13
SECOND_SECTION_EMOJI = '🕐'
SECTION_MINUTES = 0
NEXT_WEEKDAY_EMOJI = '📅'
OUR_TIMEZONE = 'Asia/Yekaterinburg'
# Выходные дни в рабочие дни:
HOLIDAY = [
    datetime(2025, 5, 1).date(),
    datetime(2025, 5, 2).date(),
    datetime(2025, 5, 8).date(),
    datetime(2025, 5, 9).date(),
    datetime(2025, 6, 12).date(),
    datetime(2025, 6, 13).date(),
    datetime(2025, 11, 3).date(),
    datetime(2025, 11, 4).date(),
    datetime(2025, 12, 31).date()
]
# Рабочие дни в выходные дни:
NOT_DAY_OFF = [
    datetime(2025, 11, 1).date()  # пока не работает!
]
# Количество часов (старт):
MIN_HOUR_IN_DAYS = 0
MAX_HOUR_IN_DAYS = 24
KEYBOARD_DELETE_FROM_SECONDS = 60

# Количество бутылей (старт):
# 🔥 важно указать правильное (фактическое) кол-во на старте:
BOOTLES_LEFT = int(os.getenv('bootles_left'))
# Порог для получения уведомлений админами):
CONSTANT_WATER_SUPPLY = int(os.getenv('constant_water_supply'))
# Когда пользователи начинают грустить (Неснижаемый минимальный запас):
BOOTLES_ZERO = 5
# Когда пользователь стал опытным и ему не нужны подсказки:
LEN_ORDERS_FOR_SENIOR_USER = 5

# Количество бутылей в партии при поступлении:
MIN_BOOTLE_ACCEPT = 1
MAX_BOOTLE_ACCEPT = 150

# Количество бутылей в партии при списании:
MIN_BOOTLE_DELETE = 1

# Команды для действий:
GET_LIST = '/get_list'
ADD_BOOTLES = '/plus'
DELETE_BOOTLES = '/minus'
DELETE_ORDER = '/delete_order'
TOTAL_BOOTLES = '/total_bootles'
DELETE_OFFICE = '/delete_office'
ADD_OFFICE = 'add_office'
ADD_BUILD = 'add_build'

API_PHONEBOOK_AWAIT = 10
TIMEOUT_AIOGRAM = 30
AWAIT_DISABLE_NOTIFICATION = 120
SUCCESSFUL_AUTH_IN_SMTP_STATUS_CODE = 235

# Стандарт кодирования сообщений:
ENCODING_IN_UTF = 'utf-8'

# Настройка логгирования:
BASE_DIR = Path(__file__).parent
LOG_DIR = Path(f'{BASE_DIR}/logs')
LOG_FILE = Path(f'{LOG_DIR}/logging_tg_water_bot.log')
MAX_BYTES_FOR_LOG_FILE = 10 ** 6
BACKUP_COUNT = 5
CUSTOM_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

# Длина символов в базе данных:
ABBR_OFFICE_COUNT = 30
NAME_OFFICE_COUNT = 70
NAME_BUILD_COUNT = 40
TG_ACCOUNT_LEN = 20

# Настройка количества кнопок в ряду клавиатуры:
OFFICE_IN_LINE = 3

# Описание событий:
START_TEXT = 'Начнём с выбора здания (локации):'
START_AGAIN_BUILD = (
    'Ничего страшного, надо решиться и выбрать здание (локацию):'
)
START_AGAIN_OFFICE = 'Нажмёте на другой кабинет?'
REPEAT_TEXT = '⭐ - повторить заказ\nили н'
REGISTRATION_DONE = 'Вот и вся регистрация! 😎'
GIVE_ME_ADDRESS_CODE = (
    'Зайдите с рабочего ПК на сайт http://phonebook.atu.mmk.ru/#/NumVer/\n'
    'Там появился код авторизации, который нужно отправить мне'
)
RULES = (
    '<b>Здравствуйте!</b>\n\n'
    '<b>Для работы сервиса определены следующие правила:</b>\n\n'
    '1. Каждый кабинет может заказать только ОДНУ бутыль в день!\n\n'
    '2. Каждый человек может заказать только ОДНУ бутыль в день!\n\n'
    f'3. Доставка осуществляется в {FIRST_SECTION} и {SECOND_SECTION} '
    'часов каждый рабочий день.\n\n'
    f'4. Если заказ воды сделан после {SECOND_SECTION} часов - доставка '
    f'будет <b>АВТОМАТИЧЕСКИ</b> перенесена на {FIRST_SECTION} часов '
    'следующего рабочего дня.\n\n'
    '5. После подачи заявки выбранный Вами кабинет получает статус '
    '«Избранное» и доступен при старте новой сессии (обращения).\n\n'
    '6. Подача заявок без необходимости может привести к блокировке Вашей '
    'учётной записи в нашем сервисе.\n\n'
    '7. Процедура регистрации выполняется для каждого Telegram-аккаунта '
    'один раз.\n\n\n'
    'Замечания и пожелания в ЛС @mx_style74'
)

INSTRUCTION_NEW_ORDER = (
    '💡 Как подать новую заявку:\n - /start\n'
    ' - кнопка «🟰Меню» слева от строки ввода сообщения'
)

SORRY = (
    'Очень жаль, но воды пока нет. Может кофе?',
    'Выпили всю воду, остался только электролит 💀',
    'На складах пусто, но Андрей Петрович уже решает проблему... '
    'Надеюсь, скоро!',
    'Воды нет, но есть печеньки... 🍪 🍪 🍪',
    'Выпили... Абсолютно всё!..',
    'GET-запрос на склад вернул значение None. Получается - воды нет!'
)

ERROR_WHEN_GET_CODE = (
    'Ошибка получения кода, повторите попытку через несколько минут.'
)
