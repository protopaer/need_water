import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from constants import (BACKUP_COUNT, CUSTOM_TIME_FORMAT, LOG_FILE, LOG_DIR,
                       MAX_BYTES_FOR_LOG_FILE, OUR_TIMEZONE)


class TimezoneFormatter(logging.Formatter):
    """Modern timezone-aware formatter using zoneinfo"""
    def __init__(self, fmt=None, datefmt=None, tz=None):
        super().__init__(fmt, datefmt)
        self.tz = ZoneInfo(OUR_TIMEZONE) if tz is None else tz

    def converter(self, timestamp):
        """
        Конвертирует timestamp в формат timezone-aware datetime.
        """
        return (
            datetime.fromtimestamp(timestamp, timezone.utc).astimezone(self.tz)
        )

    def formatTime(self, record, datefmt=None):
        """
        Форматирует время в нужной таймзоне.
        """
        dt = self.converter(record.created)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat()


def configure_logging():
    LOG_DIR.mkdir(exist_ok=True)

    rotating_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_BYTES_FOR_LOG_FILE,
        backupCount=BACKUP_COUNT,
        encoding='utf-8'
    )

    # Создаем кастомный форматтер с часовой зоной
    formatter = TimezoneFormatter(
        fmt='%(asctime)s | %(name)25s | %(levelname)10s || %(message)s',
        datefmt=CUSTOM_TIME_FORMAT,
    )
    rotating_handler.setFormatter(formatter)

    # Получаем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Удаляем все существующие обработчики
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()

    # Добавляем наш обработчик
    root_logger.addHandler(rotating_handler)

    # Тестовый лог с проверкой временной зоны
    test_time = datetime.now(ZoneInfo(OUR_TIMEZONE))
    test_time_now = test_time.strftime(CUSTOM_TIME_FORMAT)

    logging.info(
        f'Проверка часовой зоны - текущее время {test_time_now} '
        f'(часовая зона: {OUR_TIMEZONE})'
    )
