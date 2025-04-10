import logging
import pytz
from logging.handlers import RotatingFileHandler
from datetime import datetime

from constants import (BACKUP_COUNT, CUSTOM_TIME_FORMAT, LOG_FILE, LOG_DIR,
                       MAX_BYTES_FOR_LOG_FILE, OUR_TIMEZONE)


class TimezoneFormatter(logging.Formatter):
    """Кастомный форматтер с поддержкой часовых зон"""
    def __init__(self, fmt=None, datefmt=None, tz=None):
        super().__init__(fmt, datefmt)
        self.tz = tz or pytz.timezone(OUR_TIMEZONE)

    def converter(self, timestamp):
        """Конвертирует timestamp в datetime с учетом часовой зоны"""
        dt = datetime.fromtimestamp(timestamp)
        return self.tz.localize(dt)

    def formatTime(self, record, datefmt=None):
        """Форматирует время с учетом часовой зоны"""
        dt = self.converter(record.created)
        if datefmt:
            return dt.strftime(datefmt)
        else:
            return dt.isoformat()


def configure_logging():
    LOG_DIR.mkdir(exist_ok=True)
    rotating_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES_FOR_LOG_FILE, backupCount=BACKUP_COUNT
    )

    # Создаем кастомный форматтер с часовой зоной
    formatter = TimezoneFormatter(
        fmt='%(asctime)s [ %(name)25s ] %(levelname)12s >>> %(message)s',
        datefmt=CUSTOM_TIME_FORMAT,
        tz=pytz.timezone(OUR_TIMEZONE)
    )
    rotating_handler.setFormatter(formatter)

    # Получаем корневой логгер
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Удаляем все существующие обработчики
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Добавляем наш обработчик
    logger.addHandler(rotating_handler)

    # Пример лога для проверки
    logger.info(
        'Логгирование успешно настроено с часовой зоной %s', OUR_TIMEZONE
    )
