# Образ для Render: бот работает в фоне и сам опрашивает Telegram (polling).
# Токен не кладём в образ. На Render его задают переменной окружения BOT_TOKEN.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

RUN useradd --create-home --uid 1000 bot \
    && chown -R bot:bot /app
USER bot

CMD ["python", "main.py"]
