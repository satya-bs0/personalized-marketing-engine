"""Load and validate the hand-labeled golden set from data/golden_set.json."""
from __future__ import annotations

import json
from pathlib import Path

from src.schemas import ContentBlock, Donor, GeneratedEmail, GoldenExample

_GOLDEN_SET_PATH = Path(__file__).parent.parent.parent / "data" / "golden_set.json"


def load_golden_set(path: Path | None = None) -> list[GoldenExample]:
    """Load golden set, using model_construct for emails to allow synthetic edge cases."""
    p = path or _GOLDEN_SET_PATH
    raw: list[dict] = json.loads(p.read_text(encoding="utf-8"))

    examples: list[GoldenExample] = []
    for item in raw:
        donor = Donor.model_validate(item["donor"])
        # Use model_construct to bypass validators — golden set intentionally includes
        # synthetic emails with poor readability, wrong facts, etc. to test the scorers.
        email = GeneratedEmail.model_construct(**item["email"])
        selected_blocks = {
            slot: ContentBlock.model_validate(block_data)
            for slot, block_data in item["selected_blocks"].items()
        }
        example = GoldenExample(
            example_id=item["example_id"],
            notes=item["notes"],
            donor=donor,
            email=email,
            selected_blocks=selected_blocks,
            expected_verdict=item["expected_verdict"],
            expected_failures=item.get("expected_failures", []),
        )
        examples.append(example)
    return examples
