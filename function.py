from random import randint
from typing import Optional

from models import Offices


def string_generate():
    """Генерирует случайное число в телефонном справочнике."""
    return randint(0, 9)


def return_office(session, office_id) -> Optional[Offices]:
    """Возвращает кабинет."""
    return session.query(Offices).filter(Offices.id == office_id).first()
