"""
Полная выгрузка вакансий за 7 дней со ВСЕХ страниц.
Сохраняет в CSV: и прошедшие фильтр, и отсеянные — с пометкой.

Использование:
    poetry run python export_all.py
"""

import csv
import time
import logging

import requests
import config
from parsers.hh import HHParser, SEARCH_QUERIES, TITLE_ONLY_QUERIES, HH_API_URL
from filters.stopwords import apply_filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
logger = logging.getLogger(__name__)

PERIOD = 7
PER_PAGE = 100
MAX_PAGES = 20
DELAY = 0.25


def search_all_pages(query: str, extra_params: dict = None) -> list[dict]:
    """Забирает ВСЕ страницы по одному запросу."""
    headers = {"User-Agent": config.HH_USER_AGENT}
    all_items = []

    for page in range(MAX_PAGES):
        params = {
            "text": query,
            "per_page": PER_PAGE,
            "page": page,
            "order_by": "publication_time",
            "period": PERIOD,
        }
        if extra_params:
            params.update(extra_params)
        try:
            time.sleep(DELAY)
            resp = requests.get(HH_API_URL, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            all_items.extend(items)

            total_pages = data.get("pages", 0)
            logger.info(
                "  [%s] стр %d/%d, получено %d",
                query, page + 1, total_pages, len(items),
            )

            if page + 1 >= total_pages or not items:
                break
        except requests.RequestException:
            logger.exception("Ошибка на стр %d для '%s'", page, query)
            break

    return all_items


def main():
    parser = HHParser()
    seen_ids: set[str] = set()
    all_vacancies = []

    def collect(query, extra_params=None):
        logger.info("Запрос: %s %s", query, extra_params or "")
        items = search_all_pages(query, extra_params)
        for item in items:
            vid = str(item.get("id", ""))
            if vid and vid not in seen_ids:
                seen_ids.add(vid)
                parsed = parser._parse_item(item)
                if parsed:
                    all_vacancies.append(parsed)

    for query in SEARCH_QUERIES:
        collect(query)

    for query in TITLE_ONLY_QUERIES:
        collect(query, extra_params={"search_field": "name"})

    logger.info("Всего уникальных вакансий: %d", len(all_vacancies))

    results = []
    for v in all_vacancies:
        passed = apply_filters(v)
        results.append({
            "status": "PASSED" if passed else "REJECTED",
            "title": v.get("title", ""),
            "company": v.get("company", ""),
            "location": v.get("location", ""),
            "salary_min": v.get("salary_min", ""),
            "salary_max": v.get("salary_max", ""),
            "currency": v.get("currency", ""),
            "work_format": v.get("work_format", ""),
            "url": v.get("url", ""),
        })

    passed_count = sum(1 for r in results if r["status"] == "PASSED")
    rejected_count = len(results) - passed_count

    output_file = "export_vacancies.csv"
    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    logger.info("Готово! Сохранено в %s", output_file)
    logger.info("Прошли фильтр: %d, отсеяно: %d, всего: %d", passed_count, rejected_count, len(results))


if __name__ == "__main__":
    main()
