from datetime import date
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import joinedload

from models import Offices, Order, TgAccounts


def select_all_offices_in_build(build_id):
    """
    Отбор всех Кабинетов в выбранном Пользователем Здании.
    """
    return (
        select(Offices)
        .where(Offices.build_id == build_id)
        .order_by(func.lower(Offices.abbr))
    )


def check_tg_account_auth(tg_account):
    """
    Поиск в списке авторизованных Пользователей текущего Пользователя.
    """
    return (
        select(TgAccounts)
        .where(
            TgAccounts.account == tg_account,
            TgAccounts.blocked == False
        )
    )


def joinedload_last_office_with_auth_tg_account(tg_account):
    """
    Для текущего Пользователя подтягивается выбранный им ранее Кабинет.
    """
    return (
        check_tg_account_auth(tg_account)
        .options(joinedload(TgAccounts.office))  # Жадная загрузка офиса
    )


def joinedload_building_and_office_with_active_order():
    """
    Для активных Заявок добавляет Здание и Кабинет.
    """
    return (
        select(Order)
        .where(Order.in_archive == False)
        .options(
            joinedload(Order.office)
            .joinedload(Offices.building)
        )
    )


def find_last_office():
    """
    Находит самый свежий Заказ в базе данных.
    """
    return (
        select(Order)
        .order_by(Order.id.desc())  # Сортируем по ID в обратном порядке
        .limit(1)                  # Берем только одну запись
    )


def check_active_orders(office: Offices, today: date):
    """
    Проверка наличия активных заявок для конкретного Кабинета.
    """
    return (
        select(Order)
        .where(
            Order.office_id == office.id,
            or_(
                Order.in_archive == False,  # <-- проверяет выходный
                and_(
                    Order.order_date == today,  # <-- проверяет сегодня
                    Order.in_archive == True
                )
            )
        )
    )


def check_active_orders_for_current_tg_account(tg_account, today: date):
    """
    Проверка наличия активных заявок конкретного Пользователя.
    """
    return select(Order).where(
        and_(
            Order.tg_account_id == tg_account,  # Проверяем пользователя
            Order.order_date == today
        )
    )


def transfers_orders_status_to_archive():
    """
    Перевод статуса активных Заявок в состояние «в архиве».
    """
    return (
        update(Order).
        where(Order.in_archive == False)
        .values(in_archive=True)
    )
