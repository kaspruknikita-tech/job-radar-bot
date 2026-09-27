"""
Парсер вакансий с hh.ru через публичный API.
Документация: https://api.hh.ru/openapi/redoc#tag/Poisk-vakansij

Двухшаговая схема:
1. GET /vacancies?text=... — получаем список ID и сниппеты
2. GET /vacancies/{id} — получаем полную карточку с описанием и навыками
"""

import logging
import re
import time

import requests

import config
from filters.stopwords import apply_filters
from parsers.base import BaseParser
from user_profile import P

logger = logging.getLogger(__name__)

# === OAuth токен ===
# Только в памяти. В БД хранить секреты опасно (дамп БД = утечка токена).
# Цена решения — лишний запрос к hh.ru при рестарте процесса (раз в сутки).
_token: str | None = None
_token_expires_at: float = 0
_token_retry_after: float = 0


def _get_token() -> str | None:
    """Возвращает актуальный OAuth-токен.
    Кэш только в памяти. При неудаче не повторяет попытку 5 минут."""
    global _token, _token_expires_at, _token_retry_after

    if not config.HH_CLIENT_ID or not config.HH_CLIENT_SECRET:
        return None

    if _token and time.time() < _token_expires_at - 60:
        return _token

    if time.time() < _token_retry_after:
        return None

    try:
        resp = requests.post(
            "https://hh.ru/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": config.HH_CLIENT_ID,
                "client_secret": config.HH_CLIENT_SECRET,
            },
            headers={"User-Agent": config.HH_USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        _token = data["access_token"]
        _token_expires_at = time.time() + data.get("expires_in", 86400)
        logger.info("hh.ru OAuth токен получен")
        return _token
    except Exception:
        logger.exception("Не удалось получить OAuth токен hh.ru")
        _token_retry_after = time.time() + 300
        return None


def _headers() -> dict:
    headers = {"User-Agent": config.HH_USER_AGENT}
    token = _get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# === Поисковые запросы ===

SEARCH_QUERIES = P.SEARCH_HH  # правится в profile/profile.py

TITLE_ONLY_QUERIES = P.SEARCH_HH_TITLE_ONLY  # правится в profile/profile.py

SEARCH_AREAS = P.SEARCH_HH_AREAS  # правится в profile/profile.py

HH_API_URL = "https://api.hh.ru/vacancies"
DETAIL_REQUEST_DELAY = 0.3
# Пауза между поисковыми запросами: масок много, hh банит IP за плотную серию.
SEARCH_REQUEST_DELAY = 0.5
HIGHLIGHT_TAG_RE = re.compile(r"</?highlighttext>")


class HHParser(BaseParser):
    source_name = "hh.ru"
    channel = "ru"

    def fetch(self) -> list[dict]:
        all_vacancies = []
        seen_ids: set[str] = set()
        self._blocked = False

        for query in SEARCH_QUERIES:
            if self._blocked:
                break
            self._collect(query, seen_ids, all_vacancies)

        for query in TITLE_ONLY_QUERIES:
            if self._blocked:
                break
            self._collect(query, seen_ids, all_vacancies, search_field="name")

        if self._blocked:
            logger.error(
                "hh.ru отдаёт 403 — IP заблокирован. Проверь HH_USER_AGENT "
                "(должен содержать реальный контакт) и HH_CLIENT_ID/HH_CLIENT_SECRET. "
                "Собрано до блокировки: %d",
                len(all_vacancies),
            )
        return all_vacancies

    def _collect(self, query, seen_ids, result, search_field=None):
        """Забирает вакансии по запросу и добавляет новые в result."""
        items = self._search(query, search_field=search_field)
        for item in items:
            vid = str(item.get("id", ""))
            if vid and vid not in seen_ids:
                seen_ids.add(vid)
                base = self._parse_item(item)
                if not base:
                    continue
                # Отсекаем по заголовку до детального запроса: масок много,
                # лишние карточки = лишний трафик и риск бана.
                if not apply_filters(base) or self.is_known(vid):
                    continue
                detail = self._fetch_detail(vid)
                if detail:
                    base["description"] = detail.get("description", base["description"])
                    base["key_skills"] = detail.get("key_skills", [])
                    base["work_format_raw"] = detail.get("work_format_raw", [])
                    base["schedule"] = detail.get("schedule", {})
                base["work_format"] = self._map_work_format(base)
                result.append(base)

    def _search(self, query: str, per_page: int = 50, search_field: str = None) -> list[dict]:
        """Один поисковый запрос к API hh.ru."""
        headers = _headers()
        params = {
            "text": query,
            "per_page": per_page,
            "page": 0,
            "order_by": "publication_time",
            "period": 7,
            "area": SEARCH_AREAS,
        }
        if search_field:
            params["search_field"] = search_field
        try:
            time.sleep(SEARCH_REQUEST_DELAY)
            resp = requests.get(HH_API_URL, headers=headers, params=params, timeout=15)
            if resp.status_code == 403:
                self._blocked = True
                return []
            resp.raise_for_status()
            data = resp.json()
            return data.get("items", [])
        except requests.RequestException:
            logger.exception("Ошибка запроса к hh.ru: query=%s", query)
            return []

    def _fetch_detail(self, vacancy_id: str) -> dict | None:
        """Запрашивает полную карточку вакансии по ID."""
        url = f"{HH_API_URL}/{vacancy_id}"
        headers = _headers()
        try:
            time.sleep(DETAIL_REQUEST_DELAY)
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return {
                "description": data.get("description", ""),
                "key_skills": [
                    s.get("name", "") for s in data.get("key_skills", [])
                ],
                "work_format_raw": data.get("work_format") or [],
                "schedule": data.get("schedule") or {},
            }
        except requests.RequestException:
            logger.warning("Не удалось получить карточку вакансии %s", vacancy_id)
            return None

    def _parse_item(self, item: dict) -> dict | None:
        """Преобразует элемент из списка в наш формат."""
        try:
            salary = item.get("salary") or {}
            return {
                "external_id": str(item["id"]),
                "title": item.get("name", ""),
                "company": (item.get("employer") or {}).get("name", ""),
                "salary_min": salary.get("from"),
                "salary_max": salary.get("to"),
                "currency": salary.get("currency"),
                "location": (item.get("area") or {}).get("name", ""),
                "work_format": None,  # заполняется после _fetch_detail в _collect
                "url": item.get("alternate_url", ""),
                # Опыт из hh (noExperience / between1And3 / between3And6 / moreThan6) — бонус в скоринге.
                "experience": (item.get("experience") or {}).get("id"),
                "published_at": item.get("published_at"),
                "description": (item.get("snippet") or {}).get("requirement", ""),
                "snippet": self._extract_snippet(item),
                "key_skills": [],
            }
        except (KeyError, TypeError):
            logger.exception("Не удалось распарсить вакансию: %s", item.get("id"))
            return None

    @staticmethod
    def _extract_snippet(item: dict) -> str:
        snippet = item.get("snippet") or {}
        parts = []
        if snippet.get("requirement"):
            parts.append(snippet["requirement"])
        if snippet.get("responsibility"):
            parts.append(snippet["responsibility"])
        text = " | ".join(parts)
        return HIGHLIGHT_TAG_RE.sub("", text)

    @staticmethod
    def _map_work_format(vacancy: dict) -> str | None:
        """Определяет формат работы: Удалёнка / Офис / Гибрид / None.

        Приоритет: новое поле work_format из детальки (массив id),
        fallback — старое поле schedule.name.
        """
        work_format = vacancy.get("work_format_raw") or []
        ids = {item.get("id") for item in work_format if isinstance(item, dict)}

        if "REMOTE" in ids:
            return "Удалёнка"
        if "HYBRID" in ids:
            return "Гибрид"
        if "ON_SITE" in ids:
            return "Офис"

        # Fallback: старое поле schedule
        schedule = vacancy.get("schedule") or {}
        schedule_id = schedule.get("id") if isinstance(schedule, dict) else None
        if schedule_id == "remote":
            return "Удалёнка"

        return None

