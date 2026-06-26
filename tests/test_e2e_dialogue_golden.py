"""E2E регрессия: rule-based прогон каждой фикстуры → outcome совпадает с golden_outcomes.json.

Защищает от случайных правок в `shared/qualification.py` rules / списках сигналов.
Если правки осознанные — обновить `tests/fixtures/golden_outcomes.json`.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from shared.qualification import classify

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
GOLDEN = json.loads((FIXTURES / "golden_outcomes.json").read_text(encoding="utf-8"))


def _extract_client_lines(path: pathlib.Path) -> str:
    """Извлекает то что говорил клиент (строки `client: ...`)."""
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("client:"):
            lines.append(line.split(":", 1)[1].strip())
    return "\n".join(lines)


@pytest.mark.parametrize("name,expected", list(GOLDEN["fixtures"].items()))
def test_fixture_outcome_matches_golden(name: str, expected: str):
    text = _extract_client_lines(FIXTURES / name)
    actual = classify(text).outcome
    assert actual == expected, (
        f"{name}: expected {expected}, got {actual}.\n"
        f"text:\n{text}\n"
        "Если правка classify rules осознанная — обновить golden_outcomes.json."
    )


def test_all_fixtures_covered():
    fixtures_on_disk = {
        p.name for p in FIXTURES.iterdir()
        if p.suffix == ".txt" and p.name.startswith("dialog_")
    }
    assert fixtures_on_disk == set(GOLDEN["fixtures"]), (
        "Несовпадение между фикстурами на диске и golden_outcomes.json:\n"
        f"  на диске: {sorted(fixtures_on_disk)}\n"
        f"  в golden: {sorted(GOLDEN['fixtures'])}"
    )
