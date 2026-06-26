#!/usr/bin/env python3
"""Загрузка базы уже-клиентов из xlsx в таблицу existing_clients.

Источник: «база_клиентов.xlsx» от клиента (Telegram inbox 2026-05-02).
Колонки: ФИО | Телефон | Активные группы.

Поведение:
  - читает xlsx, пропуская пустые строки;
  - для каждой строки расщепляет ячейку телефонов на отдельные номера
    (split_phones), нормализует;
  - upsert по phone — если телефон уже есть, обновляет full_name + active_groups;
  - логирует summary: rows, phones, inserted, updated, skipped_empty.

Запуск (внутри backend-контейнера):
  docker exec -i voiceagent-backend python /app/infra/scripts/load_existing_clients.py /tmp/base.xlsx
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import openpyxl
from sqlalchemy import select

from shared.db import SessionLocal
from shared.existing_clients import split_phones
from shared.models import ExistingClient


def load(xlsx_path: Path, source_label: str = "base_2026_05_02") -> dict[str, int]:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    ws = wb.active

    stats = {
        "rows": 0,
        "phones_total": 0,
        "inserted": 0,
        "updated": 0,
        "skipped_empty_phone": 0,
    }

    db = SessionLocal()
    seen_in_run: set[str] = set()
    try:
        # Header row пропускаем (строка 1).
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row:
                continue
            full_name, phone_cell, active_groups = (row + (None, None, None))[:3]
            if not full_name and not phone_cell:
                continue
            stats["rows"] += 1
            phones = split_phones(phone_cell)
            if not phones:
                stats["skipped_empty_phone"] += 1
                continue
            for phone in phones:
                stats["phones_total"] += 1
                clean_name = (full_name or "").strip() or None
                clean_groups = (active_groups or "").strip() or None
                if phone in seen_in_run:
                    # дубль внутри файла: 2-3 ребёнка с одним номером родителя.
                    # Объединяем active_groups через «; ».
                    existing = db.execute(
                        select(ExistingClient).where(ExistingClient.phone == phone)
                    ).scalar_one()
                    if clean_groups and clean_groups not in (existing.active_groups or ""):
                        existing.active_groups = (
                            f"{existing.active_groups}; {clean_groups}"
                            if existing.active_groups else clean_groups
                        )
                    stats["updated"] += 1
                    continue
                seen_in_run.add(phone)
                existing = db.execute(
                    select(ExistingClient).where(ExistingClient.phone == phone)
                ).scalar_one_or_none()
                if existing:
                    existing.full_name = clean_name or existing.full_name
                    existing.active_groups = clean_groups or existing.active_groups
                    existing.source = source_label
                    stats["updated"] += 1
                else:
                    db.add(
                        ExistingClient(
                            phone=phone,
                            full_name=clean_name,
                            active_groups=clean_groups,
                            source=source_label,
                        )
                    )
                    db.flush()  # чтобы повторное select видело только что вставленную строку
                    stats["inserted"] += 1
        db.commit()
    finally:
        db.close()

    return stats


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("xlsx", type=Path, help="путь к база_клиентов.xlsx")
    p.add_argument(
        "--source",
        default="base_2026_05_02",
        help="метка source для загруженных строк",
    )
    args = p.parse_args()

    if not args.xlsx.exists():
        print(f"file not found: {args.xlsx}", file=sys.stderr)
        sys.exit(2)

    stats = load(args.xlsx, args.source)
    print("=== Loaded ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
