"""
Точка входа. Запускает бота.

Использование:
    poetry run python main.py              — запуск в режиме планировщика
    poetry run python main.py --once       — один цикл и выход (для тестов)
    poetry run python main.py --init-db    — только создать БД
"""

import sys
import logging

import config
import database
from scheduler import run_cycle, start_scheduler


def setup_logging() -> None:
    """Настраивает логирование в консоль."""
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> None:
    setup_logging()
    logger = logging.getLogger("main")

    # Проверяем конфиг
    errors = config.validate()
    if errors:
        for e in errors:
            logger.error("Конфиг: %s", e)
        if "--init-db" not in sys.argv:
            logger.error("Заполните .env и перезапустите. Выходим.")
            sys.exit(1)

    # Инициализируем БД
    database.init_db()

    # Режимы запуска
    if "--init-db" in sys.argv:
        logger.info("БД инициализирована. Готово.")
        return

    if "--once" in sys.argv:
        logger.info("Запуск одного цикла...")
        run_cycle()
        return

    # Режим по умолчанию — планировщик
    logger.info("Запускаем планировщик...")
    start_scheduler()


if __name__ == "__main__":
    main()
