"""Rule-based классификация заинтересованности клиента.

Источник критериев — `note_044701_35.txt` от 2026-04-30 (раздел
"Критерии заинтересованного клиента"). Когда подключим LLM-оценку
(`OPENAI_API_KEY`), эта функция станет fallback-ом — её результат
будет сравниваться с LLM-вердиктом для калибровки.

Используется:
  - в `zvonar/dialogue/finish` для определения outcome без LLM;
  - в `zvonar.simulate` для прогона тестовых диалогов без сети.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.models import CallOutcome


# Слова-маркеры (нормализованные, lowercase, без пунктуации).
# Каждый сигнал работает по принципу "достаточно одного попадания".
_TRAINING_INTEREST_SIGNALS = (
    "локац",        # локация / локацию / локации
    "филиал",
    "время",
    "расписан",
    "пробн",
    "записа",
    "запиш",
    "тренер",
    "адрес",
)

_CAMP_INTEREST_SIGNALS = (
    "лагер",
    "поток",
    "когда начин",
    "программ",
    "что вход",
    "база",
    "питан",
)

_NOT_INTERESTED_SIGNALS = (
    "не интересно",
    "не нужно",
    "не нужны",
    "не надо",
    "уберите",
    "удалите",
    "не звон",
    "перестаньте",
    "не беспокой",
    "уже занимаемся",
    "ходим в друг",
)

_CALLBACK_SIGNALS = (
    "перезвон",
    "позже",
    "позвоните потом",
    "не сейчас",
    "за рулём",
    "за рулем",
    "на работе",
    "в дороге",
    "в зале",
)


@dataclass(frozen=True)
class QualificationResult:
    outcome: str  # CallOutcome value
    reasons: tuple[str, ...]  # какие триггеры сработали (для аудита)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _hits(text: str, signals: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(s for s in signals if s in text)


_KIND_TO_OUTCOME = {
    "interest": CallOutcome.interested.value,
    "not_interested": CallOutcome.not_interested.value,
    "callback": CallOutcome.callback.value,
}


def classify(transcript: str) -> QualificationResult:
    """Классифицирует диалог по фразам клиента.

    Категории читаются из БД (`qualification_categories`) через
    `shared.agent_config`. Клиент через `/admin/qualification` может
    добавлять/менять категории. Если БД недоступна — fallback на
    константы _TRAINING_INTEREST_SIGNALS / _CAMP_INTEREST_SIGNALS / etc.

    Приоритет:
      1. Любая категория с kind=not_interested → not_interested
      2. Любая категория с kind=interest или custom → interested
      3. Любая категория с kind=callback → callback
      4. Без сигналов → not_interested (консервативно)
    """
    from shared import agent_config  # lazy

    text = _normalize(transcript)
    categories = agent_config.get_qualification_categories()

    by_kind: dict[str, list[str]] = {"not_interested": [], "interest": [], "callback": []}
    for cat in categories:
        hits = _hits(text, tuple(cat.phrases))
        if not hits:
            continue
        kind = cat.kind if cat.kind in by_kind else "interest"  # custom → interest
        by_kind[kind].extend(f"{cat.key}:{s}" for s in hits)

    if by_kind["not_interested"]:
        return QualificationResult(
            outcome=CallOutcome.not_interested.value,
            reasons=tuple(by_kind["not_interested"]),
        )
    if by_kind["interest"]:
        return QualificationResult(
            outcome=CallOutcome.interested.value,
            reasons=tuple(by_kind["interest"]),
        )
    if by_kind["callback"]:
        return QualificationResult(
            outcome=CallOutcome.callback.value,
            reasons=tuple(by_kind["callback"]),
        )

    return QualificationResult(
        outcome=CallOutcome.not_interested.value,
        reasons=("default:no_signal",),
    )
