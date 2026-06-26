"""CLI отчёт по unit-economics звонков (call_cost_breakdown).

Запуск:
    docker exec voiceagent-backend python -m skills.cost_report.run --period 7d
    docker exec voiceagent-backend python -m skills.cost_report.run --period 30d --csv
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from shared.db import db_session
from shared.models import CallCostBreakdown, ZvonarCall


PERIODS = {
    "24h": timedelta(hours=24),
    "7d":  timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}


def _since(period: str) -> datetime | None:
    if period == "all":
        return None
    return datetime.now(timezone.utc) - PERIODS[period]


def _fetch(period: str) -> dict:
    since = _since(period)
    with db_session() as db:
        q = db.query(
            func.coalesce(func.sum(CallCostBreakdown.sip_cost_cents),  0),
            func.coalesce(func.sum(CallCostBreakdown.tts_cost_cents),  0),
            func.coalesce(func.sum(CallCostBreakdown.stt_cost_cents),  0),
            func.coalesce(func.sum(CallCostBreakdown.llm_cost_cents),  0),
            func.coalesce(func.sum(CallCostBreakdown.total_cost_cents), 0),
            func.count(CallCostBreakdown.id),
        )
        if since is not None:
            q = q.filter(CallCostBreakdown.created_at >= since)
        sip, tts, stt, llm, total, calls = q.first()

        # Дополнительно — сколько среди этих звонков interested (для cost-per-interested)
        zq = db.query(func.count(ZvonarCall.id)).filter(ZvonarCall.outcome == "interested")
        if since is not None:
            zq = zq.filter(ZvonarCall.started_at >= since)
        interested = zq.scalar() or 0

    return {
        "period":            period,
        "calls":             int(calls),
        "interested":        int(interested),
        "sip_dollars":       int(sip)   / 100,
        "tts_dollars":       int(tts)   / 100,
        "stt_dollars":       int(stt)   / 100,
        "llm_dollars":       int(llm)   / 100,
        "total_dollars":     int(total) / 100,
        "per_call_dollars":  (int(total) / 100 / int(calls)) if calls else 0.0,
        "per_interested_dollars": (int(total) / 100 / int(interested)) if interested else None,
    }


def _print_human(d: dict) -> None:
    print(f"=== Unit-economics ({d['period']}) ===")
    print(f"  calls processed:  {d['calls']}")
    print(f"  interested:       {d['interested']}")
    print(f"  SIP:              ${d['sip_dollars']:.2f}")
    print(f"  TTS (ElevenLabs): ${d['tts_dollars']:.2f}")
    print(f"  STT (AssemblyAI): ${d['stt_dollars']:.2f}")
    print(f"  LLM (Anthropic):  ${d['llm_dollars']:.2f}")
    print(f"  TOTAL:            ${d['total_dollars']:.2f}")
    print(f"  cost / call:      ${d['per_call_dollars']:.4f}")
    if d["per_interested_dollars"] is not None:
        print(f"  cost / interested:${d['per_interested_dollars']:.4f}")
    else:
        print(f"  cost / interested: — (нет interested в периоде)")


def _print_csv(d: dict) -> None:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["period", "calls", "interested", "sip", "tts", "stt", "llm", "total", "per_call", "per_interested"])
    w.writerow([
        d["period"], d["calls"], d["interested"],
        f"{d['sip_dollars']:.2f}", f"{d['tts_dollars']:.2f}",
        f"{d['stt_dollars']:.2f}", f"{d['llm_dollars']:.2f}",
        f"{d['total_dollars']:.2f}", f"{d['per_call_dollars']:.4f}",
        f"{d['per_interested_dollars']:.4f}" if d['per_interested_dollars'] is not None else "",
    ])
    sys.stdout.write(buf.getvalue())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--period", choices=list(PERIODS) + ["all"], default="7d")
    p.add_argument("--csv", action="store_true")
    args = p.parse_args()

    d = _fetch(args.period)
    (_print_csv if args.csv else _print_human)(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
