# import logging

# from aiogram import BaseMiddleware
# from aiogram.exceptions import TelegramNetworkError


# class NetworkErrorMiddleware(BaseMiddleware):
#     async def __call__(self, handler, event, data):
#         try:
#             return await handler(event, data)
#         except TelegramNetworkError as e:
#             logging.error(f'Проблема с сетью: {e}')
#             # Можно добавить отправку уведомления админу
#             # Или можно вернуть какое-то сообщение пользователю
#             return None
#         except Exception as e:
#             logging.error(f'Неожиданная ошибка: {e}', exc_info=True)
#             return None
