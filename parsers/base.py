"""
Базовый класс для всех парсеров.
Каждый новый источник наследуется от BaseParser и реализует fetch().
"""

import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """Общий интерфейс парсера вакансий."""

    source_name: str = "unknown"  # переопределяется в наследнике
    channel: str = "ru"            # "ru" или "global"
    # Прогонять url вакансий через авто-харвест ATS-токенов.
    # Выключено у самих ATS-парсеров (ashby/gh/lever — url уже их токен) и
    # у парсеров с собственным ручным харвестом (designproject/userinterviews).
    harvest_ats: bool = True

    @abstractmethod
    def fetch(self) -> list[dict]:
        """Получает список сырых вакансий из источника.
        Каждая вакансия — dict с полями:
            external_id, title, company, salary_min, salary_max,
            currency, location, work_format, url, description
        """
        ...

    def make_hash(self, title: str, company: str, url: str,
                  external_id: str = "", source: str = "") -> str:
        """Генерирует хэш для дедупликации.
        Если есть external_id — используем source|external_id (стабильно).
        Иначе — title|company|url (для источников без id)."""
        if external_id and source:
            raw = f"{source}|{external_id}"
        else:
            raw = f"{title}|{company}|{url}".lower().strip()
        return hashlib.sha256(raw.encode()).hexdigest()

    def is_known(self, external_id) -> bool:
        """Вакансия уже в БД (в т.ч. отклонённая) — детальную страницу заново не тянем.

        Парсеры берут выдачу за несколько дней, а цикл идёт раз в 15 минут:
        без этой проверки каждый цикл повторно качал бы все карточки.
        Ошибка БД не должна ронять парсинг — тогда просто качаем.
        """
        if not external_id:
            return False
        try:
            import database
            return database.vacancy_exists(self.make_hash(
                "", "", "", external_id=str(external_id), source=self.source_name,
            ))
        except Exception:
            return False

    def prepare(self, raw: dict) -> dict:
        """Дополняет сырую вакансию служебными полями перед сохранением."""
        return {
            "snippet": None,
            "published_at": None,
            "experience": None,
            **raw,
            "source": self.source_name,
            "channel": self.channel,
            "hash": self.make_hash(
                raw.get("title", ""),
                raw.get("company", ""),
                raw.get("url", ""),
                external_id=raw.get("external_id", ""),
                source=self.source_name,
            ),
            "status": "new",
            "parsed_at": datetime.now(timezone.utc).isoformat(),
        }

    def run(self) -> list[dict]:
        """Полный цикл: забрать → подготовить. Возвращает список готовых dict'ов."""
        logger.info("[%s] Запуск парсера...", self.source_name)
        try:
            raw_vacancies = self.fetch()
        except Exception:
            logger.exception("[%s] Ошибка при парсинге", self.source_name)
            return []
        prepared = [self.prepare(v) for v in raw_vacancies]
        logger.info("[%s] Получено вакансий: %d", self.source_name, len(prepared))

        if self.harvest_ats:
            try:
                from tools.ats_harvest import harvest_ats_tokens
                urls = [v["url"] for v in prepared if v.get("url")]
                if urls:
                    harvest_ats_tokens(urls, source_label=self.source_name)
            except Exception:
                logger.exception("[%s] Сбой авто-харвеста ATS, продолжаем", self.source_name)

        return prepared
