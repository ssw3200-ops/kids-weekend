"""manual_events.yaml 직접 입력 행사"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from common import Event, sido_of


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def collect(path: Path) -> list[Event]:
    if not path.exists():
        return []
    rows = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    events = []
    for r in rows:
        events.append(Event(
            source="manual",
            title=str(r["title"]),
            region=sido_of(str(r["region"])) or str(r["region"]),
            start=_d(r["start"]),
            end=_d(r.get("end", r["start"])),
            place=str(r.get("place", "")),
            price=str(r.get("price", "")),
            link=str(r.get("link", "")),
            age=str(r.get("age", "")),
            genre=str(r.get("genre", "행사")),
            kid_flag=True,
            tags=[str(r["note"])] if r.get("note") else [],
        ))
    return events
