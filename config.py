"""
Конфигурация проекта.
Читает переменные окружения из .env и предоставляет их как атрибуты.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Корень проекта — папка, где лежит этот файл
BASE_DIR = Path(__file__).resolve().parent

# Загружаем .env из корня проекта
load_dotenv(BASE_DIR / ".env")


# --- Telegram ---
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_RU: str = os.getenv("TELEGRAM_CHANNEL_RU", "")
TELEGRAM_CHANNEL_GLOBAL: str = os.getenv("TELEGRAM_CHANNEL_GLOBAL", "")
# Два чата модерации: отдельно для RU и Global вакансий.
# Если TELEGRAM_MODERATION_CHAT_RU/GLOBAL не заданы — фолбэк на TELEGRAM_MODERATION_CHAT.
TELEGRAM_MODERATION_CHAT: str = os.getenv("TELEGRAM_MODERATION_CHAT", "")
TELEGRAM_MODERATION_CHAT_RU: str = os.getenv("TELEGRAM_MODERATION_CHAT_RU", "") or os.getenv("TELEGRAM_MODERATION_CHAT", "")
TELEGRAM_MODERATION_CHAT_GLOBAL: str = os.getenv("TELEGRAM_MODERATION_CHAT_GLOBAL", "") or os.getenv("TELEGRAM_MODERATION_CHAT", "")
TELEGRAM_ALERT_CHAT: str = os.getenv("TELEGRAM_ALERT_CHAT", "")
# Кого пинговать в алертах и сводках (например "@user1 @user2"). Пусто — без пинга.
TELEGRAM_ALERT_MENTION: str = os.getenv("TELEGRAM_ALERT_MENTION", "")
TELEGRAM_REPORT_MENTION: str = os.getenv("TELEGRAM_REPORT_MENTION", "")

# --- hh.ru ---
HH_USER_AGENT: str = os.getenv("HH_USER_AGENT", "VacancyParser/0.1")
HH_CLIENT_ID: str = os.getenv("HH_CLIENT_ID", "")
HH_CLIENT_SECRET: str = os.getenv("HH_CLIENT_SECRET", "")

# --- Adzuna ---
ADZUNA_APP_ID: str = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY: str = os.getenv("ADZUNA_APP_KEY", "")

# --- Telethon (парсер Telegram-каналов) ---
TG_API_ID: int = int(os.getenv("TG_API_ID", "0") or "0")
TG_API_HASH: str = os.getenv("TG_API_HASH", "")
TG_SESSION_STRING: str = os.getenv("TG_SESSION_STRING", "")
TG_SOURCE_CHANNELS: list[str] = [
    ch.strip() for ch in os.getenv("TG_SOURCE_CHANNELS", "").split(",") if ch.strip()
]
TG_DAYS_BACK: int = int(os.getenv("TG_DAYS_BACK", "7"))
# Публичные превью t.me/s/: сколько страниц (по ~20 постов) листать назад на канал
TG_PREVIEW_MAX_PAGES: int = int(os.getenv("TG_PREVIEW_MAX_PAGES", "3"))

# --- Hirify ---
HIRIFY_EMAIL: str = os.getenv("HIRIFY_EMAIL", "")
HIRIFY_PASSWORD: str = os.getenv("HIRIFY_PASSWORD", "")
# JSON-список cookies от playwright (gen_hirify_cookies.py) — для аккаунтов через Google OAuth.
HIRIFY_COOKIES: str = os.getenv("HIRIFY_COOKIES", "")

# --- JobSpy (LinkedIn Jobs через python-jobspy) ---
# Резидентные прокси обязательны на проде (Railway = дата-центр IP, LinkedIn режет).
# Формат: "user:pass@host:port,host2:port2" — список через запятую.
JOBSPY_PROXIES: list[str] = [
    p.strip() for p in os.getenv("JOBSPY_PROXIES", "").split(",") if p.strip()
]
# LinkedIn при пустом location отдаёт только США — гео перебираем явным списком.
# Дефолт — гео профиля: удалёнка, Россия и страны релокации (Грузия, Сербия, Кипр).
JOBSPY_LOCATIONS: list[str] = [
    loc.strip() for loc in os.getenv(
        "JOBSPY_LOCATIONS",
        "Remote,Russia,Georgia,Serbia,Cyprus",
    ).split(",") if loc.strip()
]
JOBSPY_RESULTS_WANTED: int = int(os.getenv("JOBSPY_RESULTS_WANTED", "20"))
# Пропускать только вакансии, доступные аудитории СНГ: remote / hybrid / визовый
# спонсор / релокейт. Дешёвый гейт по сигналам ДО платного LLM-скоринга.
JOBSPY_ACCESS_FILTER: bool = os.getenv("JOBSPY_ACCESS_FILTER", "true").lower() == "true"
JOBSPY_HOURS_OLD: int = int(os.getenv("JOBSPY_HOURS_OLD", "0") or "0")  # 0 = без ограничения
# Дотягивать полное описание вакансии (+1 запрос/вакансию, нужно для LLM-скоринга).
JOBSPY_FETCH_DESCRIPTION: bool = os.getenv("JOBSPY_FETCH_DESCRIPTION", "true").lower() == "true"

# --- Railway ---
RAILWAY_API_TOKEN: str = os.getenv("RAILWAY_API_TOKEN", "")
# Порог остатка в USD (кредитный баланс), ниже которого шлётся алерт
RAILWAY_BALANCE_THRESHOLD: float = float(os.getenv("RAILWAY_BALANCE_THRESHOLD", "2.0"))

# --- Профиль соискателя ---
# Всё, что делает бота «вашим»: запросы, фильтры, словари, архетипы, гео — в PROFILE_DIR/profile.py.
PROFILE_DIR: str = os.getenv("PROFILE_DIR") or str(BASE_DIR / "profile")
# Необязательно: карьерные данные для ATS-совпадения (блоки опыта, manifest.md, core.md).
# Нет папки — ATS-часть скоринга отключается, остальное работает.
CAREER_DATA_DIR: str = os.getenv("CAREER_DATA_DIR") or os.path.join(PROFILE_DIR, "career")

# --- Роль-гейт на локальной модели (Ollama) ---
# Правила не отличают «руководителя отдела продаж с CRM» от партнёрской операционки:
# различие смысловое. Вопрос «это про меня?» задаём модели, она читает role-profile.md.
# Выключено — скоринг работает только по правилам, как раньше.
LLM_ROLE_ENABLED: bool = os.getenv("LLM_ROLE_ENABLED", "false").lower() == "true"
ROLE_PROFILE_PATH: str = os.getenv(
    "ROLE_PROFILE_PATH", os.path.join(PROFILE_DIR, "role-profile.md")
)
OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3:8b")
# Профиль ~3k токенов + описание вакансии: дефолтных 4096 не хватает
OLLAMA_NUM_CTX: int = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
# Первый вызов грузит 5 ГБ модели в память — на это уходит больше минуты
OLLAMA_TIMEOUT: int = int(os.getenv("OLLAMA_TIMEOUT", "300"))
OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
# Ниже этой уверенности вердикт модели не отменяет решение правил
LLM_ROLE_MIN_CONFIDENCE: int = int(os.getenv("LLM_ROLE_MIN_CONFIDENCE", "60"))
# Модель подтвердила роль по содержанию обязанностей: словарь этого не видит.
# Нужно прежде всего продуктовым вакансиям — правила режут их за junior и чужой заголовок.
LLM_ROLE_BONUS: int = int(os.getenv("LLM_ROLE_BONUS", "25"))

# --- getmatch.ru ---
# У эндпоинта нет поиска: забираем ленту от свежих и режем белым списком.
GETMATCH_MAX_OFFERS: int = int(os.getenv("GETMATCH_MAX_OFFERS", "400"))

# --- career.habr.com ---
HABR_MAX_PAGES: int = int(os.getenv("HABR_MAX_PAGES", "2"))

# --- rabota.ru ---
# Детальная страница = 1 запрос, поэтому держим потолок на цикл.
RABOTARU_MAX_VACANCIES: int = int(os.getenv("RABOTARU_MAX_VACANCIES", "60"))

# --- remoterocketship.com ---
REMOTEROCKETSHIP_MAX_PAGES: int = int(os.getenv("REMOTEROCKETSHIP_MAX_PAGES", "2"))

# --- jobicy.com ---
JOBICY_COUNT: int = int(os.getenv("JOBICY_COUNT", "50"))

# --- Карьерные сайты компаний (реестр career_sites) ---
# Сколько компаний обходить за цикл: полный обход растянут на несколько циклов,
# чтобы цикл укладывался в PARSE_INTERVAL_MINUTES.
CAREER_SITES_PER_CYCLE: int = int(os.getenv("CAREER_SITES_PER_CYCLE", "25"))

# --- Планировщик ---
PARSE_INTERVAL_MINUTES: int = int(os.getenv("PARSE_INTERVAL_MINUTES", "15"))
# Сколько карточек слать в чат за цикл: лучшие по скору, остальные ждут следующего цикла.
MODERATION_MAX_PER_CYCLE: int = int(os.getenv("MODERATION_MAX_PER_CYCLE", "20"))
# В чат идут только вакансии, опубликованные за последние N дней (нет даты публикации — по дате находки).
MAX_VACANCY_AGE_DAYS: int = int(os.getenv("MAX_VACANCY_AGE_DAYS", "7"))
BALANCE_CHECK_INTERVAL_MINUTES: int = int(os.getenv("BALANCE_CHECK_INTERVAL_MINUTES", "60"))
# Час (МСК), когда шлётся дневная сводка парсеров за прошедший день
DAILY_REPORT_HOUR: int = int(os.getenv("DAILY_REPORT_HOUR", "9"))

# --- База данных ---
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# --- Логирование ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


def validate() -> list[str]:
    """Проверяет, что все обязательные настройки заполнены.
    Возвращает список ошибок (пустой = всё ок)."""
    errors = []
    if not DATABASE_URL:
        errors.append("DATABASE_URL не задан в .env")
    if not GOOGLE_SHEET_ID:
        errors.append("GOOGLE_SHEET_ID не задан в .env")
    return errors

# --- Google Sheets ---
GOOGLE_CREDENTIALS_FILE: str = str(BASE_DIR / "google_credentials.json")
GOOGLE_SHEET_ID: str = os.getenv("GOOGLE_SHEET_ID", "")
