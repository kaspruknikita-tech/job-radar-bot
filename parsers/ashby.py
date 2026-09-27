"""
Парсер Ashby Job Board API.
Публичный, без авторизации. Итерируется по списку компаний.
API: https://api.ashbyhq.com/posting-api/job-board/{board_token}?includeCompensation=true
"""

import logging
import time

import requests

from parsers._ats_tokens import merge_companies
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

API_URL = "https://api.ashbyhq.com/posting-api/job-board/{board_token}?includeCompensation=true"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 2
RETRY_BACKOFF_SEC = 5

# Верифицированные board_token компаний на Ashby (API возвращает 200).
# Токены регистрозависимы — берём как в jobs.ashbyhq.com/{token}.
COMPANIES = [
    # AI / ML / dev tools
    "OpenAI", "Linear", "posthog", "ramp", "lovable", "abridge",
    "matter-intelligence", "magicschool", "apify",
    # Продуктовые / B2B / SaaS
    "notion", "Superhuman Platform Inc", "patreon", "wetransfer",
    "Strava", "duck-duck-go", "parafin", "welltech", "sleeper",
    "atticus", "creditgenie", "cointracker", "dailypay",
    "handshake", "better-mortgage", "skydropx",
    # Прочее (вакансии активны/были активны)
    "ruby-labs", "intus", "suno", "Vetcove",
    "thatgamecompany", "mobbin.com",
    # Найдено через google site:jobs.ashbyhq.com (2026-05)
    "1password", "betterup", "photoroom", "kalshi", "trainline",
    "method", "liveflow", "seconddinner", "mazedesign", "jimdo.com",
    "contrast-security", "iacollaborative", "Fuel-Cycle", "M-KOPA",
    "generalintelligencecompany", "latamcent",
    # Расширенный гугл + TheirStack топ-10 (2026-05)
    "kraken.com", "super.com", "n8n", "multiverse", "suzy", "pebl",
    "listenlabs", "nexxen", "comity", "keyrock", "scientech-research",
    "blockhouse", "wincent", "monad.foundation", "wormholelabs",
    "rwazi", "strella", "global-x-etfs", "rallyuxr", "bettermile",
    "apron", "wokelo-ai", "airapps",
    "alan", "renuity", "directive",
    # Авто-добавлено discover_ats_by_name.py 2026-05-29
    "AirGarage",
    "Airbyte",
    "Airtable",
    "Andela",
    "Astronomer",
    "Buffer",
    "Capchase",
    "Checkly",
    "ClickUp",
    "Close",
    "ClubHouse",
    "Deel",
    "Docker",
    "Envoy",
    "Gitbook",
    "Gridium",
    "Gruntwork",
    "Headway",
    "Hopper",
    "Hubstaff",
    "InfluxData",
    "Instructure",
    "Juno",
    "Kraken",
    "Lifen",
    "Lightspeed",
    "Litmus",
    "Loft",
    "Mapbox",
    "MeridianLink",
    "Mux",
    "Nuna",
    "PayScale",
    "Percona",
    "Pleo",
    "Prelude",
    "Primer",
    "Procurify",
    "Quora",
    "Raft",
    "ReCharge",
    "Reddit",
    "Replit",
    "Spruce",
    "Squad",
    "TestGorilla",
    "Truelogic",
    "Vercel",
    "WebFX",
    "YAZIO",
    "Zapier",
    "aim",
    "ghost",
    "helpscout",
    "human",
    "infinite",
    "jolly",
    "lambda",
    "navi",
    "prime",
    "socket",
    "stickermule",
    "vast",
    "virtahealth",
    # Авто-добавлено discover_ats_by_name.py 2026-05-29
    "Affinity",
    "Ambient.ai",
    "Amplitude",
    "Armory",
    "Benevity",
    "Binti",
    "Bolt",
    "Castle",
    "Change",
    "Clever",
    "Commure",
    "Crunchbase",
    "Deepnote",
    "Demandbase",
    "Expensify",
    "Fin",
    "Gainsight",
    "GoodData",
    "Gorgias",
    "HackerOne",
    "Harmonic",
    "Homebase",
    "Honeybook",
    "Kong",
    "Layer",
    "Marqeta",
    "Mercury",
    "Mosaic",
    "Noyo",
    "Nylas",
    "Plaid",
    "Planet",
    "Poshmark",
    "Quantcast",
    "ReadMe",
    "Rescale",
    "SavvyMoney",
    "Sentry",
    "Snapdocs",
    "Stellar",
    "SurveyMonkey",
    "Talkdesk",
    "Thumbtack",
    "Verkada",
    "Vivun",
    "Xero",
    "alpha",
    "apollo-graphql",
    "cadre",
    "canopy",
    "canvas-medical",
    "change",
    "collective",
    "dave",
    "figure",
    "frontapp",
    "fundingcircle",
    "grand",
    "grandrounds",
    "healthgorilla",
    "jane",
    "joor",
    "junipersquare",
    "kestra",
    "kindred",
    "launchdarkly",
    "leap",
    "luxor",
    "menlo",
    "nerdwallet",
    "newfront",
    "notable",
    "openrouter",
    "railway",
    "relay",
    "render",
    "resend",
    "revenuecat",
    "runway",
    "searchapi",
    "sequoia",
    "sierra",
    "siftscience",
    "silver",
    "snowflake",
    "stash",
    "supabase",
    "svix",
    "switchboard",
    "tempo",
    "temporal",
    "workos",
    "zero",
    # Авто-добавлено discover_ats_by_name.py 2026-05-29
    "red-oak",
    "sift",
    # Авто-добавлено discover_ats_by_name.py 2026-05-30
    "abundant",
    "backmarket",
    "brigit",
    "buildout",
    "faculty",
    "prodigy-education",
    "prokeep",
]

WHITELIST = [
    "ux researcher", "ux research",
    "user researcher", "user research",
    "product researcher", "design researcher",
    "usability researcher", "usability research",
    "cx researcher", "cx research",
    "consumer insights", "user insights",
    "ux writer", "content designer",
    "usability", "user experience researcher",
]


def all_companies() -> list[str]:
    """SEED (COMPANIES) + авто-найденные токены из БД."""
    return merge_companies(COMPANIES, "ashby")


def _is_relevant(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in WHITELIST)


def _extract_work_format(job: dict) -> str:
    if job.get("isRemote"):
        return "Remote"
    wt = (job.get("workplaceType") or "").strip()
    if wt:
        return wt  # "Hybrid", "Onsite", etc.
    return ""


def _extract_salary(job: dict) -> tuple[int | None, int | None, str | None]:
    """Берёт первый Salary-компонент с заполненными min/max."""
    comp = job.get("compensation") or {}
    for c in comp.get("summaryComponents") or []:
        if c.get("compensationType") == "Salary" and c.get("minValue") and c.get("maxValue"):
            return c.get("minValue"), c.get("maxValue"), c.get("currencyCode")
    return None, None, None


class AshbyParser(BaseParser):
    source_name = "ashby"
    channel = "global"
    harvest_ats = False  # сам ATS — url уже его токен

    def _fetch_board(self, board_token: str, url: str) -> dict | None:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.get(url, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
            except requests.Timeout:
                err_type, err_detail = "Timeout", f"{REQUEST_TIMEOUT}s"
            except requests.HTTPError as e:
                code = getattr(e.response, "status_code", "?")
                err_type, err_detail = "HTTPError", str(code)
                if code in (401, 403, 404):
                    logger.warning("[ashby] %s — %s %s (no retry)", board_token, err_type, err_detail)
                    return None
            except requests.RequestException as e:
                err_type, err_detail = e.__class__.__name__, str(e)

            if attempt < MAX_RETRIES:
                logger.info("[ashby] %s — %s %s, retry %d/%d через %ds",
                            board_token, err_type, err_detail, attempt, MAX_RETRIES, RETRY_BACKOFF_SEC)
                time.sleep(RETRY_BACKOFF_SEC)
            else:
                logger.warning("[ashby] %s — %s %s (исчерпаны попытки)",
                               board_token, err_type, err_detail)
        return None

    def fetch(self) -> list[dict]:
        result = []
        for board_token in all_companies():
            url = API_URL.format(board_token=board_token)
            data = self._fetch_board(board_token, url)
            if data is None:
                continue

            for job in data.get("jobs", []):
                if not job.get("isListed", True):
                    continue
                title = (job.get("title") or "").strip()
                if not _is_relevant(title):
                    continue
                salary_min, salary_max, currency = _extract_salary(job)
                result.append({
                    "external_id": str(job.get("id", "")),
                    "title": title,
                    "company": board_token,
                    "salary_min": salary_min,
                    "salary_max": salary_max,
                    "currency": currency,
                    "location": job.get("location", "") or "",
                    "work_format": _extract_work_format(job),
                    "url": job.get("jobUrl", "") or job.get("applyUrl", ""),
                    "description": job.get("descriptionHtml", "") or job.get("descriptionPlain", ""),
                })

        return result
