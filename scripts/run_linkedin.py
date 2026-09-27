"""
Локальный прогон ТОЛЬКО источника LinkedIn (python-jobspy) — минуя Railway.

Зачем отдельно: LinkedIn режет дата-центровые IP (Railway) → на проде нужен
residential-прокси. С домашнего (резидентного) IP работает без прокси, поэтому
LinkedIn-ветку гоняем локально по cron, а на Railway крутятся остальные источники.

Пишет в ту же БД и Google Sheets, что и основной цикл (полный пайплайн:
dedup → фильтры → insert → скоринг с визовым бонусом → экспорт).

Запуск:
    poetry run python scripts/run_linkedin.py

Cron (пример, каждые 3 часа с 10 до 22):
    0 10-22/3 * * * cd /path/to/research-ux-jobs && poetry run python scripts/run_linkedin.py >> linkedin.log 2>&1
"""

import logging

import database
import scoring
from scheduler import run_cycle
from parsers.jobspy_linkedin import JobSpyLinkedInParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    database.init_db()
    # То же подключение, что в bot_app.main — иначе визовый бонус молчит.
    scoring.enable_visa_lookup(database.is_visa_sponsor)

    result = run_cycle(parsers=[JobSpyLinkedInParser()])
    logger.info("LinkedIn прогон завершён: %s", result)


if __name__ == "__main__":
    main()
