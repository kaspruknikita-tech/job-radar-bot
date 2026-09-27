"""
Кодовый ATS: насколько вакансия совпадает с подтверждённым опытом из карьерной OS.

Методика — reference/matching-strategies.md, переложенная на детерминированные правила:
- требования = термины из вакансии (инструменты, практики, метрики), найденные по секциям;
- важность требования: секция (заголовок > требования > обязанности > «будет плюсом»),
  позиция в списке, язык «обязательно / желательно», повтор в нескольких секциях;
- уверенность по требованию: прямой опыт (DIRECT) > тот же класс инструмента
  (TRANSFERABLE) > смежный класс (ADJACENT) > неизвестно (WEAK) > пробел (GAP);
- 10% итога — совпадение метрик, которые важны вакансии, с метриками из блоков.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

from bs4 import BeautifulSoup

from bot.templates import _parse_sections

from .career_os import CareerIndex

# Уверенность по полосам из matching-strategies.md
CONF_DIRECT, CONF_TRANSFERABLE, CONF_ADJACENT, CONF_WEAK, CONF_GAP = 95, 80, 65, 40, 20
# Общие практики («метрики», «документация») встречаются почти везде — меньше вес.
CONCEPT_WEIGHT = 0.5
# Методика: ранжировать 5-8 ключевых требований, остальное не размывает оценку.
TOP_REQUIREMENTS = 8
BANDS = [(90, "DIRECT"), (75, "TRANSFERABLE"), (60, "ADJACENT"), (45, "WEAK"), (0, "GAP")]

# Классы задач: инструменты внутри группы взаимозаменяемы (Transferable).
TOOL_GROUPS: dict[str, list[str]] = {
    "task_tracker": ["jira", "youtrack", "asana", "trello", "clickup", "notion", "redmine", "wrike",
                     "яндекс трекер", "yandex tracker", "kaiten", "weeek", "pyrus", "ms project"],
    "bi": ["tableau", "power bi", "looker", "grafana", "superset", "datalens", "metabase", "qlik"],
    "sql": ["sql", "postgresql", "postgres", "clickhouse", "mysql", "bigquery", "greenplum", "vertica"],
    "mmp": ["appsflyer", "adjust", "branch.io", "singular", "tenjin"],
    "crm": ["crm", "amocrm", "битрикс24", "bitrix24", "salesforce", "hubspot", "retailcrm", "bloomreach", "braze", "mindbox"],
    "agile": ["scrum", "kanban", "scrumban", "agile", "скрам", "канбан"],
    "itsm": ["itil", "sla", "mttr", "mttd", "инцидент", "incident", "postmortem", "постмортем", "on-call", "service desk"],
    "whiteboard": ["miro", "figjam", "draw.io", "lucidchart"],
    "docs": ["confluence", "вики", "wiki"],
    "messenger": ["slack", "mattermost", "microsoft teams"],
    "ads": ["google ads", "facebook ads", "meta ads", "tiktok ads", "telegram ads", "яндекс директ", "yandex direct", "vk ads", "mytarget"],
    "affiliate": ["affiliate", "аффилиат", "cpa", "партнерск", "партнёрск", "арбитраж", "keitaro", "binom", "voluum", "postback", "постбек"],
    "automation": ["n8n", "zapier", "make.com", "low-code", "no-code", "python", "apps script", "автоматизац"],
    "ai": ["chatgpt", "claude", "cursor", "llm", "openai", "нейросет"],
    "data_pipeline": ["etl", "dwh", "airflow", "dbt", "data contract", "хранилищ данных"],
    "pm_method": ["wbs", "gantt", "диаграмм ганта", "pmbok", "prince2", "waterfall", "raci", "okr", "wsjf",
                  "roadmap", "роадмап", "дорожн карт", "бэклог", "backlog"],
    "api": ["api", "rest", "s2s", "webhook", "вебхук", "интеграц", "integration", "postman", "swagger"],
    "web_analytics": ["google analytics", "яндекс метрик", "yandex metrica", "amplitude", "mixpanel", "appmetrica"],
}
ADJACENT_GROUPS: dict[str, set[str]] = {
    "bi": {"sql", "web_analytics", "data_pipeline"}, "sql": {"bi", "data_pipeline"},
    "mmp": {"ads", "web_analytics", "api"}, "ads": {"mmp", "affiliate", "web_analytics"},
    "crm": {"automation", "web_analytics"}, "automation": {"api", "ai", "crm"},
    "task_tracker": {"docs", "pm_method"}, "docs": {"task_tracker"}, "itsm": {"api", "task_tracker"},
    "web_analytics": {"bi", "mmp"}, "data_pipeline": {"sql", "bi", "api"},
    "api": {"automation", "data_pipeline", "mmp"}, "affiliate": {"ads", "crm"},
}

# Практики, которые в вакансиях пишут словами, а не названиями инструментов.
CONCEPTS: dict[str, list[str]] = {
    "стейкхолдеры": ["стейкхолдер", "заинтересованн", "stakeholder"],
    "приоритизация": ["приоритиз", "prioritiz"],
    "delivery": ["delivery"],
    "релизы": ["релиз", "release"],
    "онбординг": ["онбординг", "onboarding"],
    "найм": ["найм", "hiring", "собеседован"],
    "подрядчики и вендоры": ["подрядчик", "вендор", "vendor", "outsourc", "аутсорс"],
    "бюджет и P&L": ["p&l", "бюджет", "budget", "юнит-экономик", "unit-экономик"],
    "KPI и метрики": ["kpi", "метрик"],
    "документация": ["документац", "documentation", "регламент"],
    "A/B-тесты": ["a/b", "ab-тест", "эксперимент", "experiment"],
    "кросс-функциональность": ["кросс-функцион", "cross-functional"],
    "трансформация": ["трансформац", "transformation", "change management"],
    "риски": ["риск", "risk"],
    "управление командой": ["управлени\\w* команд", "руководство команд", "team lead", "тимлид", "прямое подчинение", "direct report"],
    "партнёры": ["партнер", "партнёр", "partner"],
    "антифрод": ["фрод", "fraud"],
    "требования и ТЗ": ["техническ\\w* задани", "требовани\\w* к", "requirements", "user stor"],
}

# Требования, которые уводят вакансию от профиля: сдельные продажи, нотации системного
# аналитика, чужие индустрии. Выведено по частотам слов в вакансиях, которые LLM
# отнесла к C против S/A (769 вакансий). Засчитываются как пробел.
FOREIGN_REQUIREMENTS: dict[str, list[str]] = {
    "холодные продажи": ["холодн\\w* (звонк|продаж|клиент|баз)", "cold call", "обзвон"],
    "работа с возражениями": ["возражени"],
    "сделки и ЛПР": ["лпр", "закрыти\\w* сдел", "заключени\\w* (сделок|договор)", "ведени\\w* сделок", "воронк\\w* продаж"],
    "план продаж": ["план\\w* продаж", "выполнени\\w* плана", "sales target", "quota"],
    "сдельная оплата": ["без потолка", "процент от продаж", "% от продаж", "бонус\\w* от продаж"],
    "телефонные продажи": ["телефонн\\w* (продаж|переговор)", "звонк\\w* клиент"],
    "нотации UML": ["uml", "нотаци"],
    "промышленность": ["оборудовани", "промышленн", "производственн", "станк", "металл"],
    "строительство": ["строительн", "стройк", "смет", "autocad", "\\bbim\\b"],
    "медицина": ["стоматолог", "медицинск", "клиник", "фармац"],
    "розница": ["розничн", "торгов\\w* зал", "мерчендайз"],
    "склад и логистика": ["склад", "отгрузк", "логистик", "\\bwms\\b"],
    "бухгалтерия и 1С": ["бухгалтер", "1с", "управленческ\\w* уч[её]т", "мсфо", "налогов\\w* уч[её]т"],
    "закупки и тендеры": ["тендер", "госзакуп", "44-фз", "223-фз"],
}
# Условия оплаты обычно пишут в «Условиях», где вес нулевой — для сдельной оплаты это и есть сигнал.
FOREIGN_IN_CONDITIONS = {"сдельная оплата"}

METRICS = ["time-to-market", "ttm", "lead time", "cycle time", "sla", "mttr", "churn", "отток",
           "ltv", "retention", "удержани", "roi", "p&l", "конверси", "выручк", "revenue",
           "предсказуем", "predictab", "throughput"]

# Пробелы, которые в вакансиях пишут по-русски — дополнение к латинице из gaps/core.
GAP_ALIASES: dict[str, list[str]] = {
    "fintech": ["финтех", "fintech"], "banking": ["банковск", "banking"],
    "blockchain": ["блокчейн", "blockchain", "крипто", "crypto", "web3"],
    "kubernetes": ["kubernetes", "k8s"], "terraform": ["terraform"], "ansible": ["ansible"],
}
_GAP_STOP = {"hands-on", "on", "of", "and", "the", "admin", "business", "console", "exchange", "x", "ads"}

_MUST = re.compile(r"обязательн|must|required|ключев|необходим", re.I)
_NICE = re.compile(r"желательн|плюсом|преимуществ|nice to have|a plus|bonus", re.I)
_SECTION_WEIGHTS = [
    (re.compile(r"плюсом|преимуществ|nice|желательн|bonus|would be", re.I), 0.5),
    (re.compile(r"услови|предлагаем|offer|benefit|о компании|about us|откликнуться|почему|мы даём|бонус|перк", re.I), 0.0),
    (re.compile(r"требовани|ожидаем|важно|кого ищем|requirement|qualif|must|что нужно|нужен|нам нужн|ты подходишь|вы подходите", re.I), 2.0),
    (re.compile(r"обязанност|задач|предстоит|responsib|what you|чем занима|ваша роль|you will", re.I), 1.5),
]


_REGEX_META = re.compile(r"[\\()\[\]|]")


def _pattern(term: str) -> re.Pattern:
    """Термин словаря → регулярка.
    Варианты со служебными символами (группы, \\w*, \\b, классы) — уже регулярки, берём как есть:
    иначе re.escape превращает «холодн\\w* (звонк|продаж)» в поиск буквальных скобок.
    Остальное экранируем: латиница целым словом, русская основа — со свободным суффиксом."""
    if _REGEX_META.search(term):
        return re.compile(r"(?<![\w])" + term, re.I)
    # re.escape экранирует и пробел («\ »), поэтому меняем именно экранированный вариант
    body = re.escape(term.lower()).replace(r"\-", r"[\s\-]?").replace(r"\ ", r"[\s\-]+")
    if re.search(r"[а-яё]", term, re.I):
        return re.compile(r"(?<![\w])" + body + r"\w*", re.I)
    return re.compile(r"(?<![\w])" + body + r"(?![\w])", re.I)


@dataclass
class Term:
    name: str
    kind: str                      # tool | concept | tag | gap
    group: str | None
    patterns: list[re.Pattern]


@dataclass
class AtsResult:
    score: int = 0
    band: str = "GAP"
    matched: list[str] = field(default_factory=list)
    transferable: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    requirements: int = 0
    low_info: bool = True

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("score", "band", "matched", "transferable", "gaps",
                                               "missing", "blocks", "requirements", "low_info")}


def _latin_chunks(text: str) -> list[str]:
    """Названия из темы пробела: «Adjust (MMP)» → Adjust, MMP; «Laravel / PHP / Vue» → каждое.
    Фразу из нескольких слов не режем («GitHub Actions»), аббревиатуры вида CI/CD не делим.
    Берём только то, что похоже на имя собственное: есть заглавная буква."""
    chunks = re.findall(r"[A-Za-z][A-Za-z0-9+.&\-]*(?:/[A-Z]{1,4}\b)?(?:\s+[A-Z][A-Za-z0-9+.&\-]*)*", text)
    out = []
    for chunk in chunks:
        parts = [chunk] if re.fullmatch(r"[A-Z]{1,4}/[A-Z]{1,4}", chunk) else re.split(r"\s*/\s*", chunk)
        for part in parts:
            p = part.strip(" .-")
            if len(p) >= 2 and re.search(r"[A-Z]", p) and p.lower() not in _GAP_STOP:
                out.append(p)
    return out


@dataclass
class _Vocabulary:
    terms: list[Term]
    evidence: str                  # всё, что подтверждает опыт, одной строкой
    partial_evidence: str          # «частично» из сигналов рынка — опыт неполный
    block_evidence: dict[str, str]
    gap_names: set[str]
    metric_patterns: list[re.Pattern]


@lru_cache(maxsize=4)
def _vocabulary(index: CareerIndex) -> _Vocabulary:
    block_evidence = {b.id: (" ".join(b.tags) + " " + b.text).lower() for b in index.blocks}
    experienced_gaps = " ".join(g.topic for g in index.gaps if g.status != "no-exp").lower()
    market_yes = " ".join(t for t, s in index.market_signals if s == "да").lower()
    evidence = " ".join([*block_evidence.values(), experienced_gaps, market_yes,
                         " ".join(index.skill_library).lower()])
    partial_evidence = " ".join(t for t, s in index.market_signals if s == "частично").lower()

    terms: list[Term] = []
    seen: set[str] = set()

    def add(name, kind, group, variants):
        key = name.lower()
        if key in seen:
            return
        seen.add(key)
        terms.append(Term(name, kind, group, [_pattern(v) for v in variants]))

    for group, tools in TOOL_GROUPS.items():
        for tool in tools:
            add(tool, "tool", group, [tool])
    for name, variants in CONCEPTS.items():
        add(name, "concept", None, variants)
    for name, variants in FOREIGN_REQUIREMENTS.items():
        add(name, "foreign", None, variants)
    # Теги-инструменты и аббревиатуры из блоков (ClickHouse, WSJF, RACI, DoR/DoD...)
    for tag in index.tags():
        for part in re.split(r"/", tag):
            part = part.strip()
            if len(part) >= 2 and re.search(r"[A-Z0-9&]", part):
                add(part, "tag", None, [part])

    gap_names: set[str] = set()
    gap_sources = [g.topic for g in index.gaps if g.status == "no-exp"]
    gap_sources += [line for line in index.honest_gaps if line.lower().startswith("нет")]
    gap_sources += [topic for topic, status in index.market_signals if status == "нет"]
    for source in gap_sources:
        for chunk in _latin_chunks(source):
            key = chunk.lower()
            variants = GAP_ALIASES.get(key, [chunk])
            if any(_pattern(v).search(evidence) for v in variants):
                continue  # опыт в блоках есть — это не пробел
            gap_names.add(key)
            add(chunk, "gap", None, variants)
    for key, variants in GAP_ALIASES.items():
        gap_names.add(key)
        add(key, "gap", None, variants)

    return _Vocabulary(terms, evidence, partial_evidence, block_evidence, gap_names,
                       [_pattern(m) for m in METRICS])


def _has_evidence(term: Term, text: str) -> bool:
    return any(p.search(text) for p in term.patterns)


def _confidence(term: Term, vocab: _Vocabulary, by_name: dict[str, Term]) -> tuple[int, str]:
    if term.kind == "foreign":
        return CONF_GAP, "gap"
    if term.kind != "gap" and _has_evidence(term, vocab.evidence):
        return CONF_DIRECT, "direct"
    if term.kind != "gap" and _has_evidence(term, vocab.partial_evidence):
        return CONF_TRANSFERABLE, "transferable"  # сигнал рынка «опыт есть частично»
    if term.kind == "gap" or term.name.lower() in vocab.gap_names:
        return CONF_GAP, "gap"
    if term.group:
        members = [by_name[t] for t in TOOL_GROUPS[term.group] if t in by_name]
        if any(_has_evidence(m, vocab.evidence) for m in members):
            return CONF_TRANSFERABLE, "transferable"
        for adj in ADJACENT_GROUPS.get(term.group, ()):
            adj_members = [by_name[t] for t in TOOL_GROUPS[adj] if t in by_name]
            if any(_has_evidence(m, vocab.evidence) for m in adj_members):
                return CONF_ADJACENT, "adjacent"
    return CONF_WEAK, "weak"


def _section_weight(heading: str) -> float:
    for rx, weight in _SECTION_WEIGHTS:
        if rx.search(heading):
            return weight
    return 1.0


def _chunks(vacancy: dict) -> list[tuple[str, float, list[str]]]:
    title = vacancy.get("title") or ""
    chunks = [("title", 3.0, [title])]
    description = vacancy.get("description") or ""
    sections = _parse_sections(description) or {}
    named = {k: v for k, v in sections.items() if k != "__intro__" and v}
    intro = sections.get("__intro__") or ""
    if not named:
        intro = BeautifulSoup(description, "html.parser").get_text("\n", strip=True)
    if intro:
        chunks.append(("intro", 1.0, [l for l in str(intro).split("\n") if l.strip()]))
    for heading, bullets in named.items():
        items = bullets if isinstance(bullets, list) else [str(bullets)]
        chunks.append((heading, _section_weight(heading), [str(b) for b in items]))
    return chunks


def match(vacancy: dict, index: CareerIndex) -> AtsResult:
    if not index.loaded:
        return AtsResult()
    vocab = _vocabulary(index)
    by_name = {t.name.lower(): t for t in vocab.terms}

    weights: dict[str, float] = {}
    sections_seen: dict[str, set[str]] = {}
    for section, section_w, bullets in _chunks(vacancy):
        head_count = math.ceil(len(bullets) / 3) if bullets else 0
        for i, bullet in enumerate(bullets):
            factor = section_w * (1.2 if i < head_count and len(bullets) > 2 else 1.0)
            if section_w == 0 and not any(_has_evidence(by_name[n.lower()], bullet) for n in FOREIGN_IN_CONDITIONS):
                continue
            if _MUST.search(bullet):
                factor *= 1.2
            elif _NICE.search(bullet):
                factor *= 0.6
            for term in vocab.terms:
                if section_w == 0 and term.name not in FOREIGN_IN_CONDITIONS:
                    continue
                if _has_evidence(term, bullet):
                    base = factor if section_w else 1.0
                    term_factor = base * (CONCEPT_WEIGHT if term.kind == "concept" else 1.0)
                    weights[term.name] = max(weights.get(term.name, 0.0), term_factor)
                    sections_seen.setdefault(term.name, set()).add(section)
    for name, secs in sections_seen.items():
        if len(secs) >= 2:
            weights[name] *= 1.3

    if not weights:
        return AtsResult()

    scored = []
    for name, w in weights.items():
        term = by_name[name.lower()]
        conf, kind = _confidence(term, vocab, by_name)
        scored.append((w, conf, kind, name))
    top = sorted(scored, key=lambda s: -s[0])[:TOP_REQUIREMENTS]
    total_w = sum(w for w, *_ in top)
    core = sum(w * conf for w, conf, *_ in top) / total_w

    jd_text = " ".join(" ".join(b) for _, _, b in _chunks(vacancy))
    jd_metrics = [p for p in vocab.metric_patterns if p.search(jd_text)]
    impact = (100 * sum(bool(p.search(vocab.evidence)) for p in jd_metrics) / len(jd_metrics)) if jd_metrics else core
    score = round(core * 0.9 + impact * 0.1)

    by_weight = sorted(scored, key=lambda s: -s[0])
    direct_names = [n for _, _, k, n in by_weight if k == "direct"]
    block_hits: dict[str, float] = {}
    for w, _, kind, name in by_weight:
        if kind != "direct":
            continue
        term = by_name[name.lower()]
        for block_id, text in vocab.block_evidence.items():
            if _has_evidence(term, text):
                block_hits[block_id] = block_hits.get(block_id, 0.0) + w

    return AtsResult(
        score=score,
        band=next(label for threshold, label in BANDS if score >= threshold),
        matched=direct_names[:6],
        transferable=[n for _, _, k, n in by_weight if k in ("transferable", "adjacent")][:4],
        gaps=[n for _, _, k, n in by_weight if k == "gap"][:4],
        missing=[n for _, _, k, n in by_weight if k == "weak"][:5],
        blocks=[b for b, _ in sorted(block_hits.items(), key=lambda x: -x[1])[:3]],
        requirements=len(scored),
        # Мало данных: меньше трёх требований или ни одного конкретного
        # (инструмент, тег, пробел, чужая индустрия) — одни общие слова.
        low_info=len(scored) < 3 or not any(by_name[n.lower()].kind != "concept" for _, _, _, n in top),
    )
