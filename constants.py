from pathlib import Path

# Настройка графика работы:
FIRST_SECTION = 10
FIRST_SECTION_EMOJI = '🕙'
SECOND_SECTION = 13
SECOND_SECTION_EMOJI = '🕐'
SECTION_MINUTES = 0
NEXT_WEEKDAY_EMOJI = '📅'
OUR_TIMEZONE = 'Asia/Yekaterinburg'

# Команды для действий:
GET_LIST = '/get_list'
ADD_OFFICE = 'add_office'
ADD_BUILD = 'add_build'

API_PHONEBOOK_AWAIT = 10
AWAIT_DISABLE_NOTIFICATION = 120

# Настройка логгирования:
BASE_DIR = Path(__file__).parent
LOG_DIR = Path(f'{BASE_DIR}/logs')
LOG_FILE = Path(f'{LOG_DIR}/logging_tg_water_bot.log')
MAX_BYTES_FOR_LOG_FILE = 10 ** 6
BACKUP_COUNT = 5

# Длина символов в базе данных:
ABBR_OFFICE_COUNT = 30
NAME_OFFICE_COUNT = 70
NAME_BUILD_COUNT = 40
TG_ACCOUNT_LEN = 20

# Настройка количества кнопок в ряду клавиатуры:
OFFICE_IN_LINE = 3

# Описание событий:
START_TEXT = 'Начнём с выбора здания (локации):'
START_AGAIN_BUILD = 'Ничего страшного, надо решиться и выбрать здание (локацию):'
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
    '1. Каждый кабинет может заказать только ОДИН бутыль в день!\n\n'
    '2. Каждый человек может заказать только ОДИН бутыль в день!\n\n'
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
