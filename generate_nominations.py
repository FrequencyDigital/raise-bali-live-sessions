#!/usr/bin/env python3
"""Generate up to 200 nomination fixture records for the SEE Awards form."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

MAX_RECORDS = 200

FIRST_WORDS = [
    "maya", "liam", "sofia", "noah", "aria", "kai", "luna", "leo",
    "nina", "omar", "zara", "eli", "mira", "jules", "hana", "ravi",
    "cleo", "theo", "isla", "nico", "amira", "felix", "suki", "dante",
    "priya", "owen", "yara", "cass", "iris", "hugo",
]

LAST_WORDS = [
    "santos", "rivera", "nguyen", "patel", "okonkwo", "alvarez", "kim",
    "hassan", "berg", "costa", "tanaka", "moreau", "silva", "ahmed",
    "kowal", "duarte", "chen", "rossi", "nair", "beck", "lopez", "park",
    "fernandez", "obrien", "malik", "vogel", "ito", "garcia", "singh", "wahl",
]

BAND_VARIANTS = [
    "Bali live sessions",
    "Bali Live Session",
    "Bali Live Sessions",
    "bali live sessions",
    "BLS",
]

FUDGE_VARIANTS = [
    "Fudge",
    "fudge",
    "FUDGE",
    "Fudge Jarcheh",
    "Fudge jarcheh",
]


def unique_gmail(used: set[str], rng: random.Random) -> str:
    for _ in range(5000):
        email = (
            f"{rng.choice(FIRST_WORDS)}.{rng.choice(LAST_WORDS)}."
            f"{rng.randint(1000, 9999)}@gmail.com"
        )
        if email not in used:
            used.add(email)
            return email
    raise RuntimeError("Could not generate a unique Gmail address")


def build_records(count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    used: set[str] = set()
    records = []
    for i in range(1, count + 1):
        records.append(
            {
                "id": i,
                "email": unique_gmail(used, rng),
                "best_live_band": rng.choice(BAND_VARIANTS),
                "promoter_of_the_year": rng.choice(FUDGE_VARIANTS),
                "social_media_star": rng.choice(FUDGE_VARIANTS),
                "status": "pending",
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate nomination JSON fixtures (max 200 records)."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=MAX_RECORDS,
        help=f"Number of records to generate (1-{MAX_RECORDS}, default {MAX_RECORDS}).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=2026,
        help="RNG seed for reproducible output (default 2026).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("nominations.json"),
        help="Output JSON path (default nominations.json).",
    )
    args = parser.parse_args()

    if args.count < 1 or args.count > MAX_RECORDS:
        parser.error(f"--count must be between 1 and {MAX_RECORDS}")

    records = build_records(args.count, args.seed)
    args.out.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} records to {args.out}")


if __name__ == "__main__":
    main()
