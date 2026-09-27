"""
Роль-гейт на локальной модели: «эта вакансия про соискателя или нет».

Правила в rules.py ловят должность регулярками и не различают «руководитель отдела
продаж, у которого в описании есть CRM» и «партнёрскую операционку» — различие
смысловое. Этот вопрос задаём модели: она читает role-profile.md (кем соискатель
является и кем нет, человеческим языком) и описание вакансии.

Модель отдаёт только вердикт и семью ролей. Баллы и тир считает код — цифры LLM
не доверяем. Ollama недоступна или отвечает мусором — возвращаем None, и скоринг
работает ровно как раньше, по правилам.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

import requests

import config

logger = logging.getLogger(__name__)

MAX_DESCRIPTION_CHARS = 6000

_SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "role_family": {
            "type": "string",
            "enum": ["TPM", "DEL", "OPS", "PERF", "TRANS", "AFFILIATE", "PRODUCT", "none"],
        },
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "why": {"type": "string"},
    },
    "required": ["relevant", "role_family", "confidence", "why"],
}

_SYSTEM = """Ты фильтруешь вакансии для одного человека. Ниже — его профиль.

{profile}

Прочитай вакансию и реши, стоит ли ему её показывать.

Правила:
- Решай по содержанию обязанностей, не по названию должности. Названия врут.
- Смотри, за что человек отвечает по факту. Наличие слов «CRM», «процессы»,
  «отчётность», «автоматизация» само по себе ничего не значит — они есть везде.
- Раздел «Как разбирать пограничные случаи» в профиле важнее всего остального.
- Не выдумывай опыт, которого в профиле нет.
- relevant=true, если вакансию стоит показать; false, если это чужая роль.
- role_family: TPM (технический PM, интеграции, данные), DEL (delivery, program),
  OPS (операционка, product/business/partner ops), PERF (enablement, sales/support ops),
  TRANS (трансформация, PMO, стратегия), AFFILIATE (партнёрка, аффилиат, CPA),
  PRODUCT (продуктовая роль или проджект с продуктовыми обязанностями — цель перехода,
  см. раздел про продакт в профиле), none (не подходит ни подо что).
- confidence: насколько ты уверен в СВОЁМ ОТВЕТЕ, а не в том, что вакансия подходит.
  Уверенное «да» и уверенное «нет» — оба высокие, 80-100. Сомневаешься, описание
  куцее или случай пограничный — ниже 60.
- why: одно предложение по-русски, за что отвечает человек в этой вакансии.
"""

_USER = """Должность: {title}
Компания: {company}

Описание:
{description}"""


@dataclass
class RoleVerdict:
    relevant: bool
    role_family: str
    confidence: int
    why: str


@lru_cache(maxsize=1)
def load_profile() -> str | None:
    path = config.ROLE_PROFILE_PATH
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        logger.warning("ROLE PROFILE не прочитан path=%s error=%s", path, exc)
        return None


def _clean(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def classify(title: str, company: str, description: str) -> RoleVerdict | None:
    """Вердикт модели или None, если модель недоступна — тогда решают правила."""
    if not config.LLM_ROLE_ENABLED:
        return None
    profile = load_profile()
    if not profile:
        return None

    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM.format(profile=profile)},
            {"role": "user", "content": _USER.format(
                title=_clean(title) or "не указана",
                company=_clean(company) or "не указана",
                description=_clean(description)[:MAX_DESCRIPTION_CHARS] or "нет описания",
            )},
        ],
        "stream": False,
        "think": False,  # qwen3 рассуждает по умолчанию: это минуты вместо секунд
        # Держать модель в памяти между вакансиями: холодный старт 8b — это +минута
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "format": _SCHEMA,
        "options": {
            "temperature": 0,
            # Ollama по умолчанию режет контекст до 4096 и молча теряет начало промпта
            "num_ctx": config.OLLAMA_NUM_CTX,
        },
    }

    try:
        resp = requests.post(f"{config.OLLAMA_URL}/api/chat", json=payload,
                             timeout=config.OLLAMA_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json()["message"]["content"]
    except Exception as exc:
        logger.warning("LLM ROLE недоступна: %s", exc)
        return None

    try:
        import json
        data = json.loads(raw)
        return RoleVerdict(
            relevant=bool(data["relevant"]),
            role_family=str(data["role_family"]),
            confidence=max(0, min(100, int(data["confidence"]))),
            why=str(data["why"]).strip(),
        )
    except Exception as exc:
        logger.warning("LLM ROLE вернула мусор: %s · raw=%.200s", exc, raw)
        return None
