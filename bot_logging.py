import logging
from logging.handlers import RotatingFileHandler

from constants import BACKUP_COUNT, LOG_FILE, LOG_DIR, MAX_BYTES_FOR_LOG_FILE


def configure_logging():
    LOG_DIR.mkdir(exist_ok=True)
    rotating_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES_FOR_LOG_FILE, backupCount=BACKUP_COUNT
    )
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[rotating_handler]
    )
