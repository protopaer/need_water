import csv
import logging
from config import AsyncSessionLocal
from models import Builds, Offices


def return_office(data) -> Offices:
    """Создает объект Кабинета."""
    return Offices(
        id=int(data['id']),
        abbr=data['abbr'],
        name=data['name'],
        office_number=int(data['office_number']),
        build_id=int(data['building_id'])
    )


def return_build(data) -> Builds:
    """Создает объект Здания."""
    return Builds(
        id=int(data['id']),
        name=data['name'],
    )


async def load_object_in_db(object, dataname):
    """
    Загрузка объекта в базу данных.
    """
    async with AsyncSessionLocal() as session:
        try:
            if dataname == 'office':
                object = return_office(object)
                text_for_log = 'Кабинета'
            elif dataname == 'build':
                object = return_build(object)
                text_for_log = 'Здания'
            else:
                logging.error('Неизвестный объект')
                text_for_log = 'чего-то еще!'

            session.add(object)
            await session.commit()
        except Exception as e:
            await session.rollback()
            obj_id = object.get('id')
            logging.error(
                f'Проблема с загрузкой {text_for_log}:{obj_id}.'
                f'Ошибка: {e}',
                exc_info=True
            )


async def upload_dataset(dataname):
    """
    Чтение таблицы CSV и построчное создание записей в БД.
    """
    with open(
        f'dataset/dataset_{dataname}.csv',
        mode='r',
        encoding='utf-8'
    ) as file:
        csv_reader = csv.DictReader(file)
        for row in csv_reader:
            await load_object_in_db(row, dataname)


async def all_upload():
    """
    Загружает все данные по Кабинетам и Зданиям в базу.
    """
    logging.info('Старт переноса данных в базу.')
    await upload_dataset('build')
    logging.info('Здания загружены.')
    await upload_dataset('office')
    logging.info('Успешная загрузка базы данных.')
