import math
import random
import tkinter as tk
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFilter, ImageTk

AV_W, AV_H = 120, 138
SS = 3                          # supersample factor for smooth edges
K = AV_W * SS / 100             # scene units (0..100 wide, 0..115 tall) -> supersampled pixels
W, H = AV_W * SS, AV_H * SS
BLUR = SS * AV_W / 200


def u(*pts: float) -> list[float]:
    return [v * K for v in pts]


@dataclass
class Scene:
    name: str
    mood: str
    sky: tuple[tuple[int, int, int], tuple[int, int, int]]
    pose: str
    fig: tuple[int, int, int]
    particles: str
    pcolor: tuple[int, int, int]
    body: tuple | None = None           # (x, y, r, color, glow color)
    ridge: tuple[int, int, int] | None = None
    ground: tuple | None = None         # (points, color)
    extras: tuple[str, ...] = ()
    fx: tuple[str, ...] = ()
    fx_color: tuple[int, int, int] = (255, 255, 255)
    wind: float = 1.0
    lift: float = 0.0
    rate: float = 0.3


SCENES = [
    # ---- calm ----
    Scene("dawn meditation", "calm", ((40, 48, 92), (240, 170, 110)), "seated", (22, 18, 34), "motes", (255, 225, 170),
          body=(50, 84, 13, (255, 220, 160), (255, 170, 110)), ridge=(96, 72, 104),
          ground=([(30, 92), (70, 92), (65, 97), (35, 97)], (24, 20, 34)), extras=("lake",), fx=("reflection",),
          wind=0.5, rate=0.15),
    Scene("moonlit bamboo", "calm", ((6, 10, 28), (26, 44, 74)), "seated", (4, 6, 12), "fireflies", (210, 255, 140),
          body=(68, 26, 11, (232, 238, 246), (120, 150, 210)), ridge=(16, 28, 50),
          ground=([(0, 115), (0, 92), (100, 92), (100, 115)], (6, 9, 16)), extras=("bamboo", "fog"), wind=0.35,
          rate=0.12),
    Scene("wanderer in the mist", "calm", ((58, 40, 28), (198, 166, 130)), "wanderer", (26, 16, 10), "ash",
          (70, 46, 30), ridge=(120, 92, 70), ground=([(0, 115), (0, 98), (100, 97), (100, 115)], (40, 26, 18)),
          extras=("pagoda", "fog"), wind=1.1, rate=0.25),
    Scene("blossom meditation", "calm", ((62, 32, 72), (242, 156, 172)), "seated", (32, 12, 32), "petals",
          (255, 190, 210), body=(70, 60, 13, (255, 210, 200), (255, 150, 175)), ridge=(116, 64, 104),
          ground=([(0, 115), (0, 92), (100, 91), (100, 115)], (42, 18, 40)), extras=("blossom",), wind=0.7,
          rate=0.35),
    Scene("snow peak stillness", "calm", ((72, 92, 124), (206, 218, 232)), "back", (22, 28, 40), "snow",
          (255, 255, 255), body=(24, 26, 8, (255, 255, 255), (220, 232, 255)), ridge=(140, 158, 182),
          ground=([(10, 115), (38, 97), (56, 98), (90, 115)], (236, 241, 248)), extras=("fog",), wind=0.8, rate=0.45),
    Scene("lotus lake", "calm", ((6, 26, 36), (40, 108, 108)), "seated", (4, 14, 18), "fireflies", (150, 255, 230),
          body=(50, 28, 16, (205, 255, 240), (80, 200, 180)), ridge=(14, 52, 58), extras=("lake",),
          fx=("reflection", "halo"), fx_color=(170, 255, 235), lift=7, wind=0.4, rate=0.15),
    Scene("facing the heavens", "calm", ((10, 14, 30), (54, 64, 104)), "back", (4, 5, 10), "motes", (200, 210, 255),
          body=(50, 38, 28, (212, 216, 232), (140, 150, 205)), ridge=(28, 34, 62),
          ground=([(0, 115), (0, 99), (60, 97), (74, 102), (100, 115)], (5, 6, 12)), wind=1.0, rate=0.15),
    # ---- battle ----
    Scene("bamboo duel", "battle", ((34, 62, 26), (196, 228, 150)), "overhead", (6, 12, 5), "leaves", (60, 110, 40),
          ground=([(0, 115), (0, 98), (100, 98), (100, 115)], (6, 12, 5)), extras=("bamboo_forest", "shafts", "fog"),
          fx=("slash",), fx_color=(235, 255, 210), wind=1.2, rate=0.25),
    Scene("ten thousand swords", "battle", ((16, 10, 32), (72, 42, 94)), "overhead", (4, 2, 8), "rain",
          (190, 190, 230), ridge=(30, 20, 48), ground=([(0, 115), (0, 98), (100, 99), (100, 115)], (6, 4, 12)),
          extras=("storm",), fx=("lightning", "slash"), fx_color=(205, 190, 255), wind=1.6, rate=0.9),
    Scene("blood moon", "battle", ((14, 9, 16), (94, 15, 24)), "sword_sky", (6, 4, 7), "embers", (255, 140, 70),
          body=(30, 30, 18, (176, 26, 36), (150, 20, 30)), ridge=(42, 9, 15),
          ground=([(0, 115), (0, 99), (40, 97), (100, 101), (100, 115)], (8, 5, 8)), fx=("gleam",), wind=1.2),
    Scene("burning battlefield", "battle", ((32, 8, 4), (224, 94, 22)), "low_guard", (12, 4, 2), "embers",
          (255, 200, 90), ridge=(70, 20, 8),
          ground=([(0, 115), (0, 97), (30, 99), (64, 96), (100, 98), (100, 115)], (12, 4, 2)),
          extras=("smoke",), fx=("slash",), fx_color=(255, 214, 140), wind=1.3, rate=0.8),
    Scene("facing the beast", "battle", ((6, 12, 8), (44, 76, 40)), "low_guard", (3, 6, 3), "embers", (255, 170, 60),
          ground=([(0, 115), (0, 98), (100, 98), (100, 115)], (4, 8, 4)), body=(30, 44, 34, (34, 72, 34), (70, 160, 70)), extras=("beast", "fog"),
          fx=("eyes",), fx_color=(255, 150, 40), wind=0.9, rate=0.3),
    Scene("lightning tribulation", "battle", ((8, 8, 18), (40, 44, 74)), "sword_sky", (2, 2, 6), "motes",
          (170, 200, 255), ridge=(22, 26, 46), ground=([(10, 115), (30, 97), (62, 98), (90, 115)], (4, 4, 8)),
          extras=("storm",), fx=("lightning", "aura"), fx_color=(160, 185, 255), wind=1.5, rate=0.3),
    # ---- god-like ----
    Scene("ascension", "god-like", ((70, 44, 12), (255, 222, 146)), "seated", (44, 26, 6), "motes", (255, 236, 170),
          body=(50, 60, 24, (255, 246, 214), (255, 214, 130)), extras=("clouds",),
          fx=("rays", "halo", "aura"), fx_color=(255, 230, 150), lift=14, wind=0.5, rate=0.4),
    Scene("lord of the stars", "god-like", ((2, 2, 10), (22, 12, 44)), "arms_open", (2, 2, 6), "motes",
          (230, 225, 255), extras=("stars", "galaxy"), fx=("aura", "halo", "twinkle"), fx_color=(170, 150, 255),
          lift=6, wind=0.5, rate=0.3),
    Scene("heaven's gate", "god-like", ((120, 92, 44), (255, 242, 206)), "arms_open", (58, 38, 12), "motes",
          (255, 246, 200), extras=("gate", "clouds"), fx=("rays", "aura"), fx_color=(255, 236, 170), lift=4,
          wind=0.6, rate=0.35),

]


def lerp(a: tuple, b: tuple, f: float) -> tuple[int, ...]:
    return tuple(int(x + (y - x) * f) for x, y in zip(a, b))


def build_background(sc: Scene) -> Image.Image:
    img = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=lerp(sc.sky[0], sc.sky[1], (y / H) ** 1.3) + (255,))
    rnd = random.Random(sc.name)

    def blurred(draw_fn, radius: float) -> None:
        layer = Image.new("RGBA", (W, H))
        draw_fn(ImageDraw.Draw(layer))
        img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius * BLUR)))

    if "stars" in sc.extras:
        for _ in range(140):
            x, y, r = rnd.uniform(0, 100), rnd.uniform(0, 115), rnd.uniform(0.15, 0.5)
            d.ellipse(u(x - r, y - r, x + r, y + r), fill=(255, 255, 255, rnd.randint(90, 230)))
    if "galaxy" in sc.extras:
        def galaxy(g: ImageDraw.ImageDraw) -> None:
            for i in range(30):
                f = i / 30
                x, y = -10 + 120 * f, 95 - 80 * f + rnd.uniform(-4, 4)
                g.ellipse(u(x - 12, y - 5, x + 12, y + 5), fill=(120, 80, 200, 40))
                g.ellipse(u(x - 5, y - 2, x + 5, y + 2), fill=(230, 180, 255, 40))
        blurred(galaxy, 10)
    if "storm" in sc.extras:
        def storm(g: ImageDraw.ImageDraw) -> None:
            for _ in range(16):
                x, y = rnd.uniform(-10, 110), rnd.uniform(-8, 30)
                g.ellipse(u(x - 20, y - 8, x + 20, y + 8), fill=(6, 4, 12, 170))
        blurred(storm, 8)
    if sc.body:
        x, y, r, color, glow = sc.body
        blurred(lambda g: g.ellipse(u(x - r * 1.7, y - r * 1.7, x + r * 1.7, y + r * 1.7), fill=glow + (150,)), 16)
        d.ellipse(u(x - r, y - r, x + r, y + r), fill=color + (255,))
    if "gate" in sc.extras:
        gc = lerp(sc.sky[1], sc.fig, 0.35) + (255,)
        d.rectangle(u(26, 40, 31, 96), fill=gc)
        d.rectangle(u(69, 40, 74, 96), fill=gc)
        d.polygon(u(16, 38, 84, 38, 90, 32, 10, 32), fill=gc)
        d.rectangle(u(22, 44, 78, 47), fill=gc)
    if "bamboo_forest" in sc.extras:
        for depth, count in ((0.75, 9), (0.5, 6)):
            col = lerp(sc.sky[1], sc.fig, 1 - depth) + (255,)
            for _ in range(count):
                x, w = rnd.uniform(-5, 105), rnd.uniform(1.5, 3) * (1.6 - depth)
                d.rectangle(u(x, -2, x + w, 98), fill=col)
                for y in range(rnd.randint(2, 12), 98, 13):
                    d.rectangle(u(x - 0.3, y, x + w + 0.3, y + 0.7), fill=col)
    if "pagoda" in sc.extras:
        pc = lerp(sc.sky[1], sc.fig, 0.45) + (255,)
        px = 18
        for i, (w, y) in enumerate(((13, 66), (10.5, 74), (8, 82))):
            d.polygon(u(px - w, y + 2, px + w, y + 2, px + w * 0.55, y - 2, px - w * 0.55, y - 2), fill=pc)
            d.rectangle(u(px - w * 0.45, y + 2, px + w * 0.45, y + 8), fill=pc)
        d.line(u(px, 64, px, 56), fill=pc, width=int(0.8 * K))
        d.rectangle(u(px - 5, 88, px + 5, 97), fill=pc)
    if "beast" in sc.extras:
        def beast(g: ImageDraw.ImageDraw) -> None:
            g.ellipse(u(-30, 8, 52, 110), fill=(2, 6, 3, 240))
            g.ellipse(u(-10, 0, 46, 60), fill=(2, 6, 3, 240))
            g.polygon(u(8, 12, 2, -6, 16, 8), fill=(2, 6, 3, 240))
            g.polygon(u(30, 10, 40, -6, 38, 14), fill=(2, 6, 3, 240))
        blurred(beast, 2)
        cracks = Image.new("RGBA", (W, H))
        cd = ImageDraw.Draw(cracks)
        for _ in range(9):
            x, y = rnd.uniform(-5, 40), rnd.uniform(20, 100)
            pts = [x, y]
            for _ in range(4):
                x, y = x + rnd.uniform(-5, 6), y + rnd.uniform(3, 7)
                pts += [x, y]
            cd.line(u(*pts), fill=(255, 120, 30, 200), width=int(0.6 * K))
        img.alpha_composite(cracks.filter(ImageFilter.GaussianBlur(0.8 * BLUR)))
        img.alpha_composite(cracks)
    if sc.ridge:
        for lift, mix, step, amp in ((12, 0.55, 14, 10), (0, 0.0, 9, 6)):
            ridge = [(0, 115)] + [(x, 84 - lift + rnd.uniform(-amp, amp * 0.6)) for x in range(-step, 101 + step, step)] + [(100, 115)]
            layer = Image.new("RGBA", (W, H))
            ImageDraw.Draw(layer).polygon([v * K for pt in ridge for v in pt], fill=lerp(sc.ridge, sc.sky[1], mix) + (255,))
            img.alpha_composite(layer.filter(ImageFilter.GaussianBlur((2.5 if mix else 1.2) * BLUR)))
    if "smoke" in sc.extras:
        def smoke(g: ImageDraw.ImageDraw) -> None:
            for _ in range(12):
                x, y = rnd.uniform(0, 100), rnd.uniform(30, 90)
                g.ellipse(u(x - 14, y - 7, x + 14, y + 7), fill=(30, 10, 6, 110))
        blurred(smoke, 7)
    if "lake" in sc.extras:
        top, bot = lerp(sc.sky[1], (0, 0, 0), 0.35), lerp(sc.sky[0], (0, 0, 0), 0.5)
        for y in range(int(92 * K), H):
            d.line([(0, y), (W, y)], fill=lerp(top, bot, (y - 92 * K) / (H - 92 * K)) + (255,))
        if sc.body:
            x, _, r, color, _ = sc.body
            def streak(g: ImageDraw.ImageDraw) -> None:
                for i in range(10):
                    yy = 93 + i * 2.2
                    g.ellipse(u(x - r * (1 - i / 14), yy - 0.5, x + r * (1 - i / 14), yy + 0.5), fill=color + (110,))
            blurred(streak, 1.2)
    if "clouds" in sc.extras:
        def clouds(g: ImageDraw.ImageDraw) -> None:
            for _ in range(22):
                x, y = rnd.uniform(-10, 110), rnd.uniform(88, 112)
                g.ellipse(u(x - 16, y - 6, x + 16, y + 6), fill=(255, 248, 230, 170))
        blurred(clouds, 5)
    if "bamboo" in sc.extras:
        bc = (10, 16, 22, 255)
        for x in (8, 15, 84, 93):
            d.rectangle(u(x, -2, x + 2.2, 93), fill=bc)
            for y in range(6, 92, 14):
                d.rectangle(u(x - 0.4, y, x + 2.6, y + 0.8), fill=bc)
            for y in range(10, 70, 22):
                side = -1 if x < 50 else 1
                d.polygon(u(x + 1, y, x + 1 + side * 9, y - 3, x + 1 + side * 4, y + 1.5), fill=bc)
    if "blossom" in sc.extras:
        bc = sc.ground[1] + (255,)
        d.line(u(-2, 18, 20, 26, 36, 22), fill=bc, width=int(1.8 * K))
        d.line(u(10, 23, 18, 36), fill=bc, width=int(1.1 * K))
        for _ in range(26):
            x, y, r = rnd.uniform(0, 42), rnd.uniform(12, 38), rnd.uniform(2, 4.5)
            d.ellipse(u(x - r, y - r * 0.8, x + r, y + r * 0.8), fill=(255, rnd.randint(150, 200), 205, 200))
    if "shafts" in sc.extras:
        def shafts(g: ImageDraw.ImageDraw) -> None:
            for x in (30, 52, 70):
                g.polygon(u(x, -5, x + 7, -5, x - 14, 100, x - 26, 100), fill=(255, 255, 230, 55))
        blurred(shafts, 5)
    if sc.ground:
        pts, color = sc.ground
        d.polygon([v * K for pt in pts for v in pt], fill=color + (255,))
    if "fog" in sc.extras:
        fog_col = lerp(sc.sky[1], (255, 255, 255), 0.15)
        def fog(g: ImageDraw.ImageDraw) -> None:
            for _ in range(10):
                x, y = rnd.uniform(-10, 110), rnd.uniform(90, 102)
                g.ellipse(u(x - 22, y - 3, x + 22, y + 3), fill=fog_col + (90,))
        blurred(fog, 4)
    if "bamboo_forest" in sc.extras:
        fc = sc.fig + (255,)
        for x, w in ((2, 5), (88, 6.5)):
            d.rectangle(u(x, -2, x + w, 115), fill=fc)
            for y in range(8, 110, 16):
                d.rectangle(u(x - 0.5, y, x + w + 0.5, y + 1.2), fill=fc)
    return img


def build_rays(color: tuple[int, int, int], cx: float, cy: float) -> Image.Image:
    size = int(max(W, H) * 1.6)
    rays = Image.new("RGBA", (size, size))
    d = ImageDraw.Draw(rays)
    c, reach = size / 2, size / 2
    for i in range(18):
        a = i * 2 * math.pi / 18
        d.polygon([(c, c), (c + reach * math.cos(a - 0.07), c + reach * math.sin(a - 0.07)),
                   (c + reach * math.cos(a + 0.07), c + reach * math.sin(a + 0.07))], fill=color + (70,))
    return rays.filter(ImageFilter.GaussianBlur(2 * BLUR))


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float = 1.0
    phase: float = field(default_factory=lambda: random.uniform(0, 6.3))


class Avatar:
    def __init__(self, parent: tk.Widget, tick_ms: int) -> None:
        self.dt = tick_ms / 1000
        # Tk can't draw images on a transparent background, so the scene sits on a solid one it fully covers
        self.label_img = tk.Label(parent, bg="#000000", bd=0, highlightthickness=0)
        self.photo = ImageTk.PhotoImage(Image.new("RGBA", (AV_W, AV_H), (0, 0, 0, 255)))
        self.label_img.config(image=self.photo)
        self.cache: dict[str, Image.Image] = {}
        self.order = SCENES[:]
        random.shuffle(self.order)
        self.index = 0
        self.t = 0.0
        self.set_scene(self.order[0])

    def set_scene(self, sc: Scene) -> None:
        self.sc = sc
        if sc.name not in self.cache:
            self.cache[sc.name] = build_background(sc)
        self.rays = None
        if "rays" in sc.fx:
            # 18 rays repeat every 20 degrees, so 20 pre-rotated frames loop seamlessly
            big = build_rays(sc.fx_color, 50, 50)
            rs, cx, cy = big.size[0], int(50 * K), int(52 * K)
            box = (rs // 2 - cx, rs // 2 - cy, rs // 2 - cx + W, rs // 2 - cy + H)
            self.rays = [big.rotate(a, resample=Image.BILINEAR).crop(box) for a in range(20)]
        self.parts: list[Particle] = []
        self.next_bolt, self.bolt_until, self.bolt = self.t + 1.5, 0.0, []

    def next_pose(self) -> None:
        self.index = (self.index + 1) % len(self.order)
        self.set_scene(self.order[self.index])

    # ---------- figure ----------
    def ribbon(self, d: ImageDraw.ImageDraw, x0: float, y0: float, length: float, width: float,
               slope: float, amp: float, phase: float = 0) -> None:
        n, wind = 44, self.sc.wind
        for i in range(n + 1):
            f = i / n
            x = x0 + length * f
            y = y0 + slope * abs(length) * f + amp * wind * f * math.sin(self.t * (1 + wind) - f * 5 + phase)
            r = width * (1 - 0.85 * f) / 2
            d.ellipse(u(x - r, y - r, x + r, y + r), fill=self.fill)

    def cap(self, d: ImageDraw.ImageDraw, a: tuple, b: tuple, ra: float, rb: float) -> None:
        """Tapered limb segment from a (radius ra) to b (radius rb)."""
        (ax, ay), (bx, by) = a, b
        L = math.hypot(bx - ax, by - ay) or 1
        nx, ny = -(by - ay) / L, (bx - ax) / L
        d.polygon(u(ax + nx * ra, ay + ny * ra, bx + nx * rb, by + ny * rb,
                    bx - nx * rb, by - ny * rb, ax - nx * ra, ay - ny * ra), fill=self.fill)
        d.ellipse(u(ax - ra, ay - ra, ax + ra, ay + ra), fill=self.fill)
        d.ellipse(u(bx - rb, by - rb, bx + rb, by + rb), fill=self.fill)

    def body(self, d: ImageDraw.ImageDraw, j: dict, pants: bool = True) -> None:
        f = self.fill
        hx, hy = j["head"]
        d.ellipse(u(hx - 2.9, hy - 3.5, hx + 2.9, hy + 3.5), fill=f)
        d.ellipse(u(hx - 1.3 + j.get("knot", 0.6), hy - 5.6, hx + 1.3 + j.get("knot", 0.6), hy - 2.8), fill=f)
        self.cap(d, j["head"], j["neck"], 1.5, 1.5)
        self.cap(d, j["sl"], j["sr"], 1.9, 1.9)
        d.polygon(u(*j["sl"], *j["sr"], *j["wr"], *j["wl"]), fill=f)
        d.polygon(u(*j["wl"], *j["wr"], *j["hr_"], *j["hl_"]), fill=f)
        for side in "lr":
            self.cap(d, j["s" + side], j["e" + side], 1.75, 1.3)
            self.cap(d, j["e" + side], j["h" + side], 1.3, 1.0)
            d.ellipse(u(j["h" + side][0] - 1.2, j["h" + side][1] - 1.2, j["h" + side][0] + 1.2, j["h" + side][1] + 1.2), fill=f)
            self.cap(d, j["h" + side + "_"], j["k" + side], 3.0, 2.2)
            self.cap(d, j["k" + side], j["f" + side], 2.2, 1.5 if not pants else 2.0)
            if pants:
                fx, fy = j["f" + side]
                d.polygon(u(fx - 2.6, fy, fx + 2.6, fy, fx + 1.6, fy - 4, fx - 1.6, fy - 4), fill=f)

    def pose_joints(self, name: str, b: float) -> tuple[dict, list]:
        """Joint positions (scene units) and ribbons [(x, y, length, width, slope, amp, phase)]."""
        if name == "seated":
            j = dict(head=(50, 59 + b), neck=(50, 63 + b), sl=(43, 65.5 + b), sr=(57, 65.5 + b),
                     el=(40.3, 73), er=(59.7, 73), hl=(36, 80.5), hr=(64, 80.5),
                     wl=(46, 78), wr=(54, 78), hl_=(44, 82), hr_=(56, 82),
                     kl=(33, 86), kr=(67, 86), fl=(57, 88), fr=(43, 88))
            return j, [(52, 57 + b, 24, 2.4, 0.25, 2.5, 0), (54, 78, 16, 1.6, 0.15, 2, 1.5)]
        if name == "back":
            j = dict(head=(46, 44 + b), neck=(46, 48.5 + b), sl=(39, 51.5 + b), sr=(53, 51 + b),
                     el=(37.6, 60), er=(54.6, 60), hl=(43, 66), hr=(49, 66),
                     wl=(42.2, 66), wr=(49.8, 66), hl_=(41.5, 70), hr_=(50.5, 70),
                     kl=(42, 83), kr=(51.5, 83.5), fl=(41, 97), fr=(53, 97))
            return j, [(49, 63, 30, 7, 0.55, 3, 0), (48, 43 + b, 22, 2.2, 0.12, 2.5, 2), (50, 66, 18, 1.6, 0.2, 2, 1)]
        if name == "overhead":
            j = dict(head=(44, 45.5 + b), neck=(45, 49.5 + b), sl=(39.5, 53 + b), sr=(52, 52 + b),
                     el=(37.5, 44.5), er=(51, 42.5), hl=(43, 37.5), hr=(45.5, 37.5),
                     wl=(42.5, 68), wr=(50.5, 68), hl_=(42, 72), hr_=(51, 72),
                     kl=(32, 82), kr=(61, 85), fl=(26, 97), fr=(71, 97), knot=1)
            return j, [(47, 43 + b, 22, 2, 0.05, 2.5, 0), (50, 66, 24, 6, 0.45, 3, 1), (48, 68, 18, 1.6, 0.2, 2.5, 2)]
        if name == "low_guard":
            j = dict(head=(57, 49 + b), neck=(58.5, 52.5 + b), sl=(53.5, 55 + b), sr=(65, 56 + b),
                     el=(46, 59), er=(72, 58.5), hl=(39, 60.5), hr=(79, 53),
                     wl=(55.5, 70), wr=(63, 70.5), hl_=(55, 74), hr_=(64, 74.5),
                     kl=(45, 82), kr=(74, 86), fl=(39, 97), fr=(83, 97), knot=1)
            return j, [(63, 68, 22, 6, 0.4, 3, 0), (59, 47 + b, 22, 2.2, 0.1, 2.5, 1.5)]
        if name == "sword_sky":
            j = dict(head=(48, 44.5 + b), neck=(48.5, 48.5 + b), sl=(42, 51.5 + b), sr=(55, 51.5 + b),
                     el=(39.5, 59), er=(57, 42.5), hl=(37.5, 66), hr=(58, 34),
                     wl=(45, 66), wr=(52, 66), hl_=(44.5, 70), hr_=(52.5, 70),
                     kl=(41, 83), kr=(57, 84), fl=(37, 97), fr=(61, 97))
            return j, [(51, 64, 28, 7, 0.5, 3, 0), (50, 43 + b, 22, 2.2, 0.12, 2.5, 2)]
        if name == "wanderer":
            j = dict(head=(50, 44.5 + b), neck=(50, 48.5 + b), sl=(44, 51.5 + b), sr=(56, 51.5 + b),
                     el=(42.5, 59.5), er=(58, 59.5), hl=(44, 66), hr=(61, 65),
                     wl=(47, 66), wr=(53, 66), hl_=(46.5, 70), hr_=(53.5, 70),
                     kl=(44, 83), kr=(56, 84), fl=(40, 97), fr=(61, 96))
            return j, [(55, 52, 30, 9, 0.55, 3.5, 0), (53, 49, 32, 2, -0.1, 3, 1.3), (53, 50.5, 26, 1.6, -0.02, 3, 2.5)]
        # arms_open
        j = dict(head=(50, 43.5 + b), neck=(50, 48 + b), sl=(43, 51 + b), sr=(57, 51 + b),
                 el=(35, 44.5 + b), er=(65, 44.5 + b), hl=(28, 37 + b), hr=(72, 37 + b),
                 wl=(46.2, 66), wr=(53.8, 66), hl_=(45.8, 70), hr_=(54.2, 70),
                 kl=(47.8, 83), kr=(52, 83.5), fl=(48.2, 96), fr=(51.6, 95))
        return j, [(53, 68, 9, 7, 2.6, 1.5, 0), (47, 68, -8, 6, 2.6, 1.5, 1.5), (52, 42 + b, 22, 2.2, 0.15, 2.5, 2)]

    def draw_figure(self, d: ImageDraw.ImageDraw, breath: float) -> tuple[float, float, tuple[float, float]]:
        """Draws the pose; returns head centre and a strike point for lightning."""
        sc = self.sc
        lift = sc.lift + (1.2 * math.sin(self.t * 1.1) if sc.lift else 0)
        j, ribbons = self.pose_joints(sc.pose, -0.5 * breath)
        knot = j.pop("knot", 0.6)
        j = {k: (x, y - lift) for k, (x, y) in j.items()}
        j["knot"] = knot
        self.body(d, j, pants=sc.pose not in ("seated",))
        for x, y, length, width, slope, amp, phase in ribbons:
            self.ribbon(d, x, y - lift, length, width, slope, amp, phase)

        f = self.fill
        if sc.pose == "seated":
            d.ellipse(u(34, 82 - lift, 66, 90 - lift), fill=f)
        if sc.pose == "wanderer":
            hx, hy = j["head"]
            d.polygon(u(hx - 10, hy + 0.5, hx, hy - 8, hx + 10, hy + 0.5), fill=f)
            d.ellipse(u(hx - 11.5, hy - 1, hx + 11.5, hy + 1.6), fill=f)
            self.cap(d, (j["hl"][0] - 1, j["hl"][1] - 3), (j["hl"][0] + 3, j["hl"][1] + 14), 0.6, 0.6)
        if sc.pose == "overhead":
            (ax, ay) = j["hl"]
            d.line(u(ax + 4, ay - 1, ax, ay), fill=f, width=int(1.1 * K))
            d.line(u(ax, ay, ax - 14, ay - 4, ax - 30, ay - 3), fill=f, width=int(1.1 * K), joint="curve")
            return j["head"][0], j["head"][1], (ax - 30, ay - 3)
        if sc.pose == "low_guard":
            (ax, ay) = j["hl"]
            d.line(u(ax + 3, ay + 0.5, ax, ay), fill=f, width=int(1.1 * K))
            d.line(u(ax, ay, ax - 16, ay - 6, ax - 32, ay - 13), fill=f, width=int(1.1 * K), joint="curve")
            d.line(u(ax + 0.5, ay - 2, ax - 0.5, ay + 2), fill=f, width=int(1.0 * K))
            return j["head"][0], j["head"][1], (ax - 32, ay - 13)
        if sc.pose == "sword_sky":
            (ax, ay) = j["hr"]
            d.line(u(ax, ay + 3, ax + 1.5, ay - 31), fill=f, width=int(1.1 * K))
            d.line(u(ax - 2.5, ay - 1, ax + 2.8, ay - 0.6), fill=f, width=int(1.0 * K))
            self.blade = (ax, ay - 1, ax + 1.5, ay - 31)
            return j["head"][0], j["head"][1], (ax + 1.5, ay - 31)
        return j["head"][0], j["head"][1], (j["head"][0], j["head"][1] - 6)

    # ---------- particles ----------
    def spawn(self) -> None:
        kind, wind = self.sc.particles, self.sc.wind
        r = random.uniform
        if kind == "embers":
            self.parts.append(Particle(r(5, 80), 97, r(0.2, 0.5) * wind, -r(0.15, 0.45)))
        elif kind == "motes":
            self.parts.append(Particle(r(10, 90), r(60, 105), r(-0.05, 0.1), -r(0.08, 0.25)))
        elif kind == "petals":
            self.parts.append(Particle(r(-10, 60), r(-5, 40), r(0.3, 0.6) * wind, r(0.15, 0.35)))
        elif kind == "leaves":
            self.parts.append(Particle(r(-10, 70), r(-5, 30), r(0.35, 0.7) * wind, r(0.2, 0.4)))
        elif kind == "ash":
            self.parts.append(Particle(r(-10, 60), r(20, 95), r(0.3, 0.6) * wind, r(-0.1, 0.05)))
        elif kind == "snow":
            self.parts.append(Particle(r(-10, 100), -3, r(0.05, 0.25) * wind, r(0.2, 0.45)))
        elif kind == "rain":
            for _ in range(3):
                self.parts.append(Particle(r(-20, 100), r(-10, 20), 0.7 * wind, 3.2))
        elif kind == "fireflies":
            self.parts.append(Particle(r(10, 90), r(50, 95), 0, 0))

    def draw_particles(self, d: ImageDraw.ImageDraw) -> None:
        kind, (cr, cg, cb) = self.sc.particles, self.sc.pcolor
        for p in self.parts:
            p.x += p.vx
            p.y += p.vy
            p.life -= 0.006 if kind != "rain" else 0.03
            if kind == "fireflies":
                p.x += 0.25 * math.sin(self.t * 0.9 + p.phase)
                p.y += 0.2 * math.cos(self.t * 0.7 + p.phase * 1.3)
                a = max(0.0, math.sin(self.t * 2 + p.phase)) * p.life
                rr = 0.7
            elif kind == "rain":
                d.line(u(p.x, p.y, p.x - 0.7, p.y - 3.2), fill=(cr, cg, cb, 90), width=max(1, int(0.25 * K)))
                continue
            elif kind == "leaves":
                p.x += 0.25 * math.sin(self.t * 2.4 + p.phase)
                ang = self.t * 3 + p.phase
                lx, ly = 1.3 * math.cos(ang), 0.5 * math.sin(ang) + 0.3
                d.polygon(u(p.x - lx, p.y - ly, p.x, p.y - 0.4, p.x + lx, p.y + ly, p.x, p.y + 0.4),
                          fill=(cr, cg, cb, int(240 * p.life)))
                continue
            elif kind == "ash":
                a, rr = math.sin(math.pi * p.life), 0.4
            elif kind == "petals":
                p.x += 0.2 * math.sin(self.t * 2 + p.phase)
                a, rr = p.life, 0.8
                d.ellipse(u(p.x - rr, p.y - rr * 0.55, p.x + rr, p.y + rr * 0.55), fill=(cr, cg, cb, int(230 * a)))
                continue
            elif kind == "snow":
                p.x += 0.12 * math.sin(self.t * 1.4 + p.phase)
                a, rr = p.life, 0.45
            elif kind == "motes":
                a, rr = math.sin(math.pi * p.life), 0.45
            else:
                a, rr = p.life, 0.55 * p.life + 0.2
            d.ellipse(u(p.x - rr, p.y - rr, p.x + rr, p.y + rr), fill=(cr, cg, cb, int(255 * max(0.0, a))))
        self.parts = [p for p in self.parts if p.life > 0 and -25 < p.x < 125 and -15 < p.y < 120]

    # ---------- frame ----------
    def tick(self) -> None:
        self.t += self.dt
        sc = self.sc
        breath = math.sin(self.t * 2 * math.pi / 5)
        frame = self.cache[sc.name].copy()

        if self.rays is not None:
            frame.alpha_composite(self.rays[int(self.t * 4) % 20])

        fig_layer = Image.new("RGBA", (W, H))
        fd = ImageDraw.Draw(fig_layer)
        self.fill = sc.fig + (255,)
        hx, hy, strike = self.draw_figure(fd, breath)

        d = ImageDraw.Draw(frame)
        if "halo" in sc.fx:
            r = 8 + 0.8 * breath
            d.ellipse(u(hx - r, hy - r, hx + r, hy + r), outline=sc.fx_color + (170,), width=max(1, int(0.7 * K)))
        if "aura" in sc.fx:
            alpha = fig_layer.getchannel("A").filter(ImageFilter.GaussianBlur(3.5 * BLUR))
            alpha = alpha.point(lambda v: int(v * (0.75 + 0.25 * breath)))
            glow = Image.new("RGBA", (W, H), sc.fx_color + (0,))
            glow.putalpha(alpha)
            frame.alpha_composite(glow)
        frame.alpha_composite(fig_layer)
        if "reflection" in sc.fx:
            off = int(2 * 92 * K) - H
            refl = fig_layer.transpose(Image.FLIP_TOP_BOTTOM).crop((0, 0, W, H - off))
            refl.putalpha(refl.getchannel("A").point(lambda v: v * 30 // 100))
            frame.alpha_composite(refl, dest=(0, off))
        d = ImageDraw.Draw(frame)

        if "gleam" in sc.fx:
            g = (self.t % 6) / 1.2
            if g < 1:
                bx, by, tx, ty = self.blade
                gx, gy = bx + (tx - bx) * g, by + (ty - by) * g
                d.ellipse(u(gx - 0.9, gy - 0.9, gx + 0.9, gy + 0.9), fill=(255, 220, 210, 255))
        if "slash" in sc.fx:
            s = (self.t % 2.8) / 0.5
            if s < 1:
                d.arc(u(20, 22, 98, 100), start=-80 + 40 * s, end=-10 + 50 * s,
                      fill=sc.fx_color + (int(230 * (1 - s)),), width=max(1, int(1.2 * K)))
        if "eyes" in sc.fx:
            glow = 0.6 + 0.4 * math.sin(self.t * 1.3)
            for ex, ey in ((16, 24), (28, 25)):
                d.ellipse(u(ex - 3.5, ey - 1.6, ex + 3.5, ey + 1.6), fill=sc.fx_color + (int(90 * glow),))
                d.polygon(u(ex - 2.4, ey, ex + 2.4, ey - 0.9, ex + 1.8, ey + 0.6), fill=(255, 220, 120, int(255 * glow)))
        if "twinkle" in sc.fx:
            rnd = random.Random(int(self.t * 2))
            for _ in range(5):
                x, y = rnd.uniform(0, 100), rnd.uniform(0, 70)
                d.line(u(x - 1.6, y, x + 1.6, y), fill=(255, 255, 255, 200), width=1)
                d.line(u(x, y - 1.6, x, y + 1.6), fill=(255, 255, 255, 200), width=1)

        if random.random() < sc.rate:
            self.spawn()
        self.draw_particles(d)

        if "lightning" in sc.fx:
            if self.t >= self.next_bolt:
                tx, ty = strike if sc.pose == "sword_sky" else (random.uniform(60, 95), 97)
                x, pts = random.uniform(tx - 25, tx + 15), []
                for i in range(9):
                    f = i / 8
                    pts += [x + (tx - x) * f + (random.uniform(-4, 4) if 0 < i < 8 else 0), -5 + (ty + 5) * f]
                self.bolt, self.bolt_until = pts, self.t + 0.3
                self.next_bolt = self.t + random.uniform(3, 6)
            if self.t < self.bolt_until:
                fade = (self.bolt_until - self.t) / 0.3
                flash = Image.new("RGBA", (W, H), (255, 255, 255, int(70 * fade)))
                frame.alpha_composite(flash)
                d = ImageDraw.Draw(frame)
                d.line(u(*self.bolt), fill=sc.fx_color + (int(160 * fade),), width=int(1.6 * K), joint="curve")
                d.line(u(*self.bolt), fill=(255, 255, 255, int(255 * fade)), width=max(1, int(0.5 * K)))

        self.photo.paste(frame.resize((AV_W, AV_H), Image.BOX))
