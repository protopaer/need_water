from pathlib import Path


FIRST_SECTION = 10
SECOND_SECTION = 15

OUR_TIMEZONE = 'Asia/Yekaterinburg'

GET_LIST = '/get_list'
ADD_OFFICE = 'add_office'
ADD_BUILD = 'add_build'

API_PHONEBOOK_AWAIT = 10

BASE_DIR = Path(__file__).parent
LOG_DIR = Path(f'{BASE_DIR}/logs')
LOG_FILE = Path(f'{LOG_DIR}/logging_tg_water_bot.log')
MAX_BYTES_FOR_LOG_FILE = 10 ** 6
BACKUP_COUNT = 5

ABBR_OFFICE_COUNT = 10
NAME_OFFICE_COUNT = 40
NAME_BUILD_COUNT = 40
TG_ACCOUNT_LEN = 20

OFFICE_IN_LINE = 3

START_TEXT = 'Начнём с выбора здания (локации):'
START_AGAIN_BUILD = 'Ничего страшного, надо решиться и выбрать здание (локацию):'
START_AGAIN_OFFICE = 'Нажмёте на другой кабинет?'
REPEAT_TEXT = 'Повторить ⭐ заказ или н'
REGISTRATION_DONE = 'Вот и вся регистрация! Easy 😎'