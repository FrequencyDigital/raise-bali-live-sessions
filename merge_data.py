#!/usr/bin/env python3
"""Merge nominations.json and events.json into a single combined.json.

Drops promoter_of_the_year and social_media_star, keeps every other answer
field. Records are paired by id; the nominations email is kept and the
events email for that id is discarded (the two files share no addresses).
"""

from __future__ import annotations

import json
from pathlib import Path

DROP = {"promoter_of_the_year", "social_media_star"}


def load(path: Path) -> dict[int, dict]:
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise SystemExit(f"{path} must be a non-empty JSON list")
    return {record["id"]: record for record in records}


def main() -> None:
    nominations = load(Path("nominations.json"))
    events = load(Path("events.json"))

    merged = []
    for record_id in sorted(set(nominations) | set(events)):
        nomination = nominations.get(record_id, {})
        event = events.get(record_id, {})

        combined = {
            "id": record_id,
            "email": nomination.get("email") or event.get("email"),
        }
        for source in (nomination, event):
            for key, value in source.items():
                if key in DROP or key in {"id", "email", "status", "error"}:
                    continue
                combined[key] = value
        combined["status"] = "pending"
        merged.append(combined)

    out = Path("combined.json")
    out.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")

    fields = sorted({key for record in merged for key in record})
    print(f"Wrote {out} — {len(merged)} records, fields: {fields}")


if __name__ == "__main__":
    main()
