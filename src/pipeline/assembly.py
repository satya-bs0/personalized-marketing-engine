from __future__ import annotations

from pathlib import Path

from src.llm.client import AnthropicClient
from src.schemas import ContentBlock, Donor, GeneratedEmail, LLMResponse

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _fill_template(template: str, **kwargs) -> str:
    # Use <<key>> syntax to avoid collision with {token} placeholders inside block texts.
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"<<{key}>>", str(value))
    return result


def _build_assemble_email_tool() -> dict:
    return {
        "name": "assemble_email",
        "description": "Assemble the final donor email from approved blocks with token substitution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Email subject line — ≤80 characters after token substitution",
                },
                "body": {
                    "type": "string",
                    "description": (
                        "Email body in plain text — ≤500 words. "
                        "Order: opener → impact → social_proof → cta → signoff. "
                        "No markdown, no HTML."
                    ),
                },
                "tokens_used": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of tokens actually substituted (e.g. ['first_name', 'center_name'])",
                },
            },
            "required": ["subject", "body", "tokens_used"],
        },
    }


def assemble_email(
    donor: Donor,
    selected_blocks: dict[str, ContentBlock],
    client: AnthropicClient,
) -> tuple[GeneratedEmail, LLMResponse]:
    """Run Stage 2: ask Claude to assemble the email from selected blocks + token values.

    selected_blocks must be keyed by slot name: subject, opener, impact,
    social_proof, cta, signoff.

    Returns the GeneratedEmail (Pydantic-validated) and full LLM telemetry.
    Pydantic raises ValidationError if subject > 80 chars or body > 500 words.
    """
    system = (_PROMPTS_DIR / "assembly_system.md").read_text()
    user_template = (_PROMPTS_DIR / "assembly_user.md").read_text()

    # Block texts inserted first so that {token} placeholders inside them are visible
    # to Claude but are NOT substituted by _fill_template (only <<...>> patterns are).
    user = _fill_template(
        user_template,
        subject_text=selected_blocks["subject"].approved_text,
        opener_text=selected_blocks["opener"].approved_text,
        impact_text=selected_blocks["impact"].approved_text,
        social_proof_text=selected_blocks["social_proof"].approved_text,
        cta_text=selected_blocks["cta"].approved_text,
        signoff_text=selected_blocks["signoff"].approved_text,
        first_name=donor.first_name,
        weeks_since_last_donation=donor.weeks_since_last_donation,
        lifetime_donations=donor.lifetime_donations,
        estimated_patients_helped=donor.estimated_patients_helped,
        center_name=donor.center_name,
    )

    tool = _build_assemble_email_tool()
    response = client.call(
        system=system,
        user=user,
        tool=tool,
        temperature=0.3,
        max_tokens=800,
    )

    email = GeneratedEmail(**response.tool_input)
    return email, response
