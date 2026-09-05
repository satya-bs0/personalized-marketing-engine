from __future__ import annotations

from pathlib import Path

from src.llm.client import AnthropicClient
from src.schemas import BlockSelection, ContentBlock, Donor, LLMResponse

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Maps slot name → BlockSelection field name (used for ID validation)
_SLOT_TO_FIELD = {
    "subject": "subject_block_id",
    "opener": "opener_block_id",
    "impact": "impact_block_id",
    "social_proof": "social_proof_block_id",
    "cta": "cta_block_id",
    "signoff": "signoff_block_id",
}


class SelectionError(Exception):
    """Raised when the LLM returns block IDs that are not in the candidate set."""


def _fill_template(template: str, **kwargs) -> str:
    # Use <<key>> syntax to avoid collision with {token} placeholders inside block texts.
    # Replacement order matters: donor dimension values before candidates_formatted,
    # so that donor-value substitutions happen before block texts (containing {tokens}) are inserted.
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"<<{key}>>", str(value))
    return result


def _format_candidates(candidates: dict[str, list[ContentBlock]]) -> str:
    lines: list[str] = []
    for slot, blocks in candidates.items():
        lines.append(f"### {slot.upper()} ({len(blocks)} candidate(s))")
        for b in blocks:
            lines.append(f"  block_id: {b.block_id}")
            lines.append(f"  text: {b.approved_text}")
            lines.append(f"  segment_fit: {b.segment_fit}")
            lines.append("")
    return "\n".join(lines)


def _build_select_blocks_tool() -> dict:
    return {
        "name": "select_blocks",
        "description": "Select exactly one approved content block per email slot.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject_block_id": {
                    "type": "string",
                    "description": "Block ID for the email subject line",
                },
                "opener_block_id": {
                    "type": "string",
                    "description": "Block ID for the email opener paragraph",
                },
                "impact_block_id": {
                    "type": "string",
                    "description": "Block ID for the donor impact statement",
                },
                "social_proof_block_id": {
                    "type": "string",
                    "description": "Block ID for the social proof section",
                },
                "cta_block_id": {
                    "type": "string",
                    "description": "Block ID for the call-to-action",
                },
                "signoff_block_id": {
                    "type": "string",
                    "description": "Block ID for the email sign-off",
                },
                "selection_reasoning": {
                    "type": "string",
                    "description": "Brief reasoning for these selections (≤500 chars total)",
                },
            },
            "required": [
                "subject_block_id",
                "opener_block_id",
                "impact_block_id",
                "social_proof_block_id",
                "cta_block_id",
                "signoff_block_id",
                "selection_reasoning",
            ],
        },
    }


def select_blocks_for_donor(
    donor: Donor,
    candidates: dict[str, list[ContentBlock]],
    client: AnthropicClient,
) -> tuple[BlockSelection, LLMResponse]:
    """Run Stage 1: ask Claude to pick the best approved block for each email slot.

    Returns the BlockSelection and full LLM telemetry.
    Raises SelectionError if any returned block ID is not in the candidate set.
    """
    system = (_PROMPTS_DIR / "selection_system.md").read_text()
    user_template = (_PROMPTS_DIR / "selection_user.md").read_text()

    # donor dimensions substituted first; candidates_formatted inserted last so that
    # {token} placeholders inside block texts are never touched by _fill_template.
    user = _fill_template(
        user_template,
        first_name=donor.first_name,
        lifecycle_stage=donor.lifecycle_stage,
        recency_tier=donor.recency_tier,
        weeks_since_last_donation=donor.weeks_since_last_donation,
        lifetime_donations=donor.lifetime_donations,
        estimated_patients_helped=donor.estimated_patients_helped,
        center_name=donor.center_name,
        candidates_formatted=_format_candidates(candidates),
    )

    tool = _build_select_blocks_tool()
    response = client.call(
        system=system,
        user=user,
        tool=tool,
        temperature=0.0,
        max_tokens=500,
    )

    selection = BlockSelection(**response.tool_input)

    invalid: list[str] = []
    for slot, field in _SLOT_TO_FIELD.items():
        returned_id = getattr(selection, field)
        valid_ids = {b.block_id for b in candidates.get(slot, [])}
        if returned_id not in valid_ids:
            invalid.append(
                f"{field}={returned_id!r} not in {slot} candidates {sorted(valid_ids)}"
            )

    if invalid:
        raise SelectionError(
            f"LLM returned block IDs outside the candidate set: {'; '.join(invalid)}"
        )

    return selection, response
