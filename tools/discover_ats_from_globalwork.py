"""
Discovery: тянет ATS-токены из globalwork.ai.

globalwork.ai — агрегатор поверх стандартных ATS. SSR-страница
/en/remote-jobs/usa/{slug} отдаёт ~20 вакансий в RSC-payload, у каждой
jobUrl ведёт на ОРИГИНАЛ (Ashby/Greenhouse/Lever/Workday/...).
Берём эти jobUrl и прогоняем через harvest_ats_tokens — он сам извлекает,
валидирует и пишет в БД токены ashby/greenhouse/lever.

Намеренно НЕ фильтруем слаги по UX-нише — harvest собирает все валидные
борды, whitelist отсеивает на уровне вакансий.

Usage:
    python3 tools/discover_ats_from_globalwork.py
    python3 tools/discover_ats_from_globalwork.py --slugs researcher designer product-manager
    python3 tools/discover_ats_from_globalwork.py --dry-run
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.ats_harvest import _extract_tokens, harvest_ats_tokens

logger = logging.getLogger(__name__)

BASE = "https://globalwork.ai/en/remote-jobs/usa/{slug}"
SITEMAP = "https://globalwork.ai/sitemap_index.xml"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

# Широкие популярные слаги — максимум разных компаний/бордов.
DEFAULT_SLUGS = [
    "researcher", "designer", "product-manager", "data-analyst",
    "software-engineer", "marketing-manager", "recruiter", "accountant",
    "data-scientist", "project-manager", "sales-manager", "customer-success",
]


def _extract_listing(html: str) -> list[dict]:
    """Достаёт data[] из RSC-payload (ключ initialListData)."""
    key = '\\"initialListData\\":'
    i = html.find(key)
    if i < 0:
        return []
    depth = 0
    start = None
    k = i + len(key)
    while k < len(html):
        c = html[k]
        if c == "{":
            if start is None:
                start = k
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                blob = html[start:k + 1]
                break
        k += 1
    else:
        return []
    blob = blob.replace('\\"', '"').replace("\\\\", "\\")
    try:
        return json.loads(blob).get("data", [])
    except json.JSONDecodeError:
        return []


def _fetch(url: str, retries: int = 3) -> str:
    """GET с ретраями — Cloudflare троттлит серии запросов."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 404:
                return ""
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            wait = 5 * (attempt + 1)
            logger.warning("[globalwork] %s — %s, retry через %ds", url, e, wait)
            time.sleep(wait)
    return ""


def collect_job_urls(slugs: list[str], delay: float = 4.0) -> list[str]:
    urls: list[str] = []
    for slug in slugs:
        html = _fetch(BASE.format(slug=slug))
        if not html:
            logger.info("[globalwork] %s — пусто/404", slug)
            continue
        jobs = _extract_listing(html)
        slug_urls = [j["jobUrl"] for j in jobs if j.get("jobUrl")]
        urls.extend(slug_urls)
        logger.info("[globalwork] %s — %d вакансий", slug, len(slug_urls))
        time.sleep(delay)
    return urls


def run_discovery(slugs: list[str] | None = None, delay: float = 4.0,
                  dry_run: bool = False) -> dict[str, list[str]]:
    """Собирает jobUrl из globalwork и харвестит ATS-токены. Возвращает {ats: [добавленные]}."""
    urls = collect_job_urls(slugs or DEFAULT_SLUGS, delay=delay)
    logger.info("[globalwork] собрано jobUrl: %d", len(urls))
    if not urls:
        return {}

    if dry_run:
        found = _extract_tokens(urls)
        for ats, tokens in found.items():
            if tokens:
                logger.info("[dry-run] %s: %d кандидатов: %s",
                            ats, len(tokens), ", ".join(sorted(tokens)))
        return {ats: sorted(t) for ats, t in found.items()}

    added = harvest_ats_tokens(urls, source_label="globalwork")
    total = sum(len(v) for v in added.values())
    logger.info("[globalwork] добавлено новых токенов: %d %s", total, dict(added))
    return added


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--slugs", nargs="+", default=DEFAULT_SLUGS)
    ap.add_argument("--delay", type=float, default=4.0, help="пауза между запросами, сек")
    ap.add_argument("--dry-run", action="store_true", help="не писать в БД, только показать токены")
    args = ap.parse_args()
    run_discovery(args.slugs, delay=args.delay, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
