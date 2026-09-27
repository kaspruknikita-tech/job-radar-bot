"""
Работа с базой данных PostgreSQL.
Создаёт таблицу vacancies, умеет вставлять/читать/обновлять записи.
"""

import json
import logging
import os
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


def _get_connection() -> psycopg2.extensions.connection:
    """Создаёт подключение к PostgreSQL из DATABASE_URL."""
    url = os.environ["DATABASE_URL"]
    # Railway иногда отдаёт postgres://, psycopg2 требует postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url)


def init_db() -> None:
    """Создаёт таблицы, если их нет."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS vacancies (
                    id              SERIAL PRIMARY KEY,
                    external_id     TEXT,
                    source          TEXT NOT NULL,
                    title           TEXT NOT NULL,
                    company         TEXT,
                    salary_min      INTEGER,
                    salary_max      INTEGER,
                    currency        TEXT,
                    location        TEXT,
                    work_format     TEXT,
                    url             TEXT,
                    description     TEXT,
                    snippet         TEXT,
                    hash            TEXT NOT NULL UNIQUE,
                    status          TEXT NOT NULL DEFAULT 'new',
                    channel         TEXT NOT NULL,
                    parsed_at       TEXT NOT NULL,
                    posted_at       TEXT,
                    scheduled_at    TIMESTAMP WITH TIME ZONE
                )
            """)
            cur.execute("""
                ALTER TABLE vacancies
                ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMP WITH TIME ZONE
            """)
            cur.execute("""
                ALTER TABLE vacancies
                ADD COLUMN IF NOT EXISTS moderation_message_id INTEGER
            """)
            # Дата публикации на стороне источника. Нужна для сортировки по свежести:
            # parsed_at говорит когда МЫ нашли, published_at — когда вакансия вышла.
            cur.execute("""
                ALTER TABLE vacancies
                ADD COLUMN IF NOT EXISTS published_at TIMESTAMP WITH TIME ZONE
            """)
            cur.execute("""
                ALTER TABLE vacancies
                ADD COLUMN IF NOT EXISTS experience TEXT
            """)
            # Индекс под дедупликацию по нормализованным заголовку и компании
            cur.execute(f"CREATE INDEX IF NOT EXISTS vacancies_title_company_norm_idx "
                        f"ON vacancies (({_NORM_TITLE}), ({_NORM_COMPANY}))")
            # Решение из карточки: applied / declined, причина отказа и когда решено
            for ddl in (
                "ADD COLUMN IF NOT EXISTS decision TEXT",
                "ADD COLUMN IF NOT EXISTS decision_reason TEXT",
                "ADD COLUMN IF NOT EXISTS decided_at TIMESTAMP WITH TIME ZONE",
            ):
                cur.execute(f"ALTER TABLE vacancies {ddl}")
        conn.commit()
        logger.info("База данных инициализирована (PostgreSQL)")
    finally:
        conn.close()
    init_vacancy_scores()
    init_parser_runs()
    init_ats_tables()
    init_brand_cache()
    init_visa_sponsors()
    init_career_sites()


def init_vacancy_scores() -> None:
    """Создаёт таблицу vacancy_scores, если её нет."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS vacancy_scores (
                    id               SERIAL PRIMARY KEY,
                    vacancy_id       INTEGER NOT NULL REFERENCES vacancies(id),
                    scored_at        TIMESTAMP DEFAULT NOW(),
                    prompt_version   TEXT NOT NULL,
                    tier             VARCHAR(1) NOT NULL,
                    action           TEXT NOT NULL,
                    score            INTEGER NOT NULL,
                    score_breakdown  JSONB,
                    visa_sponsorship TEXT,
                    relocation_support TEXT,
                    remote_policy    TEXT,
                    salary_min       INTEGER,
                    salary_max       INTEGER,
                    salary_currency  TEXT,
                    experience_level TEXT,
                    verbatim_evidence JSONB,
                    pre_filter_blocked BOOLEAN DEFAULT FALSE,
                    reason           TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS vacancy_scores_vacancy_id_idx ON vacancy_scores(vacancy_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS vacancy_scores_tier_idx ON vacancy_scores(tier)")
            cur.execute("CREATE INDEX IF NOT EXISTS vacancy_scores_scored_at_idx ON vacancy_scores(scored_at)")
            # На проде эти колонки добавлены миграциями, в CREATE TABLE их не было —
            # на чистой базе INSERT падал целиком. Держим их здесь, чтобы схема
            # собиралась с нуля одинаково.
            for ddl in (
                "ADD COLUMN IF NOT EXISTS model_used TEXT",
                "ADD COLUMN IF NOT EXISTS latency_ms INTEGER",
                "ADD COLUMN IF NOT EXISTS post_enrichment JSONB",
                "ADD COLUMN IF NOT EXISTS brand_data JSONB",
                # Поля целевого профиля (prompt v3)
                "ADD COLUMN IF NOT EXISTS archetype TEXT",
                "ADD COLUMN IF NOT EXISTS domain_match BOOLEAN",
                "ADD COLUMN IF NOT EXISTS geo_bucket TEXT",
                "ADD COLUMN IF NOT EXISTS english_level_required TEXT",
                "ADD COLUMN IF NOT EXISTS ops_content BOOLEAN",
                # Кодовый скоринг: ATS-совпадение с карьерной OS
                "ADD COLUMN IF NOT EXISTS ats_score INTEGER",
                "ADD COLUMN IF NOT EXISTS ats_details JSONB",
            ):
                cur.execute(f"ALTER TABLE vacancy_scores {ddl}")
        conn.commit()
    finally:
        conn.close()


def init_career_sites() -> None:
    """Реестр компаний с карьерными сайтами (таблица HyperCareer и т.п.).
    Компании без найденного ATS парсятся напрямую — см. parsers/career_sites.py."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS career_sites (
                    id               SERIAL PRIMARY KEY,
                    name             TEXT NOT NULL,
                    url              TEXT NOT NULL,
                    industry         TEXT,
                    location         TEXT,
                    russian_speaking BOOLEAN NOT NULL DEFAULT FALSE,
                    has_ats          BOOLEAN NOT NULL DEFAULT FALSE,
                    source           TEXT,
                    added_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS career_sites_name_idx
                ON career_sites (lower(name))
            """)
        conn.commit()
    finally:
        conn.close()


def save_career_site(
    name: str, url: str, industry: str = "", location: str = "",
    russian_speaking: bool = False, source: str | None = None,
) -> bool:
    """Добавляет компанию в реестр. False — уже была."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO career_sites (name, url, industry, location, russian_speaking, source)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (lower(name)) DO NOTHING
                RETURNING id
                """,
                (name, url, industry, location, russian_speaking, source),
            )
            row = cur.fetchone()
        conn.commit()
        return row is not None
    finally:
        conn.close()


def mark_career_site_has_ats(name: str) -> None:
    """Помечает, что у компании нашёлся ATS-борд — карьерный сайт парсить не нужно."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE career_sites SET has_ats = TRUE WHERE lower(name) = lower(%s)",
                (name,),
            )
        conn.commit()
    finally:
        conn.close()


def load_career_sites(only_without_ats: bool = True) -> list[dict]:
    """Компании из реестра. По умолчанию — только те, у кого ATS не нашёлся."""
    conn = _get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            sql = "SELECT * FROM career_sites"
            if only_without_ats:
                sql += " WHERE has_ats = FALSE"
            sql += " ORDER BY name"
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def init_parser_runs() -> None:
    """Создаёт таблицу parser_runs — посуточная статистика парсеров и фильтров."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS parser_runs (
                    id          SERIAL PRIMARY KEY,
                    run_at      TIMESTAMP WITH TIME ZONE NOT NULL,
                    source      TEXT NOT NULL,
                    parsed      INTEGER NOT NULL DEFAULT 0,
                    duplicates  INTEGER NOT NULL DEFAULT 0,
                    passed      INTEGER NOT NULL DEFAULT 0,
                    rejected    INTEGER NOT NULL DEFAULT 0
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS parser_runs_run_at_idx ON parser_runs(run_at)")
        conn.commit()
    finally:
        conn.close()


def init_ats_tables() -> None:
    """Хранилище авто-найденных ATS-токенов и реестр опробованных имён.
    На Railway ФС эфемерная — токены живут в БД, а не в parsers/*.py."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ats_discovered_tokens (
                    id        SERIAL PRIMARY KEY,
                    ats       TEXT NOT NULL,
                    token     TEXT NOT NULL,
                    added_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    source    TEXT
                )
            """)
            # Регистронезависимый дедуп: один токен на один ATS.
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS ats_tokens_unique_idx
                ON ats_discovered_tokens (ats, lower(token))
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ats_probed_names (
                    id        SERIAL PRIMARY KEY,
                    name      TEXT NOT NULL,
                    ats       TEXT NOT NULL,
                    result    TEXT NOT NULL,
                    tried_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS ats_probed_unique_idx
                ON ats_probed_names (lower(name), ats)
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS ats_tokens_added_at_idx ON ats_discovered_tokens(added_at)")
        conn.commit()
    finally:
        conn.close()


_LEGAL_SUFFIXES = {
    "inc", "llc", "corp", "corporation", "co", "company", "ltd", "limited",
    "llp", "lp", "plc", "gmbh", "ag", "sa", "srl", "bv", "nv", "pvt",
    "private", "group", "holdings", "incorporated", "us", "usa", "america",
    "americas", "international", "global", "technologies", "technology",
    "services", "solutions", "systems", "labs", "studios", "software",
}


def normalize_company(name: str | None) -> str:
    """Нормализует имя компании для матчинга: lower, убирает скобки/пунктуацию,
    срезает хвостовые юридические суффиксы. 'Amazon.com Services LLC' -> 'amazon'."""
    import re as _re
    s = (name or "").lower()
    s = _re.sub(r"\([^)]*\)", " ", s)          # убрать (...)
    s = s.replace("&", " and ").replace(".com", " ")
    s = _re.sub(r"[^a-z0-9 ]", " ", s)         # только буквы/цифры/пробел
    parts = [p for p in s.split() if p]
    # срезаем хвостовые суффиксы (несколько подряд: 'us llp' -> '')
    while len(parts) > 1 and parts[-1] in _LEGAL_SUFFIXES:
        parts.pop()
    return " ".join(parts)


def _domain_root(domain: str | None) -> str:
    """'jobs.stripe.com' -> 'stripe'. Пусто если домен невалиден."""
    d = (domain or "").strip().lower()
    if not d or "." not in d:
        return ""
    host = d.split("/")[0]
    labels = [l for l in host.split(".") if l]
    if len(labels) < 2:
        return ""
    return labels[-2]


_GENERIC_FIRST = {
    "tech", "data", "info", "next", "open", "blue", "soft", "smart", "world",
    "first", "one", "new", "core", "true", "real", "main", "best", "the",
    "digital", "cloud", "media", "health", "care", "pay", "go", "net",
}


def company_match_keys(name: str | None, domain: str | None = None) -> set[str]:
    """Набор ключей под которыми компания может встретиться в вакансии."""
    keys: set[str] = set()
    norm = normalize_company(name)
    if norm:
        keys.add(norm)
        parts = norm.split()
        first = parts[0]
        # Первое слово как ключ только у многословных имён и если оно не generic —
        # иначе 'Tech Mahindra' дал бы ложный матч любой 'Tech ...' вакансии.
        if len(parts) > 1 and len(first) >= 5 and first not in _GENERIC_FIRST:
            keys.add(first)
    root = _domain_root(domain)
    if root and len(root) >= 3 and root not in _GENERIC_FIRST:
        keys.add(root)
    return keys


def init_visa_sponsors() -> None:
    """Реестр компаний-визовых-спонсоров (ellis/h1bdata/myvisajobs).
    Несколько ключей могут указывать на одну компанию (имя, домен). На Railway
    ФС эфемерная — список живёт в БД."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS visa_sponsors (
                    name_key  TEXT PRIMARY KEY,
                    display   TEXT NOT NULL,
                    source    TEXT NOT NULL,
                    domain    TEXT,
                    added_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
            """)
        conn.commit()
    finally:
        conn.close()


def save_visa_sponsor(display: str, source: str, domain: str | None = None) -> int:
    """Пишет все match-ключи компании. Возвращает число новых ключей.
    Дубль-ключ (та же компания из другого источника) игнорируется."""
    keys = company_match_keys(display, domain)
    if not keys:
        return 0
    conn = _get_connection()
    try:
        added = 0
        with conn.cursor() as cur:
            for k in keys:
                cur.execute(
                    """
                    INSERT INTO visa_sponsors (name_key, display, source, domain)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (name_key) DO NOTHING
                    RETURNING name_key
                    """,
                    (k, display, source, domain),
                )
                if cur.fetchone() is not None:
                    added += 1
        conn.commit()
        return added
    finally:
        conn.close()


def save_visa_sponsors_bulk(records: list[tuple[str, str, str | None]]) -> int:
    """Батч-запись спонсоров в одном соединении. records: [(display, source, domain)].
    Возвращает число новых ключей. На порядки быстрее save_visa_sponsor в цикле."""
    rows: list[tuple[str, str, str, str | None]] = []
    for display, source, domain in records:
        for k in company_match_keys(display, domain):
            rows.append((k, display, source, domain))
    if not rows:
        return 0
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            # execute_values — одна SQL-команда на все строки (не round-trip на каждую).
            returned = psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO visa_sponsors (name_key, display, source, domain)
                VALUES %s
                ON CONFLICT (name_key) DO NOTHING
                RETURNING name_key
                """,
                rows,
                fetch=True,
            )
            added = len(returned)
        conn.commit()
        return added
    finally:
        conn.close()


def is_visa_sponsor(company: str | None) -> dict | None:
    """Компания в списке визовых спонсоров? Возвращает {display, source} или None."""
    keys = company_match_keys(company)
    if not keys:
        return None
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT display, source FROM visa_sponsors WHERE name_key = ANY(%s) LIMIT 1",
                (list(keys),),
            )
            row = cur.fetchone()
            if row:
                return {"display": row[0], "source": row[1]}
            return None
    finally:
        conn.close()


def get_visa_sponsor_names() -> list[str]:
    """Уникальные display-имена компаний из реестра — вход для харвеста."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT display FROM visa_sponsors ORDER BY display")
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def count_visa_sponsors() -> int:
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM visa_sponsors")
            return cur.fetchone()[0]
    finally:
        conn.close()


def init_brand_cache() -> None:
    """Кэш брендового скоринга по компании. Hit (если запись свежая по TTL)
    пропускает дорогой веб-вызов Perplexity. Ключ — компания в нижнем регистре."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS brand_cache (
                    company     TEXT PRIMARY KEY,
                    brand_data  JSONB NOT NULL,
                    brand_tag   TEXT,
                    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    hit_count   INTEGER NOT NULL DEFAULT 0
                )
            """)
        conn.commit()
    finally:
        conn.close()


def get_brand_cache(company: str, max_age_days: int = 90) -> dict | None:
    """Возвращает закэшированный brand_data по компании, если запись свежее TTL.
    Промах (нет записи / устарела) → None. При hit инкрементит hit_count."""
    key = " ".join((company or "").lower().split())
    if not key:
        return None
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE brand_cache
                SET hit_count = hit_count + 1
                WHERE company = %s
                  AND updated_at > NOW() - (%s || ' days')::interval
                RETURNING brand_data
                """,
                (key, str(max_age_days)),
            )
            row = cur.fetchone()
        conn.commit()
        return row[0] if row else None
    finally:
        conn.close()


def save_brand_cache(company: str, brand_data: dict) -> None:
    """Upsert brand_data по компании. Обновляет updated_at (сбрасывает TTL)."""
    key = " ".join((company or "").lower().split())
    if not key:
        return
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO brand_cache (company, brand_data, brand_tag, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (company) DO UPDATE
                SET brand_data = EXCLUDED.brand_data,
                    brand_tag  = EXCLUDED.brand_tag,
                    updated_at = NOW()
                """,
                (key, json.dumps(brand_data), brand_data.get("brand_tag")),
            )
        conn.commit()
    finally:
        conn.close()


def save_ats_token(ats: str, token: str, source: str | None = None) -> bool:
    """Кладёт токен в БД. True если вставлен, False если уже был (дубликат)."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ats_discovered_tokens (ats, token, source) VALUES (%s, %s, %s)
                ON CONFLICT (ats, lower(token)) DO NOTHING
                RETURNING id
                """,
                (ats, token, source),
            )
            inserted = cur.fetchone() is not None
        conn.commit()
        return inserted
    finally:
        conn.close()


def load_ats_tokens(ats: str) -> list[str]:
    """Все авто-найденные токены данного ATS из БД (порядок добавления)."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT token FROM ats_discovered_tokens WHERE ats = %s ORDER BY added_at",
                (ats,),
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def record_probed_name(name: str, ats: str, result: str) -> None:
    """Фиксирует попытку probe по имени (result: 'hit:<token>' | 'miss').
    Дедуп по (lower(name), ats) — повторно ночью не пробуем."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ats_probed_names (name, ats, result) VALUES (%s, %s, %s)
                ON CONFLICT (lower(name), ats) DO NOTHING
                """,
                (name, ats, result),
            )
        conn.commit()
    finally:
        conn.close()


def get_probed_pairs() -> set[tuple[str, str]]:
    """Множество уже опробованных (lower(name), ats) — для пропуска повторов."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT lower(name), ats FROM ats_probed_names")
            return {(row[0], row[1]) for row in cur.fetchall()}
    finally:
        conn.close()


def get_recent_companies(start: datetime, end: datetime) -> list[str]:
    """Уникальные непустые названия компаний из vacancies за период [start, end)."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT company FROM vacancies
                WHERE parsed_at >= %s AND parsed_at < %s
                  AND company IS NOT NULL AND company <> ''
                """,
                (start.isoformat(), end.isoformat()),
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def get_discovered_tokens(start: datetime, end: datetime) -> dict[str, list[str]]:
    """Токены, добавленные за период [start, end), сгруппированные по ATS."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ats, token FROM ats_discovered_tokens
                WHERE added_at >= %s AND added_at < %s
                ORDER BY ats, added_at
                """,
                (start, end),
            )
            out: dict[str, list[str]] = {}
            for ats, token in cur.fetchall():
                out.setdefault(ats, []).append(token)
            return out
    finally:
        conn.close()


def get_discovered_counts(start: datetime, end: datetime) -> dict[str, int]:
    """Сколько токенов добавлено за период [start, end) в разрезе способа.
    Возвращает {"night": N, "url": M} (url = всё, кроме ночного probe)."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT CASE WHEN source = 'night_probe' THEN 'night' ELSE 'url' END AS kind,
                       COUNT(*)
                FROM ats_discovered_tokens
                WHERE added_at >= %s AND added_at < %s
                GROUP BY kind
                """,
                (start, end),
            )
            out = {"night": 0, "url": 0}
            for kind, cnt in cur.fetchall():
                out[kind] = int(cnt)
            return out
    finally:
        conn.close()


def record_parser_runs(run_at: datetime, stats: dict[str, dict]) -> None:
    """Пишет по строке на каждый источник за один цикл шедулера.
    stats = {source: {"parsed": int, "duplicates": int, "passed": int, "rejected": int}}."""
    if not stats:
        return
    rows = [
        (run_at, source,
         s.get("parsed", 0), s.get("duplicates", 0),
         s.get("passed", 0), s.get("rejected", 0))
        for source, s in stats.items()
    ]
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO parser_runs (run_at, source, parsed, duplicates, passed, rejected) VALUES %s",
                rows,
            )
        conn.commit()
    finally:
        conn.close()


def get_parser_stats(start: datetime, end: datetime) -> dict:
    """Агрегат parser_runs за период [start, end).
    Возвращает {"by_source": {src: {...}}, "totals": {...}, "cycles": int}."""
    conn = _get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT source,
                       SUM(parsed)     AS parsed,
                       SUM(duplicates) AS duplicates,
                       SUM(passed)     AS passed,
                       SUM(rejected)   AS rejected
                FROM parser_runs
                WHERE run_at >= %s AND run_at < %s
                GROUP BY source
                ORDER BY SUM(parsed) DESC
                """,
                (start, end),
            )
            by_source = {}
            totals = {"parsed": 0, "duplicates": 0, "passed": 0, "rejected": 0}
            for row in cur.fetchall():
                src = row.pop("source")
                vals = {k: int(v or 0) for k, v in row.items()}
                by_source[src] = vals
                for k in totals:
                    totals[k] += vals[k]
            cur.execute(
                "SELECT COUNT(DISTINCT run_at) AS cycles FROM parser_runs WHERE run_at >= %s AND run_at < %s",
                (start, end),
            )
            cycles = int(cur.fetchone()["cycles"] or 0)
        return {"by_source": by_source, "totals": totals, "cycles": cycles}
    finally:
        conn.close()


def save_vacancy_score(result, prompt_version: str) -> None:
    """Сохраняет ScoringResult в vacancy_scores. Каждый вызов — новая строка."""
    conn = _get_connection()
    try:
        enrichment_json = (
            json.dumps(result.post_enrichment.model_dump()) if result.post_enrichment else None
        )
        base_args = (
            result.vacancy_id, prompt_version,
            result.tier, result.action, result.score,
            json.dumps(result.score_breakdown),
            result.visa_sponsorship, result.relocation_support, result.remote_policy,
            result.salary_min, result.salary_max, result.salary_currency,
            result.experience_level,
            json.dumps(result.verbatim_evidence),
            result.pre_filter_blocked, result.reason,
            result.model_used or None, result.latency_ms or None,
            result.archetype, result.domain_match, result.geo_bucket,
            result.english_level_required, result.ops_content,
            result.ats_score, json.dumps(result.ats_details, ensure_ascii=False),
        )
        brand_json = json.dumps(result.brand_data) if result.brand_data else None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO vacancy_scores
                        (vacancy_id, prompt_version, tier, action, score, score_breakdown,
                         visa_sponsorship, relocation_support, remote_policy,
                         salary_min, salary_max, salary_currency, experience_level,
                         verbatim_evidence, pre_filter_blocked, reason,
                         model_used, latency_ms,
                         archetype, domain_match, geo_bucket,
                         english_level_required, ops_content,
                         ats_score, ats_details,
                         post_enrichment, brand_data)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            %s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    base_args + (enrichment_json, brand_json),
                )
            conn.commit()
        except psycopg2.errors.UndefinedColumn:
            # Колонки post_enrichment/brand_data ещё не добавлены — fallback без них.
            # Другие ошибки (сериализация, FK, сеть) пробрасываем, чтобы не терять данные молча.
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO vacancy_scores
                        (vacancy_id, prompt_version, tier, action, score, score_breakdown,
                         visa_sponsorship, relocation_support, remote_policy,
                         salary_min, salary_max, salary_currency, experience_level,
                         verbatim_evidence, pre_filter_blocked, reason,
                         model_used, latency_ms,
                         archetype, domain_match, geo_bucket,
                         english_level_required, ops_content,
                         ats_score, ats_details)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            %s,%s,%s,%s,%s,%s,%s)
                    """,
                    base_args,
                )
            conn.commit()
            logger.warning("save_vacancy_score: brand_data/post_enrichment не сохранены — примените миграции 003-004")
    finally:
        conn.close()


def get_setting(key: str) -> str | None:
    """Читает значение из таблицы settings."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def set_setting(key: str, value: str) -> None:
    """Сохраняет или обновляет значение в таблице settings."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO settings (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (key, value),
            )
        conn.commit()
    finally:
        conn.close()


def vacancy_exists(hash_value: str) -> bool:
    """Проверяет, есть ли вакансия с таким хэшем в базе."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM vacancies WHERE hash = %s", (hash_value,))
            return cur.fetchone() is not None
    finally:
        conn.close()


def vacancy_exists_by_external(external_id: str, source: str) -> bool:
    """Проверяет наличие вакансии по external_id + source."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM vacancies WHERE external_id = %s AND source = %s",
                (external_id, source),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


# Заголовок и компания без регистра, пробелов и пунктуации: «Бизнес-аналитик» = «Бизнес аналитик.»,
# «(Юг России)» = «— Юг России». Так склеиваются клоны одной вакансии по разным городам.
_NORM_TITLE = "regexp_replace(lower(title), '[^[:alnum:]]', '', 'g')"
_NORM_COMPANY = "regexp_replace(lower(coalesce(company, '')), '[^[:alnum:]]', '', 'g')"


def vacancy_exists_by_title_company(title: str, company: str) -> bool:
    """Есть ли вакансия с тем же заголовком и компанией (без учёта регистра и пунктуации)."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT 1 FROM vacancies
                    WHERE {_NORM_TITLE} = regexp_replace(lower(%s), '[^[:alnum:]]', '', 'g')
                      AND {_NORM_COMPANY} = regexp_replace(lower(%s), '[^[:alnum:]]', '', 'g')
                    LIMIT 1""",
                (title, company),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def insert_vacancy(vacancy: dict) -> int | None:
    """Вставляет вакансию в БД. Возвращает id или None при дубликате."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO vacancies
                    (external_id, source, title, company,
                     salary_min, salary_max, currency,
                     location, work_format, url, description, snippet,
                     hash, status, channel, parsed_at, published_at, experience)
                VALUES
                    (%(external_id)s, %(source)s, %(title)s, %(company)s,
                     %(salary_min)s, %(salary_max)s, %(currency)s,
                     %(location)s, %(work_format)s, %(url)s, %(description)s, %(snippet)s,
                     %(hash)s, %(status)s, %(channel)s, %(parsed_at)s, %(published_at)s, %(experience)s)
                RETURNING id
                """,
                vacancy,
            )
            new_id = cur.fetchone()[0]
        conn.commit()
        logger.debug("Вакансия сохранена: id=%s, %s", new_id, vacancy.get("title"))
        return new_id
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        logger.debug("Дубликат, пропускаем: %s", vacancy.get("title"))
        return None
    finally:
        conn.close()


def get_pending_vacancies(channel: str) -> list[dict]:
    """Возвращает вакансии со статусом 'new' для указанного канала."""
    conn = _get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM vacancies WHERE status = 'new' AND channel = %s ORDER BY parsed_at",
                (channel,),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_new_vacancies() -> list[dict]:
    """Вакансии, которые пора отправить в чат: новые и возвращённые из таблицы."""
    conn = _get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM vacancies WHERE status IN ('new', 'returned') ORDER BY parsed_at",
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_vacancy_by_id(vacancy_id: int) -> dict | None:
    """Возвращает вакансию по ID."""
    conn = _get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM vacancies WHERE id = %s", (vacancy_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def mark_pending(vacancy_id: int) -> None:
    """Ставит статус 'pending' — вакансия отправлена в чат модерации."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vacancies SET status = 'pending' WHERE id = %s",
                (vacancy_id,),
            )
        conn.commit()
    finally:
        conn.close()


def mark_posted(vacancy_id: int) -> None:
    """Ставит статус 'posted' и фиксирует время публикации."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            now = datetime.now(timezone.utc).isoformat()
            cur.execute(
                "UPDATE vacancies SET status = 'posted', posted_at = %s WHERE id = %s",
                (now, vacancy_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_latest_vacancy_score(vacancy_id: int) -> dict | None:
    """Возвращает последний скор вакансии из vacancy_scores или None."""
    conn = _get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM vacancy_scores WHERE vacancy_id = %s ORDER BY scored_at DESC LIMIT 1",
                (vacancy_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def save_moderation_message_id(vacancy_id: int, message_id: int) -> None:
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vacancies SET moderation_message_id = %s WHERE id = %s",
                (message_id, vacancy_id),
            )
        conn.commit()
    finally:
        conn.close()


def update_vacancy_description(vacancy_id: int, description: str) -> None:
    """Обновляет описание вакансии."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vacancies SET description = %s WHERE id = %s",
                (description, vacancy_id),
            )
        conn.commit()
    finally:
        conn.close()


def mark_scheduled(vacancy_id: int, publish_at: datetime) -> None:
    """Планирует публикацию вакансии на указанное время."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vacancies SET status = 'scheduled', scheduled_at = %s WHERE id = %s",
                (publish_at, vacancy_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_due_scheduled() -> list[dict]:
    """Возвращает запланированные вакансии, у которых scheduled_at <= now."""
    conn = _get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM vacancies
                WHERE status = 'scheduled' AND scheduled_at <= NOW()
                ORDER BY scheduled_at
                """,
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def mark_rejected(vacancy_id: int) -> None:
    """Ставит статус 'rejected' (не прошла фильтр)."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vacancies SET status = 'rejected' WHERE id = %s",
                (vacancy_id,),
            )
        conn.commit()
    finally:
        conn.close()


def mark_skipped(vacancy_id: int) -> None:
    """Tier C: в модерацию не отправляется, но остаётся в БД для разбора и дедупа."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vacancies SET status = 'skipped' WHERE id = %s",
                (vacancy_id,),
            )
        conn.commit()
    finally:
        conn.close()


def mark_decision(vacancy_id: int, decision: str, reason: str | None = None) -> None:
    """Решение из карточки: applied (откликаюсь) или declined (не подходит, с причиной)."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE vacancies
                SET status = %s, decision = %s, decision_reason = %s, decided_at = NOW()
                WHERE id = %s
                """,
                (decision, decision, reason, vacancy_id),
            )
        conn.commit()
    finally:
        conn.close()


def mark_snoozed(vacancy_id: int, until: datetime) -> None:
    """«Позже»: карточка вернётся в чат после until."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vacancies SET status = 'snoozed', scheduled_at = %s WHERE id = %s",
                (until, vacancy_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_due_snoozed() -> list[dict]:
    """Отложенные вакансии, которым пора вернуться в чат."""
    conn = _get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM vacancies WHERE status = 'snoozed' AND scheduled_at <= NOW() ORDER BY scheduled_at",
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def mark_returned(vacancy_ids: list[int]) -> int:
    """Возврат из вкладки «Забраковано ботом»: вакансия снова пойдёт в чат.
    Трогаем только отбракованные ботом, чтобы не перезаписать твоё решение."""
    if not vacancy_ids:
        return 0
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vacancies SET status = 'returned' WHERE id = ANY(%s) AND status IN ('skipped', 'rejected', 'stale')",
                (list(vacancy_ids),),
            )
            count = cur.rowcount
        conn.commit()
        return count
    finally:
        conn.close()


def mark_stale(vacancy_id: int) -> None:
    """Вакансия старше MAX_VACANCY_AGE_DAYS: в чат не идёт, но её можно вернуть из таблицы."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE vacancies SET status = 'stale' WHERE id = %s", (vacancy_id,))
        conn.commit()
    finally:
        conn.close()

