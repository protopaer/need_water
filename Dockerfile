FROM python:3.9-slim
WORKDIR /app

# Создаем директорию для блокировочного файла
RUN mkdir -p /tmp && chmod 777 /tmp

COPY requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir
COPY . .
CMD ["python", "run_bot.py"]
