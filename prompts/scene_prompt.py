CHARACTER_PREFIX = (
    "Korean male worker, Sampyo navy blue uniform with company logo, "
    "reflective yellow stripes, white hard hat with Sampyo logo, "
    "safety gloves, steel-toe boots, "
)


def build_image_prompt(scene_image_prompt: str, equipment: str = "") -> str:
    eq = f"Equipment shown must be {equipment}. " if equipment else ""
    return f"{CHARACTER_PREFIX}{eq}{scene_image_prompt}"
