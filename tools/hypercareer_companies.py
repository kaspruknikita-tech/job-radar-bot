"""
Разбор публичной таблицы HyperCareer со списком компаний, нанимающих
русскоязычных специалистов.

Что делает:
1. Тянет таблицу через gviz-эндпоинт (обычный CSV-export отдаёт 401).
2. Для каждой компании открывает карьерный сайт и собирает исходящие ссылки.
3. Прогоняет ссылки через штатный ATS-харвест — найденные борды
   greenhouse/ashby/lever/smartrecruiters/bamboohr попадают в БД,
   и следующий цикл парсеров начнёт тянуть их вакансии напрямую.
4. С --probe дополнительно подбирает токен по названию компании.

Запуск:
    python3 tools/hypercareer_companies.py            # только ссылки с careers-страниц
    python3 tools/hypercareer_companies.py --probe    # + подбор по имени (долго)
    python3 tools/hypercareer_companies.py --limit 20
"""

import argparse
import csv
import io
import logging
import sys
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

import database  # noqa: E402
from tools.ats_harvest import harvest_ats_tokens, _extract_tokens  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SHEET_ID = "1vO8bLxR3kzz7VNTuHlZhIqmgedezKosX8Vb_Elu6Wbc"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def fetch_companies() -> list[dict]:
    """Возвращает [{name, careers_url, industry, location, russian_speaking}]."""
    resp = requests.get(SHEET_URL, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    rows = list(csv.reader(io.StringIO(resp.text)))
    if not rows:
        return []

    out = []
    for row in rows[1:]:
        if len(row) < 2 or not row[0].strip():
            continue
        out.append({
            "name": row[0].strip(),
            "careers_url": row[1].strip(),
            "industry": row[2].strip() if len(row) > 2 else "",
            "location": row[3].strip() if len(row) > 3 else "",
            "russian_speaking": (row[4].strip().upper() == "TRUE") if len(row) > 4 else False,
        })
    return out


def collect_links(url: str) -> list[str]:
    """Все исходящие ссылки карьерной страницы. Пустой список при любой ошибке."""
    if not url.startswith(("http://", "https://")):
        return []
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15, allow_redirects=True)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.debug("не открылась %s: %s", url, exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    links = {resp.url}
    for a in soup.find_all("a", href=True):
        links.add(urljoin(resp.url, a["href"]))
    return list(links)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="обработать только N компаний")
    ap.add_argument("--probe", action="store_true", help="подбирать токен по имени компании")
    args = ap.parse_args()

    companies = fetch_companies()
    if args.limit:
        companies = companies[:args.limit]
    logger.info("компаний в таблице: %d", len(companies))

    database.init_career_sites()
    new_in_registry = 0
    for c in companies:
        if database.save_career_site(
            c["name"], c["careers_url"], c["industry"], c["location"],
            c["russian_speaking"], source="hypercareer",
        ):
            new_in_registry += 1
    logger.info("в реестр career_sites добавлено новых: %d", new_in_registry)

    all_links: list[str] = []
    no_site = 0
    with_ats = 0
    for i, c in enumerate(companies, 1):
        links = collect_links(c["careers_url"])
        if not links:
            no_site += 1
        all_links.extend(links)

        # Есть ссылка на ATS — вакансии заберёт профильный ATS-парсер,
        # карьерный сайт напрямую парсить не нужно.
        if any(_extract_tokens(links).values()):
            database.mark_career_site_has_ats(c["name"])
            with_ats += 1

        if i % 20 == 0:
            logger.info("обойдено %d/%d, ссылок собрано %d", i, len(companies), len(all_links))

    logger.info("карьерных сайтов не открылось: %d", no_site)
    logger.info("компаний с ATS-бордом: %d", with_ats)
    logger.info("ссылок на проверку: %d", len(all_links))

    added = harvest_ats_tokens(all_links, source_label="hypercareer")
    total = sum(len(v) for v in added.values())
    logger.info("новых ATS-токенов: %d", total)
    for ats, tokens in added.items():
        if tokens:
            logger.info("  %s: %s", ats, ", ".join(tokens))

    remaining = database.load_career_sites(only_without_ats=True)
    logger.info("компаний без ATS (пойдут в parsers/career_sites.py): %d", len(remaining))

    if args.probe:
        from tools.discover_ats_by_name import probe_name, _ATS_CHECKS
        import importlib
        existing = {}
        for ats in _ATS_CHECKS:
            mod = importlib.import_module(f"parsers.{ats}")
            existing[ats] = {t.lower() for t in mod.all_companies()}
        found = 0
        for c in companies:
            res = probe_name(c["name"], existing)
            hits = {k: v for k, v in res.items() if k != "name" and v}
            if hits:
                found += 1
                logger.info("  по имени %s -> %s", c["name"], hits)
        logger.info("компаний с токеном по имени: %d", found)


if __name__ == "__main__":
    main()
