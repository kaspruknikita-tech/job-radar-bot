"""
Парсер hirify.me через JSON API (https://api.hirify.me).

Auth-приоритет:
  1. HIRIFY_COOKIES (JSON-список от playwright/gen_hirify_cookies.py) — для Google OAuth.
  2. HIRIFY_EMAIL + HIRIFY_PASSWORD через Sanctum — для нативных аккаунтов.
  3. Анонимно — company_title будет '%hirify_global%', fallback на linkedin-слаг.

Проверка авторизации: GET /api/profile (401 анону, 200 авторизованному).
"""

import json
import logging
import time
import urllib.parse

import requests

import config
from bot.alerts import send_alert
from parsers.base import BaseParser
from user_profile import P

logger = logging.getLogger(__name__)

API_BASE = "https://api.hirify.me"
WEB_BASE = "https://hirify.me"

SEARCH_QUERIES = P.SEARCH_HIRIFY  # правится в profile/profile.py

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_HIDDEN_PLACEHOLDER = "%hirify_global%"
_PER_PAGE = 50
_MAX_PAGES = 5
_DETAIL_DELAY = 0.3  # сек, 60 req/min лимит API


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": _UA,
        "Accept": "application/json",
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/",
    })
    return s


def _apply_cookies(session: requests.Session, cookies_json: str) -> int:
    """Заливает cookies от playwright (gen_hirify_cookies.py) в requests.Session.
    Формат: JSON-список dict'ов с полями name/value/domain. Возвращает число загруженных."""
    try:
        items = json.loads(cookies_json)
    except Exception:
        logger.warning("[hirify] HIRIFY_COOKIES не парсится как JSON")
        return 0
    n = 0
    for c in items if isinstance(items, list) else []:
        try:
            session.cookies.set(
                name=c["name"],
                value=c["value"],
                domain=c.get("domain") or ".hirify.me",
                path=c.get("path") or "/",
            )
            n += 1
        except Exception:
            continue
    return n


def _is_authed(session: requests.Session) -> bool:
    """GET /api/profile — 200 авторизованному, 401 анону."""
    try:
        r = session.get(f"{API_BASE}/api/profile", timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def _login_password(session: requests.Session) -> bool:
    """Sanctum CSRF + POST /auth/login. Только для нативных hirify-аккаунтов
    (не Google OAuth — там пароль от Google и /auth/login его не примет)."""
    if not (config.HIRIFY_EMAIL and config.HIRIFY_PASSWORD):
        return False
    try:
        session.get(f"{API_BASE}/sanctum/csrf-cookie", timeout=10)
        xsrf_raw = session.cookies.get("XSRF-TOKEN", "")
        if not xsrf_raw:
            logger.warning("[hirify] не получен XSRF-TOKEN")
            return False
        xsrf = urllib.parse.unquote(xsrf_raw)
        resp = session.post(
            f"{API_BASE}/auth/login",
            json={"email": config.HIRIFY_EMAIL, "password": config.HIRIFY_PASSWORD},
            headers={"X-XSRF-TOKEN": xsrf, "Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("[hirify] password-логин успешен")
            return True
        logger.warning("[hirify] password-логин неудачен: HTTP %s %s",
                       resp.status_code, (resp.text or "")[:200])
        return False
    except Exception:
        logger.exception("[hirify] Ошибка password-логина")
        return False


def _authenticate(session: requests.Session) -> str:
    """Возвращает метку режима: 'cookies' | 'password' | 'anon'."""
    if config.HIRIFY_COOKIES:
        loaded = _apply_cookies(session, config.HIRIFY_COOKIES)
        if loaded and _is_authed(session):
            logger.info("[hirify] auth=cookies (загружено %d cookies)", loaded)
            return "cookies"
        logger.warning("[hirify] HIRIFY_COOKIES не дали авторизации (loaded=%d) — пробую дальше", loaded)
        send_alert(
            "[HIRIFY] Куки протухли — авторизация не прошла, парсер уходит в anon.\n\n"
            "Что сделать сейчас:\n"
            "1. python gen_hirify_cookies.py → залогиниться → скопировать вывод\n"
            "2. Railway → переменная HIRIFY_COOKIES → вставить новое значение\n\n"
            "Чтобы не протухали впредь: задать паролю аккаунту Hirify "
            "(Forgot password, даже если вход через Google) и прописать в Railway "
            "HIRIFY_EMAIL / HIRIFY_PASSWORD — тогда парсер логинится сам каждый цикл, "
            f"куки не нужны.\n{config.TELEGRAM_ALERT_MENTION}"
        )
        # Чистим cookies, чтобы протухшие не мешали password-логину
        session.cookies.clear()
    if _login_password(session):
        return "password"
    logger.info("[hirify] auth=anon — company через linkedin-fallback")
    return "anon"


def _titleize(slug: str) -> str:
    """'frends-app' → 'Frends App', "victoria's-secret" → "Victoria's Secret".
    Капитализируем только первую букву слова, чтобы не ломать апострофы."""
    words = urllib.parse.unquote(slug).replace("-", " ").split()
    return " ".join(w[:1].upper() + w[1:] for w in words)


def _company_from_linkedin(linkedin_url: str | None) -> str:
    """Из 'https://www.linkedin.com/company/frends-app/people/' извлекает 'Frends App'."""
    if not linkedin_url:
        return ""
    try:
        path = urllib.parse.urlparse(linkedin_url).path.strip("/")
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] == "company":
            return _titleize(parts[1])
    except Exception:
        return ""
    return ""


def _resolve_company(v: dict) -> str:
    title = (v.get("company_title") or "").strip()
    if title and title != _HIDDEN_PLACEHOLDER:
        return title
    # Fallback: linkedin slug
    return _company_from_linkedin(v.get("linkedin"))


def _location(v: dict) -> str:
    """Собирает location из remote_type/regions."""
    regions = v.get("regions") or []
    parts = []
    for r in regions[:2]:
        name = r.get("name_en") or r.get("name") or r.get("code")
        if name:
            parts.append(str(name).replace("_", " ").title())
    if parts:
        return ", ".join(parts)
    remote_type = v.get("remote_type")
    return str(remote_type).replace("_", " ").title() if remote_type else ""


def _work_format(v: dict) -> str | None:
    wf = v.get("work_format")
    if not wf:
        return None
    if isinstance(wf, list):
        return ", ".join(wf) if wf else None
    return str(wf)


def _salary(v: dict) -> tuple[int | None, int | None, str | None]:
    s = v.get("salary") or {}
    if not isinstance(s, dict):
        return None, None, None
    return s.get("min"), s.get("max"), (s.get("currency") or None)


def _fetch_description(session: requests.Session, slug: str) -> str:
    """GET /api/vacancies/{slug} → поле 'text' (HTML)."""
    try:
        r = session.get(f"{API_BASE}/api/vacancies/{slug}", timeout=15)
        if r.status_code != 200:
            logger.debug("[hirify] detail HTTP %s для %s", r.status_code, slug)
            return ""
        data = r.json()
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        return (data.get("text") or data.get("clear_text") or data.get("seo_description") or "") if isinstance(data, dict) else ""
    except Exception:
        logger.debug("[hirify] ошибка detail для %s", slug, exc_info=True)
        return ""


def _normalize(v: dict, description: str) -> dict:
    sal_min, sal_max, currency = _salary(v)
    return {
        "external_id": str(v.get("id") or ""),
        "title": (v.get("original_title") or v.get("title") or "").strip(),
        "company": _resolve_company(v),
        "salary_min": sal_min,
        "salary_max": sal_max,
        "currency": currency,
        "location": _location(v),
        "work_format": _work_format(v),
        "url": f"{WEB_BASE}/jobs/{v.get('slug')}" if v.get("slug") else f"{WEB_BASE}/",
        "description": description,
    }


class HirifyParser(BaseParser):
    source_name = "hirify"
    channel = "global"

    def fetch(self) -> list[dict]:
        session = _make_session()
        auth_mode = _authenticate(session)
        authed = auth_mode != "anon"

        result: list[dict] = []
        seen: set[int] = set()
        skipped_scam = 0

        for query in SEARCH_QUERIES:
            for page in range(1, _MAX_PAGES + 1):
                try:
                    r = session.get(
                        f"{API_BASE}/api/vacancies",
                        params={"search": query, "per_page": _PER_PAGE, "page": page},
                        timeout=15,
                    )
                except Exception:
                    logger.exception("[hirify] Ошибка списка query=%s page=%s", query, page)
                    break
                if r.status_code != 200:
                    logger.warning("[hirify] list HTTP %s query=%s page=%s",
                                   r.status_code, query, page)
                    break
                data = r.json()
                items = data.get("data") or []
                if not items:
                    break
                for v in items:
                    vid = v.get("id")
                    if not vid or vid in seen:
                        continue
                    seen.add(vid)
                    if v.get("is_scam") or v.get("is_potential_scam"):
                        skipped_scam += 1
                        continue
                    slug = v.get("slug") or ""
                    desc = _fetch_description(session, slug) if slug else ""
                    time.sleep(_DETAIL_DELAY)
                    result.append(_normalize(v, desc))
                if page >= (data.get("last_page") or 1):
                    break

            logger.info("[hirify] query=%r → собрано всего: %d", query, len(result))

        if skipped_scam:
            logger.info("[hirify] Отфильтровано scam: %d", skipped_scam)
        logger.info("[hirify] Итого вакансий: %d (auth=%s)", len(result), auth_mode)
        return result
