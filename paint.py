"""Paints missing scenes into art/ with an OpenRouter image model. Usage: python3 paint.py [--force] [scene name ...]"""
import base64
import io
import sys
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from avatar import SCENES, art_path
from voice import api_key, complete

MODEL = "openai/gpt-5-image-mini"  # cheapest OpenAI (ChatGPT) image model on OpenRouter
STYLE = ("Cinematic xianxia digital painting, painterly and atmospheric, ink-wash meets concept art. Portrait 4:5 "
         "composition with the figure centered and clearly readable as a silhouette at thumbnail size. "
         "No text, no logo, no watermark, no border.")
HERO = "a young male cultivator with long black hair in a topknot and flowing dark robes"

PROMPTS = {
    "dawn meditation": f"{HERO} sits in lotus meditation on a flat rock in a still mirror lake at dawn, a huge golden "
                       "rising sun behind him, lavender and peach misty mountains, his reflection in the water.",
    "moonlit bamboo": f"{HERO} sits in lotus meditation on a mossy stone in a bamboo forest at night under a silver "
                      "full moon, blue moonlight, yellow-green fireflies, blue ground mist.",
    "wanderer in the mist": "a lone swordsman in a wide conical bamboo hat and long dark cloak walks a misty mountain "
                            "path, cloak and scarves streaming in the wind, a faded pagoda in the fog, sepia tones.",
    "blossom meditation": f"{HERO} meditates on a hilltop under a blooming cherry blossom tree at dusk, petals "
                          "drifting, pale pink sun over violet mountains.",
    "snow peak stillness": f"{HERO}, seen from behind, stands on a snowy mountain summit, cloak blowing, pale winter "
                           "sky, gentle snowfall, misty peaks below.",
    "lotus lake": f"{HERO} floats cross-legged above a lotus lake at night, a faint glowing halo behind his head, "
                  "a pale mint moon, cyan fireflies, his reflection in dark teal water.",
    "facing the heavens": f"{HERO}, seen from behind, stands at a cliff edge facing an enormous silver-white full "
                          "moon, robes and hair streaming, deep blue night, misty mountains below.",
    "bamboo duel": "a black silhouette of a young swordsman in a wide dynamic lunge holding a long sword overhead "
                   "with both hands, headband tails whipping, misty bright green bamboo forest with light shafts, "
                   "dark foreground bamboo framing the scene, falling leaves, high contrast like a fighting game cover.",
    "ten thousand swords": f"{HERO} stands in a battle stance on a stormy plain while countless glowing flying "
                           "swords fill the purple sky behind him, heavy rain, a lightning bolt, violet and indigo.",
    "blood moon": f"{HERO} stands on a dark ridge with a long sword raised straight to the sky before a huge "
                  "blood-red moon, crimson and black sky, orange embers rising.",
    "burning battlefield": f"{HERO} crouches in a low battle stance, sword pointed forward, other arm thrown back, "
                           "a sky of orange fire and black smoke, swirling embers, distant flames.",
    "facing the beast": "a colossal shadow beast with glowing orange eyes and molten lava cracks looms over a small "
                        "lone young swordsman in dark robes standing his ground in a low stance, toxic green mist "
                        "and glow, embers; the beast fills the left and top, the swordsman is lower right.",
    "lightning tribulation": f"{HERO} stands on a jagged peak with his sword raised as huge blue-white lightning "
                             "bolts strike down from a vortex of black storm clouds, a crackling blue aura.",
    "ascension": f"{HERO} floats cross-legged in meditation high above a sea of golden clouds, radiant god rays "
                 "from a brilliant sun behind him, a golden halo, rising golden light particles.",
    "lord of the stars": f"{HERO} floats in deep space with both arms spread wide, a vast violet and indigo spiral "
                         "galaxy behind him, countless stars, a faint violet aura and halo.",
    "heaven's gate": f"{HERO} stands on clouds with arms open before an enormous glowing celestial gate of ancient "
                     "Chinese architecture, golden light pouring through it, god rays, white-gold and amber.",
}


def paint(key: str, name: str) -> str:
    response = complete(key, [{"role": "user", "content": f"{STYLE} {PROMPTS[name]}"}], max_tokens=8000,
                        model=MODEL, modalities=["image", "text"])
    url = response["choices"][0]["message"]["images"][0]["image_url"]["url"]
    image = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
    image.thumbnail((640, 800), Image.LANCZOS)
    path = art_path(next(s for s in SCENES if s.name == name))
    path.parent.mkdir(exist_ok=True)
    image.save(path, quality=90)
    return f"painted {path.name} ({image.width}x{image.height})"


def main() -> None:
    key = api_key()
    if not key:
        sys.exit("No OpenRouter key in the Keychain. Run: security add-generic-password -s mo-wuji-widget -a openrouter -w")
    force = "--force" in sys.argv
    names = [a for a in sys.argv[1:] if a != "--force"] or list(PROMPTS)
    todo = [n for n in names if force or not art_path(next(s for s in SCENES if s.name == n)).exists()]
    if not todo:
        print("Every scene already has a painting. Use --force to repaint.")
        return
    with ThreadPoolExecutor(max_workers=4) as pool:
        for name, result in zip(todo, pool.map(lambda n: _safe(key, n), todo)):
            print(f"{name}: {result}")


def _safe(key: str, name: str) -> str:
    try:
        return paint(key, name)
    except Exception as error:  # report each failure and keep painting the rest
        return f"failed: {error}"


if __name__ == "__main__":
    main()
