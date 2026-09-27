from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator


class ScoringInput(BaseModel):
    vacancy_id: int
    title: str
    company: str
    description: str
    location: str | None = None
    work_format: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str | None = None
    is_ru: bool = False


class PostEnrichment(BaseModel):
    # Все поля с дефолтами — LLM (особенно мелкие модели) часть полей опускает.
    # Лучше частичное обогащение, чем ValidationError и потеря всего скоринга.
    summary: str = ""
    key_tasks: list[str] = []
    key_requirements: list[str] = []
    key_benefits: list[str] = []
    formatted_salary: str | None = None
    seniority_label: str = "Not specified"


class ScoringResult(BaseModel):
    vacancy_id: int
    tier: Literal["S", "A", "B", "C"]
    action: Literal["curated_plus", "curated", "main", "skip"]
    score: int  # итоговый скор правил, может быть отрицательным; пороги — в tier_mapper
    score_breakdown: dict[str, int]
    ats_score: int = 0  # процент совпадения с карьерной OS
    ats_details: dict = {}  # совпало / похоже / пробелы / блоки опыта
    archetype: Literal["TPM", "DEL", "OPS", "PERF", "TRANS", "none"] = "none"
    domain_match: bool = False
    geo_bucket: Literal[
        "remote_ru", "spb", "msk", "reloc_georgia_serbia_cyprus",
        "other_foreign", "us_only", "unclear",
    ] = "unclear"
    english_level_required: Literal["b2_ok", "c1_plus", "unclear"] = "unclear"
    ops_content: bool = False
    visa_sponsorship: Literal["yes", "implied", "no", "unclear"]
    relocation_support: Literal["yes", "implied", "no", "unclear"]
    remote_policy: Literal["global", "eu", "us_only", "hybrid", "on_site", "unclear"]
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    experience_level: Literal["junior", "mid", "senior", "lead", "unclear"]
    verbatim_evidence: dict[str, str]
    pre_filter_blocked: bool
    regex_completeness_score: float
    enrichment_used: bool
    completeness_score: float
    needs_enrichment: bool
    post_enrichment: PostEnrichment | None
    reason: str
    model_used: str = ""
    latency_ms: int = 0
    # Вердикт локальной модели «это про меня?»; None — модель не отвечала
    llm_role_relevant: bool | None = None
    llm_role_family: str = ""
    llm_role_confidence: int = 0
    llm_role_why: str = ""
    brand_data: dict | None = None

    @model_validator(mode="after")
    def salary_range_valid(self) -> "ScoringResult":
        if self.salary_min is not None and self.salary_max is not None:
            if self.salary_min > self.salary_max:
                self.salary_min, self.salary_max = self.salary_max, self.salary_min
        return self
