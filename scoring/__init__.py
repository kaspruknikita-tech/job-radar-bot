from __future__ import annotations

import logging
import re

import config
from filters.stopwords import stop_role

from . import ats, fit, llm_role, rules
from .career_os import load_career_index
from .models import PostEnrichment, ScoringInput, ScoringResult
from .pre_filter import pre_filter
from .tier_mapper import map_tier

logger = logging.getLogger(__name__)

# Версия логики оценки — пишется в vacancy_scores.prompt_version.
PROMPT_VERSION = "rules-ats-v4"  # v4: «своя база» — сразу C, Москва в офисе −40

# Должность, которой нет в словаре профиля, но архетип распознан правилами
# (Enablement, Learning Ops, Affiliate, Service Coordinator...). Без этого выдача
# сужается до формулировок, которые уже встречались в прошлых сканах.
ARCHETYPE_TITLE_FLOOR = 22
VISA_SPONSOR_POINTS = 12   # как релокационный пакет в гео-таблице
ENGLISH_C1_PENALTY = -15   # профиль: B2, требование C1+ — минус
OWN_BASE_PENALTY = -40     # affiliate/продажи «со своей базой партнёров» — профиль не про это; тир сразу C

_OWN_BASE_RE = re.compile(
    r"(сво\w*|собственн\w*|наработанн\w*)\s+баз\w*|с\s+базой\s+(партн|контакт|вебмастер|веб-мастер|клиент)"
    r"|own\s+(base|network|database)\s+of|existing\s+(network|base)\s+of",
    re.IGNORECASE,
)
_OWN_BASE_REQUIRED_RE = re.compile(r"ключев|обязательн|необходим|требуется|за сч[её]т|must|required", re.IGNORECASE)


def _own_base_required(text: str) -> bool:
    """«Своя база» как требование, а не «будет плюсом»: упомянута больше одного раза
    или рядом стоит «ключевое / обязательно / за счёт своей базы»."""
    matches = list(_OWN_BASE_RE.finditer(text))
    if len(matches) >= 2:
        return True
    return any(_OWN_BASE_REQUIRED_RE.search(text[max(0, m.start() - 80):m.end() + 40]) for m in matches)

# Опциональный lookup визовых спонсоров по компании (bot_app.py::main → enable_visa_lookup).
visa_lookup = None  # Callable[[str], dict | None]


def enable_visa_lookup(fn) -> None:
    """Подключает проверку визового спонсора. fn(company)->{display,source}|None."""
    global visa_lookup
    visa_lookup = fn


def _career_index():
    return load_career_index(config.CAREER_DATA_DIR)


def _lexicon():
    return fit.load_lexicon()


def _ats_points(result: ats.AtsResult) -> int:
    """ATS-процент → очки на шкале скорера."""
    if result.low_info:
        return 0
    if result.score >= 80:
        return 30
    if result.score >= 70:
        return 20
    if result.score >= 60:
        return 10
    if result.score < 50:
        return -20
    return 0


def _reason(fr: fit.FitResult, res: ats.AtsResult) -> str:
    parts = []
    if res.requirements:
        parts.append(f"ATS {res.score}%" + (" (мало данных)" if res.low_info else ""))
    if res.matched:
        parts.append("совпало: " + ", ".join(res.matched[:4]))
    if res.transferable:
        parts.append("похоже: " + ", ".join(res.transferable[:2]))
    if res.gaps:
        parts.append("пробелы: " + ", ".join(res.gaps[:3]))
    if fr.hits:
        parts.append("сигналы: " + ", ".join(fr.hits[:4]))
    if fr.negatives:
        parts.append("минусы: " + ", ".join(fr.negatives[:3]))
    if res.blocks:
        parts.append("блоки: " + ", ".join(res.blocks[:2]))
    if fr.geo_label:
        parts.append(fr.geo_label)
    return " · ".join(parts)


def _result(vacancy: dict, **fields) -> ScoringResult:
    base = dict(
        vacancy_id=vacancy["id"],
        score_breakdown={},
        visa_sponsorship="unclear",
        relocation_support="unclear",
        remote_policy="unclear",
        salary_min=vacancy.get("salary_min"),
        salary_max=vacancy.get("salary_max"),
        salary_currency=vacancy.get("currency"),
        experience_level="unclear",
        verbatim_evidence={},
        pre_filter_blocked=False,
        regex_completeness_score=1.0,
        enrichment_used=False,
        completeness_score=1.0,
        needs_enrichment=False,
        post_enrichment=None,
        reason="",
    )
    base.update(fields)
    return ScoringResult(**base)


def score_vacancy(vacancy: dict) -> ScoringResult:
    """Оценка вакансии без LLM: правила профиля + ATS по карьерным данным."""
    full_text = " ".join(filter(None, [
        vacancy.get("title", ""), vacancy.get("description", ""), vacancy.get("location", ""),
    ]))
    blocked, matched = pre_filter(full_text)
    if blocked:
        return _result(vacancy, tier="C", action="skip", score=0, pre_filter_blocked=True,
                       reason=f"Заблокировано pre-filter: «{matched}»")

    fields = rules.extract(vacancy)
    fr = fit.score(vacancy, fields["geo_bucket"], _lexicon())
    res = ats.match(vacancy, _career_index())
    verdict = llm_role.classify(vacancy.get("title") or "", vacancy.get("company") or "",
                                vacancy.get("description") or "")
    # Уверенный вердикт модели о роли; ниже порога — только справочно, решают правила
    role_call = verdict if verdict and verdict.confidence >= config.LLM_ROLE_MIN_CONFIDENCE else None

    breakdown = {
        "заголовок": fr.title_weight * 2,
        "сигналы": round(fr.bonus),
        "минус_сигналы": -round(fr.malus),
        "опыт": fr.experience_bonus,
        "гео": fr.geo_points,
        "ats": _ats_points(res),
        "роль_подтверждена": config.LLM_ROLE_BONUS if role_call and role_call.relevant else 0,
    }
    if fr.title_weight == 0 and fields["archetype"] != "none":
        breakdown["архетип_вне_словаря"] = ARCHETYPE_TITLE_FLOOR * 2
    if fields["english_level_required"] == "c1_plus":
        breakdown["английский_c1"] = ENGLISH_C1_PENALTY
    if _own_base_required(rules.plain_text(vacancy.get("description"))):
        breakdown["своя_база"] = OWN_BASE_PENALTY
    company = (vacancy.get("company") or "").strip()
    if visa_lookup is not None and company and fields["geo_bucket"] in ("other_foreign", "us_only", "unclear"):
        try:
            if visa_lookup(company) is not None:
                breakdown["визовый_спонсор"] = VISA_SPONSOR_POINTS
        except Exception as exc:
            logger.warning("VISA lookup failed company=%r error=%s", company, exc)
    breakdown = {k: int(v) for k, v in breakdown.items() if v}
    total = sum(breakdown.values())

    stop_word = fr.title_bad
    overridden = (stop_word in fit.ADJACENT_OVERRIDABLE_BAD
                  and fields["adjacent_role"] and fields["ops_content"])
    profile_stop = stop_role(vacancy.get("title") or "")
    if profile_stop and not stop_word:
        stop_word, overridden = profile_stop, False
    # Модель прочитала обязанности и сказала, что роль своя: словарное стоп-слово снимаем.
    # Обратное — «не моя роль» — обрабатывается ниже, до расчёта тира.
    if role_call and role_call.relevant and stop_word:
        overridden = True
    if role_call and not role_call.relevant:
        tier, action = "C", "skip"
        reason = f"Модель: не моя роль · {role_call.why}"
    elif stop_word and not overridden:
        tier, action = "C", "skip"
        reason = f"Стоп-слово в заголовке: «{stop_word}» · " + _reason(fr, res)
    elif "своя_база" in breakdown:
        tier, action = "C", "skip"
        reason = "Требуется своя база партнёров/клиентов · " + _reason(fr, res)
    else:
        tier, action = map_tier(total)
        reason = _reason(fr, res)

    logger.info("SCORE: vacancy_id=%s score=%d tier=%s archetype=%s geo=%s ats=%d role=%s breakdown=%s",
                vacancy["id"], total, tier, fields["archetype"], fields["geo_bucket"], res.score,
                f"{verdict.role_family}/{verdict.confidence}" if verdict else "-", breakdown)

    return _result(
        vacancy,
        tier=tier,
        action=action,
        score=total,
        score_breakdown=breakdown,
        ats_score=res.score,
        ats_details=res.as_dict(),
        archetype=fields["archetype"],
        domain_match=fields["domain_match"],
        geo_bucket=fields["geo_bucket"],
        english_level_required=fields["english_level_required"],
        ops_content=fields["ops_content"],
        visa_sponsorship=fields["visa_sponsorship"],
        relocation_support=fields["relocation_support"],
        remote_policy=fields["remote_policy"],
        experience_level=fields["experience_level"],
        llm_role_relevant=verdict.relevant if verdict else None,
        llm_role_family=verdict.role_family if verdict else "",
        llm_role_confidence=verdict.confidence if verdict else 0,
        llm_role_why=verdict.why if verdict else "",
        model_used=config.OLLAMA_MODEL if verdict else "",
        reason=reason,
    )


__all__ = ["score_vacancy", "enable_visa_lookup", "PROMPT_VERSION", "ScoringInput", "ScoringResult", "PostEnrichment"]
