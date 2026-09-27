"""
Загрузка карьерной OS (career-data) — основа кодового ATS-скоринга.

Что читаем (только чтение, файлы вне репозитория — там персональные данные):
- manifest.md — таблицы `ID | Архетипы | Теги | Описание` по всем блокам опыта;
- blocks/*.md — строка «Теги:», компания и текст «Что сделал / Результат»;
- gaps.md — темы, которые спрашивает рынок: статус no-exp = настоящий пробел,
  unformed / closed = опыт есть, просто блок не оформлен;
- core.md — домены профиля и «Честные пробелы»;
- ../drill/market/signals.md — что рынок требует и есть ли опыт: да / частично / нет;
- ../kit-library.json — наборы навыков из прошлых адаптированных резюме.

Результат — CareerIndex: какие термины у соискателя подтверждены опытом, какие
являются пробелами и в каких блоках лежит доказательство.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

logger = logging.getLogger(__name__)

_MANIFEST_ROW = re.compile(r"^\|\s*`([a-z0-9-]+)`\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|")
_BLOCK_HEAD = re.compile(r"Архетипы:\s*([^|\n]+)\|\s*Компания:\s*([^|\n]+)")
_BLOCK_TAGS = re.compile(r"^Теги:\s*(.+)$", re.M)
_SECTION = re.compile(r"^## (Что сделал|Результат|Контекст)\s*\n(.+?)(?=\n## |\Z)", re.M | re.S)
_GAP_STATUS_HAS_EXPERIENCE = {"unformed", "closed"}


@dataclass
class Block:
    id: str
    archetypes: list[str]
    company: str
    tags: list[str]
    text: str  # «Контекст / Что сделал / Результат», в нижнем регистре


@dataclass
class Gap:
    topic: str
    status: str  # no-exp | unformed | closed


@dataclass(eq=False)  # хешируется по объекту: индекс один на процесс, по нему кэшируется словарь ATS
class CareerIndex:
    blocks: list[Block] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    honest_gaps: list[str] = field(default_factory=list)
    # (тема, статус опыта «да» / «частично» / «нет») из drill/market/signals.md
    market_signals: list[tuple[str, str]] = field(default_factory=list)
    # Навыки из наборов kit-library.json: то, что уже подавалось в резюме
    skill_library: list[str] = field(default_factory=list)

    @property
    def loaded(self) -> bool:
        return bool(self.blocks)

    def tags(self) -> set[str]:
        return {t for b in self.blocks for t in b.tags}


def _split_list(cell: str) -> list[str]:
    return [p.strip() for p in cell.split(",") if p.strip()]


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _load_blocks(root: str) -> list[Block]:
    manifest_tags: dict[str, tuple[list[str], list[str]]] = {}
    manifest_path = os.path.join(root, "manifest.md")
    if os.path.exists(manifest_path):
        for line in _read(manifest_path).splitlines():
            m = _MANIFEST_ROW.match(line)
            if m:
                manifest_tags[m.group(1)] = (_split_list(m.group(2)), _split_list(m.group(3)))

    blocks: list[Block] = []
    blocks_dir = os.path.join(root, "blocks")
    for name in sorted(os.listdir(blocks_dir)) if os.path.isdir(blocks_dir) else []:
        if not name.endswith(".md"):
            continue
        block_id = name[:-3]
        body = _read(os.path.join(blocks_dir, name))
        head = _BLOCK_HEAD.search(body)
        tags_line = _BLOCK_TAGS.search(body)
        arch_m, tags_m = manifest_tags.get(block_id, ([], []))
        tags = sorted(set(tags_m) | set(_split_list(tags_line.group(1)) if tags_line else set()))
        text = " ".join(s.group(2) for s in _SECTION.finditer(body)).lower()
        blocks.append(Block(
            id=block_id,
            archetypes=arch_m or (_split_list(head.group(1)) if head else []),
            company=head.group(2).strip() if head else "",
            tags=tags,
            text=text,
        ))
    return blocks


def _load_gaps(root: str) -> list[Gap]:
    path = os.path.join(root, "gaps.md")
    if not os.path.exists(path):
        return []
    gaps = []
    for line in _read(path).splitlines():
        if not line.startswith("|") or re.match(r"^\|\s*-", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[0] in ("Тема", ""):
            continue
        gaps.append(Gap(topic=cells[0], status=cells[4].lower()))
    return gaps


def _load_core(root: str) -> tuple[list[str], list[str]]:
    path = os.path.join(root, "core.md")
    if not os.path.exists(path):
        return [], []
    core = _read(path)
    domains_m = re.search(r"^## Домены\s*\n+(.+?)\n", core, re.M)
    domains = _split_list(domains_m.group(1).rstrip(".")) if domains_m else []
    gaps_m = re.search(r"^## Честные пробелы.*?\n(.+?)(?=\n## |\Z)", core, re.M | re.S)
    honest = [l.lstrip("- ").strip() for l in gaps_m.group(1).splitlines() if l.startswith("- ")] if gaps_m else []
    return domains, honest


def _load_market_signals(jos_root: str) -> list[tuple[str, str]]:
    path = os.path.join(jos_root, "drill", "market", "signals.md")
    if not os.path.exists(path):
        return []
    out = []
    for line in _read(path).splitlines():
        if not line.startswith("|") or re.match(r"^\|\s*-", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0] != "Методология / инструмент":
            out.append((cells[0], cells[4].lower()))
    return out


def _load_skill_library(jos_root: str) -> list[str]:
    path = os.path.join(jos_root, "kit-library.json")
    if not os.path.exists(path):
        return []
    import json
    try:
        data = json.loads(_read(path))
    except ValueError:
        logger.warning("kit-library.json не читается — навыки из резюме не учтены")
        return []
    skills: set[str] = set()
    for item in data.get("skillsets", []):
        text = re.sub(r"\*\*[^*]+:\*\*", "\n", item.get("text", ""))  # убираем «**Инструменты:**»
        for part in re.split(r"[,;•·\n|]", text):
            if "@" in part:  # ники людей из рекомендаций — не навыки
                continue
            part = re.sub(r"\s+", " ", part.replace("(", " ").replace(")", " ")).strip(" .-*&:/")
            if 1 < len(part) < 40:
                skills.add(part)
    return sorted(skills)


@lru_cache(maxsize=1)
def load_career_index(root: str) -> CareerIndex:
    """Читает карьерную OS один раз на процесс. Нет папки — пустой индекс и предупреждение:
    скоринг продолжит работать на правилах без ATS-части."""
    if not root or not os.path.isdir(root):
        logger.warning("CAREER_DATA_DIR не найден (%r) — ATS-совпадение отключено", root)
        return CareerIndex()
    domains, honest = _load_core(root)
    jos_root = os.path.dirname(os.path.normpath(root))
    index = CareerIndex(
        blocks=_load_blocks(root), gaps=_load_gaps(root), domains=domains, honest_gaps=honest,
        market_signals=_load_market_signals(jos_root), skill_library=_load_skill_library(jos_root),
    )
    logger.info("Карьерная OS: блоков %d, тегов %d, пробелов %d (no-exp %d), сигналов рынка %d, навыков из резюме %d",
                len(index.blocks), len(index.tags()), len(index.gaps),
                sum(g.status == "no-exp" for g in index.gaps), len(index.market_signals), len(index.skill_library))
    return index
