"""Загрузка CSV-базы лидов в БД.

Ожидаемый формат CSV:
    phone,name,segment,note
где segment ∈ naborki|academy|branch|special|unknown

Запуск:
    docker exec voiceagent-backend python -m zvonar.csv_loader path/to/leads.csv
"""
from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

from shared.db import db_session
from shared.models import Lead, LeadSegment

log = logging.getLogger(__name__)

VALID_SEGMENTS = {s.value for s in LeadSegment}


def normalize_phone(p: str) -> str:
    p = p.strip()
    digits = "".join(c for c in p if c.isdigit() or c == "+")
    if digits.startswith("8"):
        digits = "+7" + digits[1:]
    if not digits.startswith("+"):
        digits = "+" + digits
    return digits


def load_csv(path: Path) -> int:
    """Совместимость с CLI — возвращает только число inserted."""
    stats = load_csv_stats(path)
    return stats["inserted"]


def load_csv_stats(path: Path) -> dict[str, int]:
    """Расширенная версия — возвращает {inserted, skipped, total}."""
    inserted = 0
    skipped = 0
    total = 0
    with db_session() as db, open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            phone_raw = row.get("phone") or row.get("Phone") or row.get("Телефон") or ""
            if not phone_raw:
                skipped += 1
                continue
            phone = normalize_phone(phone_raw)
            segment = (row.get("segment") or "").strip().lower() or LeadSegment.unknown.value
            if segment not in VALID_SEGMENTS:
                segment = LeadSegment.unknown.value
            stmt = (
                insert(Lead)
                .values(
                    phone=phone,
                    name=(row.get("name") or row.get("Name") or "").strip() or None,
                    segment=segment,
                )
                .on_conflict_do_nothing(index_elements=["phone"])
                .returning(Lead.id)
            )
            new_id = db.execute(stmt).scalar_one_or_none()
            if new_id is not None:
                inserted += 1
            else:
                skipped += 1
    log.info("csv loaded: total=%d inserted=%d skipped=%d", total, inserted, skipped)
    return {"inserted": inserted, "skipped": skipped, "total": total}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m zvonar.csv_loader <leads.csv>")
        sys.exit(2)
    print(f"Inserted leads: {load_csv(Path(sys.argv[1]))}")
