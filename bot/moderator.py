"""
Отправка вакансий в чат модерации и публикация одобренных в каналы.
Использует Telegram Bot API напрямую через requests (без asyncio).
"""

import re
import time
import logging
from datetime import datetime, timedelta, timezone

import config
import database
from bot.templates import format_ru, format_global
from bot.tg_api import call as tg_call
from exporters.sheets import export_rejected_to_sheets, export_to_sheets
from scoring import score_vacancy, PROMPT_VERSION
from scoring.models import PostEnrichment, ScoringResult

logger = logging.getLogger(__name__)

_SEND_DELAY = 3.5
_TG_TEXT_LIMIT = 4096
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
# Открывающие и закрывающие теги — оба паттерна case-insensitive,
# чтобы <B>...</B> и <b>...</b> считались согласованно.
_TAG_PAIRS = (
    (re.compile(r"<b\b[^>]*>", re.IGNORECASE), re.compile(r"</b>", re.IGNORECASE), "</b>"),
    (re.compile(r"<i\b[^>]*>", re.IGNORECASE), re.compile(r"</i>", re.IGNORECASE), "</i>"),
    (re.compile(r"<a\b[^>]*>", re.IGNORECASE), re.compile(r"</a>", re.IGNORECASE), "</a>"),
)
_TIER_ICONS = {"S": "⭐", "A": "🔵", "B": "🟡", "C": "🔴"}

# Источники, генерирующие/переписывающие описание — текст вакансии может быть
# выдуман (см. кейс Hinge: «Remote Worldwide», которого в оригинале нет).
_UNTRUSTED_SOURCES = {"bebee", "designproject", "theirstack"}

# Компактные сигналы для карточки: 🌍 удалёнка · 🛂 виза · ✈️ релокация.
_REMOTE_DISPLAY = {
    "global":  ("✅", "worldwide"),
    "eu":      ("✅", "EU"),
    "us_only": ("⚠️", "US"),
    "hybrid":  ("⚠️", "гибрид"),
    "on_site": ("❌", "офис"),
    "unclear": ("❓", ""),
}
_YESNO_DISPLAY = {"yes": "✅", "implied": "🟡", "no": "❌", "unclear": "❓"}
_QUOTE_CAP = 50

_ARCHETYPE_DISPLAY = {
    "TPM": "TPM",
    "DEL": "Delivery",
    "OPS": "Operations",
    "PERF": "Enablement",
    "TRANS": "Transformation",
    "none": "не наш профиль",
}
_GEO_DISPLAY = {
    "remote_ru": "удалёнка РФ",
    "spb": "СПб",
    "msk": "Москва",
    "reloc_georgia_serbia_cyprus": "релокация GE/RS/CY",
    "other_foreign": "зарубеж",
    "us_only": "US only",
    "unclear": "гео не указано",
}
_ENGLISH_DISPLAY = {"c1_plus": "англ. C1+", "b2_ok": "англ. B2 хватит", "unclear": ""}


def _freshness(vacancy: dict) -> str:
    """Сколько прошло с публикации. Пусто, если источник даты не дал."""
    from datetime import datetime, timezone

    raw = vacancy.get("published_at")
    if not raw:
        return ""
    try:
        dt = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
    except (ValueError, TypeError):
        return ""

    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{int(delta.total_seconds() // 60)} мин назад"
    if hours < 24:
        return f"{int(hours)} ч назад"
    return f"{int(hours // 24)} дн назад"


def _headline(vacancy: dict, result: ScoringResult | None) -> str:
    """Шапка карточки модерации: всё для решения за 5 секунд + ссылка на отклик.

    Порядок: тир, архетип, гео, вилка, компания, свежесть — затем прямая ссылка.
    """
    from bot.templates import _format_salary, _safe_url

    parts = []
    if result is not None:
        icon = _TIER_ICONS.get(result.tier, "")
        tier = f"{icon} {result.tier}"
        if result.score > 0:
            tier += f" ({result.score})"
        parts.append(tier)
        parts.append(_ARCHETYPE_DISPLAY.get(result.archetype, result.archetype))
        parts.append(_GEO_DISPLAY.get(result.geo_bucket, result.geo_bucket))

    salary = _format_salary(vacancy)
    parts.append(salary if salary else "вилки нет")

    company = (vacancy.get("company") or "").strip()
    if company:
        parts.append(company)

    fresh = _freshness(vacancy)
    if fresh:
        parts.append(fresh)

    head = " · ".join(p for p in parts if p)
    link = f'🔗 <a href="{_safe_url(vacancy.get("url", ""))}">Откликнуться</a>'
    return f"<b>{head}</b>\n{link}\n\n"


def _signals_block(result: ScoringResult) -> list[str]:
    """Сигналы доступности: формат работы, виза, релокация, английский, домен."""
    ev = result.verbatim_evidence or {}

    r_emoji, r_word = _REMOTE_DISPLAY.get(result.remote_policy, ("❓", ""))
    remote = f"🌍 {r_emoji}" + (f" {r_word}" if r_word else "")
    visa = f"🛂 {_YESNO_DISPLAY.get(result.visa_sponsorship, '❓')}"
    reloc = f"✈️ {_YESNO_DISPLAY.get(result.relocation_support, '❓')}"
    lines = [f"{remote} · {visa} · {reloc}"]

    extra = []
    english = _ENGLISH_DISPLAY.get(result.english_level_required, "")
    if english:
        extra.append(("⚠️ " if result.english_level_required == "c1_plus" else "🗣 ") + english)
    if result.domain_match:
        extra.append("🎯 профильный домен")
    if result.ops_content:
        extra.append("⚙️ операционное содержание")
    if extra:
        lines.append(" · ".join(extra))

    for emoji, field in (("🌍", "remote_policy"), ("🛂", "visa_sponsorship"),
                         ("✈️", "relocation_support"), ("🗣", "english_level_required")):
        q = ev.get(field)
        if q:
            if len(q) > _QUOTE_CAP:
                q = q[:_QUOTE_CAP].rstrip() + "…"
            lines.append(f"└ {emoji} «{q}»")
    return lines


def _get_enrichment(result: ScoringResult | None) -> dict | None:
    if result and result.post_enrichment:
        return result.post_enrichment.model_dump()
    return None


def _format(vacancy: dict, result: ScoringResult | None = None) -> str:
    enrichment = _get_enrichment(result)
    if vacancy.get("channel") == "ru":
        return format_ru(vacancy, enrichment=enrichment)
    return format_global(vacancy, enrichment=enrichment)


def _tg_len(s: str) -> int:
    """Длина в UTF-16 code units — так Telegram считает лимит 4096."""
    return len(s.encode("utf-16-le")) // 2


def _tg_truncate(s: str, max_units: int) -> str:
    """Усекает строку до max_units UTF-16 code units."""
    units = 0
    for i, c in enumerate(s):
        cost = 2 if ord(c) > 0xFFFF else 1
        if units + cost > max_units:
            return s[:i]
        units += cost
    return s


def _balance_html_tags(s: str) -> str:
    for open_re, close_re, close_tag in _TAG_PAIRS:
        opens = len(open_re.findall(s))
        closes = len(close_re.findall(s))
        if opens > closes:
            s += close_tag * (opens - closes)
    return s


def _truncate_for_telegram(text: str, footer: str, limit: int = _TG_TEXT_LIMIT) -> str:
    """Урезает text+footer под лимит Telegram (UTF-16 units). Сохраняет ссылку 'Откликнуться' и футер."""
    if _tg_len(text) + _tg_len(footer) <= limit:
        return text + footer

    text = text.rstrip("\n")
    lines = text.split("\n")
    if lines and "<a href=" in lines[-1]:
        link_line = lines[-1]
        body = "\n".join(lines[:-1])
        tail = "\n\n…\n\n" + link_line + footer
    else:
        body = text
        tail = "\n\n…" + footer

    available = limit - _tg_len(tail)
    if available < 200:
        plain = _TAG_STRIP_RE.sub("", text + footer)
        return _tg_truncate(plain, limit - 1) + "…"

    truncated = _tg_truncate(body, available)
    cut = truncated.rfind("\n\n")
    if cut > 200:
        truncated = truncated[:cut]

    truncated = _balance_html_tags(truncated)
    return truncated + tail


def _scoring_footer(result: ScoringResult, vacancy: dict) -> str:
    icon = _TIER_ICONS[result.tier]

    if result.pre_filter_blocked:
        return f"\n\n{icon} Tier {result.tier} · {result.reason}"

    parts = [f"{icon} Tier {result.tier}"]
    # Скор без потолка (правила + ATS), пороги S ≥ 130 / A ≥ 95 / B ≥ 65 — см. tier_mapper.
    parts[0] += f" · скор {result.score}"
    if result.ats_score:
        parts[0] += f" · ATS {result.ats_score}%"

    lines = [" | ".join(parts)]
    if result.reason:
        lines.append(f"💬 {result.reason}")

    if vacancy.get("source") in _UNTRUSTED_SOURCES:
        lines.append("⚠️ источник непроверен — сверь оригинал")

    lines.append("")
    lines.extend(_signals_block(result))

    # Компания в курируемом списке визовых спонсоров — подсветка для зарубежных.
    if result.geo_bucket in ("other_foreign", "us_only", "unclear"):
        try:
            sponsor = database.is_visa_sponsor(vacancy.get("company"))
        except Exception:
            sponsor = None
        if sponsor and result.visa_sponsorship != "no":
            lines.append(f"🛂✅ Компания-визовый спонсор (исторически, {sponsor['source']})")

    if result.needs_enrichment:
        lines.append("⚠️ Неполные данные, проверь вручную")

    bd = result.brand_data
    if bd and bd.get("brand_tag") and not bd.get("error"):
        lines.append("")
        tag = bd.get("brand_tag", "")
        meta = " · ".join(filter(None, [bd.get("industry", ""), bd.get("scale", "")]))
        lines.append(f"🏷 {tag}" + (f" · {meta}" if meta else ""))
        if bd.get("summary"):
            lines.append(bd["summary"])

    return "\n\n" + "\n".join(lines)


LATER_SLOTS = [("⏳ Через 3 ч", 180), ("⏳ Завтра", 1440)]
DECLINE_REASONS = {
    "profile": "не мой профиль",
    "geo": "гео",
    "salary": "зарплата",
    "company": "компания",
    "level": "уровень",
    "other": "другое",
}


def _keyboard(vacancy_id: int, channel: str = "") -> dict:
    """Кнопки решения по вакансии. channel не используется — оставлен для совместимости вызовов."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Откликаюсь", "callback_data": f"apply:{vacancy_id}"},
                {"text": "❌ Не подходит", "callback_data": f"decline:{vacancy_id}"},
            ],
            [{"text": label, "callback_data": f"later:{vacancy_id}:{mins}"} for label, mins in LATER_SLOTS],
        ]
    }


def _decline_keyboard(vacancy_id: int) -> dict:
    """Причина отказа в одно нажатие — это же разметка для калибровки скоринга."""
    items = list(DECLINE_REASONS.items())
    rows = [
        [{"text": label, "callback_data": f"reason:{vacancy_id}:{code}"} for code, label in items[i:i + 3]]
        for i in range(0, len(items), 3)
    ]
    rows.append([{"text": "↩️ Назад", "callback_data": f"back:{vacancy_id}"}])
    return {"inline_keyboard": rows}


def _row_to_scoring_result(row: dict, vacancy_id: int) -> ScoringResult:
    """Восстанавливает ScoringResult из строки vacancy_scores."""
    enrich_data = row.get("post_enrichment")
    post_enrichment = PostEnrichment(**enrich_data) if enrich_data else None
    return ScoringResult(
        vacancy_id=vacancy_id,
        tier=row["tier"],
        action=row["action"],
        score=row["score"],
        score_breakdown=row.get("score_breakdown") or {},
        archetype=row.get("archetype") or "none",
        domain_match=bool(row.get("domain_match")),
        geo_bucket=row.get("geo_bucket") or "unclear",
        english_level_required=row.get("english_level_required") or "unclear",
        ops_content=bool(row.get("ops_content")),
        ats_score=row.get("ats_score") or 0,
        ats_details=row.get("ats_details") or {},
        visa_sponsorship=row["visa_sponsorship"],
        relocation_support=row["relocation_support"],
        remote_policy=row.get("remote_policy", "unclear"),
        salary_min=row.get("salary_min"),
        salary_max=row.get("salary_max"),
        salary_currency=row.get("salary_currency"),
        experience_level=row.get("experience_level", "unclear"),
        verbatim_evidence=row.get("verbatim_evidence") or {},
        pre_filter_blocked=bool(row.get("pre_filter_blocked", False)),
        regex_completeness_score=0.0,
        enrichment_used=post_enrichment is not None,
        completeness_score=1.0,
        needs_enrichment=False,
        post_enrichment=post_enrichment,
        reason=row.get("reason") or "",
        model_used=row.get("model_used") or "",
        latency_ms=row.get("latency_ms") or 0,
        brand_data=row.get("brand_data"),
    )


def _get_or_score(vacancy: dict) -> ScoringResult | None:
    """Берёт скор из БД. Если нет — считает заново."""
    try:
        row = database.get_latest_vacancy_score(vacancy["id"])
        # Оценку другой версии (например, прежний LLM-скоринг) не переиспользуем — считаем заново.
        if row and row.get("prompt_version") == PROMPT_VERSION:
            return _row_to_scoring_result(row, vacancy["id"])
        result = score_vacancy(vacancy)
    except Exception:
        logger.warning("Скоринг не удался для вакансии %s", vacancy.get("id"), exc_info=True)
        return None
    try:
        database.save_vacancy_score(result, PROMPT_VERSION)
    except Exception:
        logger.warning("Не удалось сохранить скор вакансии %s", vacancy.get("id"), exc_info=True)
    return result


def send_to_moderation(vacancy: dict, scoring_result: ScoringResult | None = None) -> bool:
    """Отправляет одну вакансию в чат модерации с кнопками. True = успешно."""
    try:
        if scoring_result is None:
            scoring_result = _get_or_score(vacancy)

        text = _headline(vacancy, scoring_result) + _format(vacancy, scoring_result)
        footer = _scoring_footer(scoring_result, vacancy) if scoring_result is not None else ""
        text = _truncate_for_telegram(text, footer)

        mod_chat = _get_moderation_chat(vacancy.get("channel", ""))
        resp = tg_call(
            "sendMessage",
            chat_id=mod_chat,
            text=text,
            parse_mode="HTML",
            reply_markup=_keyboard(vacancy["id"], vacancy["channel"]),
            disable_web_page_preview=True,
        )
        database.mark_pending(vacancy["id"])
        msg_id = (resp.get("result") or {}).get("message_id")
        if msg_id:
            database.save_moderation_message_id(vacancy["id"], msg_id)
        return True
    except Exception:
        logger.exception("Не удалось отправить вакансию %s на модерацию", vacancy.get("id"))
        return False


def _get_moderation_chat(channel: str) -> str:
    if channel == "ru":
        return config.TELEGRAM_MODERATION_CHAT_RU
    return config.TELEGRAM_MODERATION_CHAT_GLOBAL


_CHANNEL_MAP = {
    "ru":     lambda: config.TELEGRAM_CHANNEL_RU,
    "global": lambda: config.TELEGRAM_CHANNEL_GLOBAL,
}


def publish_due_scheduled() -> int:
    """Публикует все вакансии у которых scheduled_at уже наступил."""
    due = database.get_due_scheduled()
    if not due:
        return 0

    published = 0
    for v in due:
        channel_id = _CHANNEL_MAP.get(v.get("channel", ""), lambda: config.TELEGRAM_CHANNEL_GLOBAL)()
        if not channel_id:
            logger.warning("Нет channel_id для вакансии id=%s", v["id"])
            continue
        try:
            scoring_result = _get_or_score(v)
            text = _format(v, scoring_result)
            tg_call(
                "sendMessage",
                chat_id=channel_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            database.mark_posted(v["id"])
            published += 1
            logger.info("Опубликована запланированная вакансия id=%s", v["id"])
        except Exception:
            logger.exception(
                "Ошибка публикации запланированной вакансии id=%s channel=%s chat_id=%r",
                v["id"], v.get("channel"), channel_id,
            )
        time.sleep(_SEND_DELAY)

    return published


def _published_at(vacancy: dict) -> datetime | None:
    """Дата публикации, а если источник её не дал — дата, когда вакансию нашли."""
    for key in ("published_at", "parsed_at"):
        raw = vacancy.get(key)
        if not raw:
            continue
        if isinstance(raw, datetime):
            dt = raw
        else:
            text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(raw).replace("Z", "+00:00"))
            try:
                dt = datetime.fromisoformat(text)
            except ValueError:
                continue
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


_TIER_RANK = {"S": 1, "A": 2, "B": 3, "C": 4}
# Бонус к скору в очереди за свежесть публикации: (не старше часов, бонус)
FRESHNESS_BONUS = [(6, 40), (24, 25), (72, 10)]


def _freshness_bonus(vacancy: dict) -> int:
    published = _published_at(vacancy)
    if published is None:
        return 0
    hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600
    return next((bonus for limit, bonus in FRESHNESS_BONUS if hours <= limit), 0)


def _fair_order(scored: list) -> list:
    """Порядок отправки: возвращённые из таблицы первыми, дальше тир S → A → B → C,
    а внутри тира — по кругу из разных источников, лучшая вакансия каждого первой.
    Иначе hh, у которого формат и город приходят полями, занимает весь лимит карточек.
    «Лучшая» = скор + бонус за свежесть: на свежие вакансии откликаются первыми.
    Бонус влияет только на очередь — тир и сохранённый скор не меняются."""
    from collections import defaultdict, deque

    def score(pair):
        base = pair[1].score if pair[1] is not None else -1
        return base + _freshness_bonus(pair[0])

    groups: dict[int, list] = defaultdict(list)
    for pair in scored:
        vacancy, result = pair
        if vacancy.get("status") == "returned":
            rank = 0
        else:
            rank = _TIER_RANK.get(result.tier if result is not None else "B", 4)
        groups[rank].append(pair)

    ordered = []
    for rank in sorted(groups):
        queues: dict[str, deque] = defaultdict(deque)
        for pair in sorted(groups[rank], key=score, reverse=True):
            queues[pair[0].get("source", "")].append(pair)
        sources = sorted(queues, key=lambda s: score(queues[s][0]), reverse=True)
        while any(queues.values()):
            for source in sources:
                if queues[source]:
                    ordered.append(queues[source].popleft())
    return ordered


def send_new_vacancies_to_moderation(limit: int | None = None) -> int:
    """limit — сколько карточек можно отправить за этот вызов (по умолчанию MODERATION_MAX_PER_CYCLE)."""
    if limit is not None and limit <= 0:
        return 0
    """Берёт все 'new' вакансии из БД и отправляет в чат модерации."""
    if not config.TELEGRAM_BOT_TOKEN or not (config.TELEGRAM_MODERATION_CHAT_RU or config.TELEGRAM_MODERATION_CHAT_GLOBAL):
        logger.warning("Telegram не настроен, пропускаем отправку на модерацию")
        return 0

    vacancies = database.get_new_vacancies()
    if not vacancies:
        return 0

    # Только свежее: старше MAX_VACANCY_AGE_DAYS — в «Забраковано ботом», оттуда можно вернуть.
    # Возвращённые тобой идут в чат в любом случае.
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.MAX_VACANCY_AGE_DAYS)
    fresh, stale_rows = [], []
    for v in vacancies:
        published = _published_at(v)
        if v.get("status") != "returned" and published is not None and published < cutoff:
            database.mark_stale(v["id"])
            stale_rows.append({**v, "_reject_reason": f"Старше {config.MAX_VACANCY_AGE_DAYS} дней "
                                                      f"(опубликована {published:%d.%m.%Y})"})
        else:
            fresh.append(v)
    vacancies = fresh
    if stale_rows:
        logger.info("Старше %d дней, в чат не идут: %d", config.MAX_VACANCY_AGE_DAYS, len(stale_rows))
        try:
            export_rejected_to_sheets(stale_rows)
        except Exception:
            logger.exception("Экспорт устаревших в таблицу упал, продолжаем")
    if not vacancies:
        return 0

    # Скорим заранее и сортируем по убыванию скора: чем выше скор,
    # тем раньше вакансия появляется в выдаче модерации.
    scored = [(v, _get_or_score(v)) for v in vacancies]
    scored = _fair_order(scored)

    sent = 0
    deferred = 0
    sent_rows, skipped_rows = [], []
    for v, scoring_result in scored:
        # Tier C (action=skip) в чат не шлём: при двух десятках источников он
        # топит годные вакансии. Без скора отправляем — прятать непроверенное нельзя.
        # Возвращённые из таблицы идут в чат в любом случае: это твоё решение.
        returned = v.get("status") == "returned"
        if scoring_result is not None and scoring_result.tier == "C" and not returned:
            database.mark_skipped(v["id"])
            skipped_rows.append({**v, "_scoring": scoring_result})
            continue
        # Список уже отсортирован по скору: лучшие уходят сейчас, остальные — в следующих циклах.
        if sent >= (config.MODERATION_MAX_PER_CYCLE if limit is None else limit):
            deferred += 1
            continue
        if send_to_moderation(v, scoring_result):
            sent += 1
            sent_rows.append({**v, "_scoring": scoring_result})
        time.sleep(_SEND_DELAY)
    if skipped_rows:
        logger.info("Tier C пропущено без модерации: %d", len(skipped_rows))
    if deferred:
        logger.info("Отложено до следующего цикла (лимит %d карточек): %d", config.MODERATION_MAX_PER_CYCLE, deferred)
    try:
        export_to_sheets(sent_rows)
        export_rejected_to_sheets(skipped_rows)
    except Exception:
        logger.exception("Экспорт в таблицу упал, продолжаем")

    logger.info("Отправлено на модерацию: %d вакансий", sent)
    return sent


def resend_due_snoozed() -> int:
    """«Позже»: возвращает в чат вакансии, у которых наступило время."""
    sent = 0
    for v in database.get_due_snoozed():
        if send_to_moderation(v):
            sent += 1
        time.sleep(_SEND_DELAY)
    return sent
