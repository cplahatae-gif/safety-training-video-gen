"""Scene image prompt builder (legacy + domain-aware).

build_image_prompt() — legacy signature (defaults to industrial domain for back-compat)
build_image_prompt_v2() — domain-aware (preferred for new code)
"""
from prompts.character_prompts import build_image_prompt_v2, get_character_prefix


# Legacy constant — kept for backwards compat. New code should use
# get_character_prefix(domain) from character_prompts instead.
CHARACTER_PREFIX = get_character_prefix("industrial")


def build_image_prompt(scene_image_prompt: str, equipment: str = "", domain: str = "industrial") -> str:
    """Build full image prompt with character prefix.

    The `domain` parameter selects the appropriate character outfit. When omitted,
    defaults to 'industrial' to preserve legacy behavior. Pass the actual domain
    for non-industrial SOPs (lab/medical/chemical/construction/general).
    """
    return build_image_prompt_v2(scene_image_prompt, domain=domain, equipment=equipment)
