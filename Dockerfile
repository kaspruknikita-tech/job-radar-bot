FROM python:3.12-slim

WORKDIR /app

ENV POETRY_VIRTUALENVS_CREATE=false

RUN pip install --no-cache-dir poetry==2.3.2

COPY pyproject.toml poetry.lock ./

RUN poetry install --only main --no-root --no-interaction --no-ansi

RUN playwright install-deps chromium && playwright install chromium

COPY . .

CMD ["python", "bot_app.py"]
