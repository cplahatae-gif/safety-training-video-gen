"""Domain-aware character prefix prompts for FLUX image generation.

Each domain has a distinct visual identity. This replaces the previous
hardcoded "Sampyo industrial worker" prefix that produced nonsensical
results when applied to non-industrial domains (e.g., lab researcher
in industrial uniform).
"""

CHARACTER_PROMPTS: dict[str, str] = {
    "industrial": (
        "Korean male worker, navy blue industrial work uniform, "
        "reflective yellow stripes, white hard hat, "
        "safety gloves, steel-toe boots, "
    ),
    "construction": (
        "Korean male construction worker, sturdy work clothes, "
        "yellow reflective safety vest, white hard hat with strap, "
        "work gloves, heavy-duty boots, "
    ),
    "lab": (
        "Korean researcher, clean white lab coat over plain shirt, "
        "laser safety goggles or safety glasses, "
        "nitrile gloves when handling samples, closed-toe shoes, "
    ),
    "medical": (
        "Korean medical staff, clean blue or green scrubs, "
        "name badge, latex or nitrile gloves when needed, "
        "closed-toe medical shoes, surgical mask if appropriate, "
    ),
    "chemical": (
        "Korean technician, full chemical-resistant suit, "
        "respirator or full-face mask, chemical-resistant gloves, "
        "rubber boots, eye protection, "
    ),
    "general": (
        "Korean worker, neat work uniform appropriate to the task, "
        "necessary personal protective equipment, "
    ),
}


# Multi-angle pose descriptions for character reference sheet generation
CHARACTER_SHEET_POSES: list[dict] = [
    {
        "id": "front",
        "description": "front view, full body, neutral standing pose, looking at camera, neutral expression",
    },
    {
        "id": "working",
        "description": "three-quarter view, focused on equipment, mid-action working pose, professional concentration",
    },
    {
        "id": "side",
        "description": "side profile, full body, hands at sides, natural posture",
    },
    {
        "id": "alert",
        "description": "front view, slightly tilted head, alert and cautious expression, hands raised slightly",
    },
    {
        "id": "instructive",
        "description": "three-quarter view, gesturing toward equipment, confident teaching pose, clear demonstration",
    },
]


def get_character_prefix(domain: str) -> str:
    """Get the character prefix for a given domain. Falls back to general."""
    return CHARACTER_PROMPTS.get(domain, CHARACTER_PROMPTS["general"])


def build_character_sheet_prompt(
    domain: str,
    pose: dict,
    environment_hint: str = "",
    ref_desc: str = "",
) -> str:
    """Build a FLUX prompt for one pose in the character reference sheet.

    ref_desc: optional text description derived from user reference images,
    prepended to lock in character appearance.
    """
    prefix = get_character_prefix(domain)
    bg = environment_hint or "clean neutral studio background, soft lighting"
    ref_part = f"{ref_desc}" if ref_desc else ""
    return (
        f"{ref_part}{prefix}"
        f"{pose['description']}, "
        f"photorealistic portrait, sharp facial features, "
        f"single person, {bg}, single continuous shot, no text overlays"
    )


def build_image_prompt_v2(
    scene_image_prompt: str,
    domain: str = "general",
    equipment: str = "",
) -> str:
    """Domain-aware version of build_image_prompt.

    Drop-in replacement for prompts.scene_prompt.build_image_prompt with
    domain dispatch.
    """
    prefix = get_character_prefix(domain)
    eq = f"Equipment shown must be {equipment}. " if equipment else ""
    return f"{prefix}{eq}{scene_image_prompt}"
