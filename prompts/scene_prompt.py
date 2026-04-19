CHARACTER_PREFIX = (
    "Korean male worker, Sampyo navy blue uniform with company logo, "
    "reflective yellow stripes, white hard hat with Sampyo logo, "
    "safety gloves, steel-toe boots, "
)


def build_image_prompt(scene_image_prompt: str) -> str:
    """Prepend character consistency prefix to every image prompt."""
    return f"{CHARACTER_PREFIX}{scene_image_prompt}"
