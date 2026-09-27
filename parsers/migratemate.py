"""
Парсер migratemate.co — курируемая доска US-вакансий с визовым спонсорством.

Сайт за Vercel Security Checkpoint (JS-challenge), голый requests ловит 429.
Проходим headless-браузером с флагом --disable-blink-features=AutomationControlled
(chromium ставится в прод-Docker: `playwright install chromium`).

Листинг по слагам /visa-sponsorship-jobs/<slug>. Данные берём из Next.js RSC-пейлоада
(self.__next_f) — там objectID, компания, локация, визовые типы, зарплата; описание
дотягиваем из JSON-LD ItemList того же документа (совпадает по порядку).

Детальные страницы вакансий за логином, apply — за email-gate, внешнего url работодателя
нет. Поэтому url = страница слага, дедуп по source|objectID, harvest_ats=False.

Зарплата: только годовые суммы (почасовые "$/hr" в JSON-LD ошибочно помечены YEAR —
пропускаем, схема БД хранит суммы без периода). Числа не нормализуем (см. память проекта).

Визовые типы вписываем в конец описания — явный сигнал для визового приора в скоринге.
"""

import json
import logging
import re

from bs4 import BeautifulSoup

from parsers.base import BaseParser

logger = logging.getLogger(__name__)

BASE = "https://migratemate.co"
SLUGS = [
    "ux-researcher",
    "user-researcher",
    "user-experience-researcher",
    "senior-user-researcher",
    "ux-research-manager",
    "ux-research-intern",
    "director-of-research-operations",
]

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_NAV_TIMEOUT = 60_000
_CHALLENGE_TIMEOUT = 45_000
_SETTLE_MS = 3_000

_RELEVANT = (
    "ux", "user experience", "user research", "researcher", "research",
    "usability", "cx", "customer experience", "service design", "insight",
    "design", "product design",
)

_NEXT_F_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.S)
_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in _RELEVANT)


def _decode_next_f(html: str) -> str:
    """Склеивает RSC-чанки Next.js в единый payload-текст."""
    chunks = _NEXT_F_RE.findall(html)
    out = []
    for c in chunks:
        try:
            out.append(c.encode().decode("unicode_escape"))
        except (UnicodeDecodeError, UnicodeEncodeError):
            out.append(c)
    return "".join(out)


def _extract_jobs_array(blob: str) -> list[dict]:
    """Вырезает первый сбалансированный JSON-массив с ключом objectID."""
    i = blob.find('"objectID"')
    if i < 0:
        return []
    start = blob.rfind("[", 0, i)
    if start < 0:
        return []
    depth = 0
    end = -1
    for j in range(start, len(blob)):
        ch = blob[j]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = j
                break
    if end < 0:
        return []
    try:
        arr = json.loads(blob[start:end + 1])
    except json.JSONDecodeError:
        return []
    return [x for x in arr if isinstance(x, dict) and x.get("objectID")]


def _extract_descriptions(html: str) -> dict[str, str]:
    """title (нормализованный) -> текст описания из JSON-LD ItemList."""
    result: dict[str, str] = {}
    for raw in _LD_RE.findall(html):
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not (isinstance(d, dict) and d.get("@type") == "ItemList"):
            continue
        for li in d.get("itemListElement", []):
            jp = li.get("item") or {}
            title = (jp.get("title") or "").strip().lower()
            desc_html = jp.get("description") or ""
            if title and desc_html:
                result[title] = BeautifulSoup(desc_html, "html.parser").get_text(" ", strip=True)
    return result


def _parse_salary(job: dict) -> tuple[int | None, int | None, str | None]:
    """Годовые суммы из RSC. Почасовые ('/hr') пропускаем."""
    proc = (job.get("salary_processed") or "").lower()
    if "/hr" in proc or "/hour" in proc or "hour" in proc:
        return None, None, None

    def _num(v):
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return None

    smin, smax = _num(job.get("salary_min")), _num(job.get("salary_max"))
    if not smin and not smax:
        return None, None, None
    return smin, smax, "USD"


def _visa_line(job: dict) -> str:
    """Строка визовых типов для явного сигнала в описании."""
    types = job.get("visa_types_sponsored") or []
    labels = [str(t).split("|")[0].strip() for t in types if t]
    labels = [x for x in labels if x]
    if not labels:
        return ""
    return "Visa sponsorship offered: " + ", ".join(dict.fromkeys(labels)) + "."


def parse_listing(html: str, slug: str) -> list[dict]:
    """Разбирает SSR-документ слага в список сырых вакансий."""
    blob = _decode_next_f(html)
    jobs = _extract_jobs_array(blob)
    if not jobs:
        logger.warning("[migratemate] %s: не нашёл массив вакансий в RSC", slug)
        return []

    descriptions = _extract_descriptions(html)
    url = f"{BASE}/visa-sponsorship-jobs/{slug}"

    result = []
    for job in jobs:
        title = (job.get("title") or "").strip()
        if not title or not _is_relevant(title):
            continue

        desc = descriptions.get(title.lower(), "")
        visa = _visa_line(job)
        description = (desc + ("\n\n" + visa if visa else "")).strip()

        smin, smax, currency = _parse_salary(job)

        location = (job.get("location") or "").strip()
        work_format = (job.get("work_location_type") or "").strip() or None
        posted_at = job.get("date_posted") or None

        result.append({
            "external_id": job["objectID"],
            "title": title,
            "company": (job.get("company") or "").strip(),
            "salary_min": smin,
            "salary_max": smax,
            "currency": currency,
            "location": location,
            "work_format": work_format,
            "url": url,
            "description": description,
            "posted_at": posted_at,
        })
    return result


def _fetch_html(page, url: str) -> str | None:
    """Грузит страницу и ждёт прохождения Vercel-challenge."""
    page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
    try:
        page.wait_for_function(
            "!document.title.includes('Vercel Security Checkpoint')",
            timeout=_CHALLENGE_TIMEOUT,
        )
    except Exception:
        logger.warning("[migratemate] Не прошли challenge: %s", url)
        return None
    page.wait_for_timeout(_SETTLE_MS)
    return page.content()


class MigrateMateParser(BaseParser):
    source_name = "migratemate"
    channel = "global"
    harvest_ats = False  # нет внешних apply-url (детали за логином)

    def fetch(self) -> list[dict]:
        from playwright.sync_api import sync_playwright

        seen: set[str] = set()
        result: list[dict] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            ctx = browser.new_context(user_agent=_UA, locale="en-US")
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            page = ctx.new_page()
            try:
                for slug in SLUGS:
                    url = f"{BASE}/visa-sponsorship-jobs/{slug}"
                    try:
                        html = _fetch_html(page, url)
                    except Exception:
                        logger.warning("[migratemate] Сбой загрузки %s", slug)
                        continue
                    if not html:
                        continue
                    for vac in parse_listing(html, slug):
                        if vac["external_id"] in seen:
                            continue
                        seen.add(vac["external_id"])
                        result.append(vac)
            finally:
                browser.close()

        logger.info("[migratemate] Итого уникальных вакансий: %d", len(result))
        return result
