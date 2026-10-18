import ctypes
import fcntl
import json
import random
import subprocess
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from PIL import Image

from avatar import Avatar, time_of_day
from voice import Voice

BASE = Path(__file__).resolve().parent
REFRESH_MS = 30 * 60 * 1000
TICK_MS = 180
WIDTH = 470               # card width at 100%
TEXT_W = 274              # width of the text column at 100%
PAD = 16                  # card inset and the gap between scene and text
XS, SM, MD = 4, 8, 12     # vertical spacing steps inside the text column
SCALES = (0.8, 1.8)       # smallest and largest card size
FONT = "Lora"
# colours checked on the tinted glass over a bright sky: secondary text 5.0:1, main 6.3:1 (10:1+ on darker wallpapers)
BG, FG, GOLD, DIM = "systemTransparent", "#f7f4ee", "#e8c47c", "#d6dbe2"
BAR_DIM = "#8796a6"       # chart bars below goal, progress track, secondary button outline
INK = "#111820"           # text on gold
FIELD_BG = "#1c2530"
TINT = (0x11 / 255, 0x18 / 255, 0x20 / 255, 0.40)   # the lightest tint that keeps text readable
STATE_FILE = Path.home() / "Library/Application Support/mo-wuji-widget/state.json"
DURATIONS = (25, 50, 90)


objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.dylib")
appkit = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
objc.objc_getClass.restype = ctypes.c_void_p
objc.sel_registerName.restype = ctypes.c_void_p
appkit.CGEventSourceButtonState.restype = ctypes.c_bool
appkit.CGEventSourceButtonState.argtypes = [ctypes.c_int32, ctypes.c_uint32]
appkit.CFDataCreate.restype = ctypes.c_void_p
appkit.CFDataCreate.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long]
appkit.CFRelease.argtypes = [ctypes.c_void_p]
appkit.CGDataProviderCreateWithCFData.restype = ctypes.c_void_p
appkit.CGDataProviderCreateWithCFData.argtypes = [ctypes.c_void_p]
appkit.CGColorSpaceCreateWithName.restype = ctypes.c_void_p
appkit.CGColorSpaceCreateWithName.argtypes = [ctypes.c_void_p]
appkit.CGImageCreate.restype = ctypes.c_void_p
appkit.CGImageCreate.argtypes = [ctypes.c_size_t] * 5 + [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                                                           ctypes.c_void_p, ctypes.c_bool, ctypes.c_int]
appkit.CGImageRelease.argtypes = [ctypes.c_void_p]


def load_fonts() -> None:
    """Registers the bundled fonts for this process only, so nothing is installed system-wide."""
    ct = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreText.framework/CoreText")
    cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
    cf.CFURLCreateFromFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
    ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
    for font in (BASE / "fonts").glob("*.ttf"):
        path = str(font).encode()
        url = cf.CFURLCreateFromFileSystemRepresentation(None, path, len(path), False)
        ct.CTFontManagerRegisterFontsForURL(url, 1, None)  # 1 = process scope


def msg(obj: int, sel: bytes, *args: int, restype=ctypes.c_void_p, argtypes: tuple = ()) -> int:
    send = objc.objc_msgSend
    send.restype = restype
    send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
    return send(obj, objc.sel_registerName(sel), *args)


def ns_app() -> int:
    return msg(objc.objc_getClass(b"NSApplication"), b"sharedApplication")


def hide_dock_icon() -> None:
    msg(ns_app(), b"setActivationPolicy:", 1, argtypes=(ctypes.c_long,))


def pin_to_desktop() -> int:
    appkit.CGWindowLevelForKey.restype = ctypes.c_int32
    level = appkit.CGWindowLevelForKey(18) + 1  # just above desktop icons, below all app windows
    behavior = 1 | 16 | 64  # all Spaces | stationary in Mission Control | skip Cmd-` cycling
    windows = msg(ns_app(), b"windows")
    for i in range(msg(windows, b"count", restype=ctypes.c_ulong)):
        win = msg(windows, b"objectAtIndex:", i, argtypes=(ctypes.c_ulong,))
        msg(win, b"setLevel:", level, argtypes=(ctypes.c_long,))
        msg(win, b"setCollectionBehavior:", behavior, argtypes=(ctypes.c_ulong,))
    return win


class CGRect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("w", ctypes.c_double), ("h", ctypes.c_double)]


def make_glass(win: int, width: int, height: int) -> None:
    """Puts a native frosted-glass view behind Tk's transparent content, like macOS desktop widgets."""
    msg(win, b"setOpaque:", 0, argtypes=(ctypes.c_bool,))
    # a non-opaque window lets clicks fall through its transparent pixels, and the glass counts as
    # transparent; setting this explicitly makes the whole card clickable
    msg(win, b"setIgnoresMouseEvents:", 0, argtypes=(ctypes.c_bool,))
    msg(win, b"setBackgroundColor:", msg(objc.objc_getClass(b"NSColor"), b"clearColor"), argtypes=(ctypes.c_void_p,))
    content = msg(win, b"contentView")
    glass = msg(msg(objc.objc_getClass(b"NSVisualEffectView"), b"alloc"), b"initWithFrame:",
                CGRect(0, 0, width, height), argtypes=(CGRect,))
    msg(glass, b"setMaterial:", 13, argtypes=(ctypes.c_long,))      # HUD window: dark frosted glass
    msg(glass, b"setBlendingMode:", 0, argtypes=(ctypes.c_long,))   # blur what is behind the window
    msg(glass, b"setState:", 1, argtypes=(ctypes.c_long,))          # stay frosted even though never focused
    msg(glass, b"setAutoresizingMask:", 18, argtypes=(ctypes.c_ulong,))
    msg(glass, b"setWantsLayer:", 1, argtypes=(ctypes.c_bool,))
    layer = msg(glass, b"layer")
    msg(layer, b"setCornerRadius:", 16.0, argtypes=(ctypes.c_double,))
    msg(layer, b"setMasksToBounds:", 1, argtypes=(ctypes.c_bool,))
    msg(layer, b"setBorderWidth:", 0.5, argtypes=(ctypes.c_double,))
    appkit.CGColorCreateGenericRGB.restype = ctypes.c_void_p
    appkit.CGColorCreateGenericRGB.argtypes = [ctypes.c_double] * 4
    msg(layer, b"setBorderColor:", appkit.CGColorCreateGenericRGB(1, 1, 1, 0.18), argtypes=(ctypes.c_void_p,))
    name = msg(objc.objc_getClass(b"NSString"), b"stringWithUTF8String:", b"NSAppearanceNameDarkAqua",
               argtypes=(ctypes.c_char_p,))
    dark = msg(objc.objc_getClass(b"NSAppearance"), b"appearanceNamed:", name, argtypes=(ctypes.c_void_p,))
    msg(glass, b"setAppearance:", dark, argtypes=(ctypes.c_void_p,))
    frame = msg(content, b"superview")
    msg(frame, b"addSubview:positioned:relativeTo:", glass, -1, content,
        argtypes=(ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p))
    # a dark tint over the blur keeps text readable over bright wallpapers; it sits below Tk's content
    tint = msg(msg(objc.objc_getClass(b"NSView"), b"alloc"), b"initWithFrame:", CGRect(0, 0, width, height),
               argtypes=(CGRect,))
    msg(tint, b"setAutoresizingMask:", 18, argtypes=(ctypes.c_ulong,))
    msg(tint, b"setWantsLayer:", 1, argtypes=(ctypes.c_bool,))
    tint_layer = msg(tint, b"layer")
    msg(tint_layer, b"setBackgroundColor:", appkit.CGColorCreateGenericRGB(*TINT), argtypes=(ctypes.c_void_p,))
    msg(tint_layer, b"setCornerRadius:", 16.0, argtypes=(ctypes.c_double,))
    msg(frame, b"addSubview:positioned:relativeTo:", tint, -1, content,
        argtypes=(ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p))


class SceneLayer:
    """Shows the animated scene through Core Animation. Tk redraws a changing image slowly on macOS:
    about 8% of a core at this frame rate, against about 3% this way."""

    def __init__(self, win: int, avatar: Avatar) -> None:
        self.avatar, self.label = avatar, avatar.label_img
        self.content = msg(win, b"contentView")
        self.pixels = msg(win, b"backingScaleFactor", restype=ctypes.c_double)   # 2 on Retina screens
        self.space = appkit.CGColorSpaceCreateWithName(ctypes.c_void_p.in_dll(appkit, "kCGColorSpaceSRGB"))
        msg(self.content, b"setWantsLayer:", 1, argtypes=(ctypes.c_bool,))
        self.layer = msg(objc.objc_getClass(b"CALayer"), b"layer")
        msg(self.layer, b"setAutoresizingMask:", 8, argtypes=(ctypes.c_uint,))   # keep its distance from the top
        msg(msg(self.content, b"layer"), b"addSublayer:", self.layer, argtypes=(ctypes.c_void_p,))
        self.label.winfo_toplevel().bind("<Configure>", self.place, add="+")
        self.place()

    @staticmethod
    def transaction(change: Callable[[], None]) -> None:
        ca = objc.objc_getClass(b"CATransaction")
        msg(ca, b"begin")
        msg(ca, b"setDisableActions:", 1, argtypes=(ctypes.c_bool,))   # no fade or slide between frames
        change()
        msg(ca, b"commit")

    def place(self, e: tk.Event | None = None) -> None:
        """Keeps the layer over the scene's slot in the Tk layout; macOS measures from the bottom-left."""
        root = self.label.winfo_toplevel()
        x, y = self.label.winfo_rootx() - root.winfo_rootx(), self.label.winfo_rooty() - root.winfo_rooty()
        w, h = self.avatar.size
        height = msg(self.content, b"frame", restype=CGRect).h
        self.transaction(lambda: msg(self.layer, b"setFrame:", CGRect(x, height - y - h, w, h), argtypes=(CGRect,)))

    def show(self, frame: Image.Image) -> None:
        w, h = (round(v * self.pixels) for v in self.avatar.size)
        pixels = frame.resize((w, h), Image.LANCZOS if w > frame.width else Image.BOX).tobytes()
        data = appkit.CFDataCreate(None, pixels, len(pixels))
        provider = appkit.CGDataProviderCreateWithCFData(data)
        image = appkit.CGImageCreate(w, h, 8, 32, w * 4, self.space, 5, provider, None, False, 0)  # 5 = RGB, skip alpha
        self.transaction(lambda: msg(self.layer, b"setContents:", image, argtypes=(ctypes.c_void_p,)))
        appkit.CGImageRelease(image)
        appkit.CFRelease(provider)
        appkit.CFRelease(data)


class NSPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


def mouse_location() -> NSPoint:
    return msg(objc.objc_getClass(b"NSEvent"), b"mouseLocation", restype=NSPoint)


def card_is_under_pointer(win: int) -> bool:
    """True only if a click at the pointer would land on the card, not on a window covering it."""
    point = mouse_location()
    hit = msg(objc.objc_getClass(b"NSWindow"), b"windowNumberAtPoint:belowWindowWithWindowNumber:", point, 0,
              restype=ctypes.c_long, argtypes=(NSPoint, ctypes.c_long))
    return hit == msg(win, b"windowNumber", restype=ctypes.c_long)


def is_visible(win: int) -> bool:
    return bool(msg(win, b"occlusionState", restype=ctypes.c_ulong) & 2)


def mouse_down() -> bool:
    return appkit.CGEventSourceButtonState(0, 0)


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(STATE_FILE)


def notify(title: str, text: str) -> None:
    subprocess.run(["osascript", "-e", f'display notification "{text}" with title "{title}" sound name "Glass"'],
                   check=False)


def summarize(sessions: list[dict], goal: int) -> dict:
    per_day = Counter(date.fromisoformat(s["date"]) for s in sessions)
    today = date.today()
    # a streak counts days that met the goal; today only joins once it is met
    streak, day = 0, today if per_day[today] >= goal else today - timedelta(days=1)
    while per_day[day] >= goal:
        streak += 1
        day -= timedelta(days=1)
    return {
        "today": per_day[today],
        "today_minutes": sum(s["minutes"] for s in sessions if s["date"] == today.isoformat()),
        "week": [(today - timedelta(days=i), per_day[today - timedelta(days=i)]) for i in range(6, -1, -1)],
        "streak": streak,
        "total": len(sessions),
        "hours": sum(s["minutes"] for s in sessions) / 60,
    }


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


class QuoteWidget:
    def __init__(self) -> None:
        self.entries = [line.split("|") for line in (BASE / "quotes.txt").read_text().splitlines()
                        if line.count("|") == 2]
        self.current = ""
        self.dragging = False
        self.actions: dict[tk.Widget, Callable[[], None]] = {}   # clickable widgets and what they do
        self.watching = False
        self.was_down = False
        self.timer_job: str | None = None
        self.state = load_state()
        self.state.setdefault("goal", 4)
        self.state.setdefault("minutes", 50)
        self.state.setdefault("sessions", [])
        self.state.setdefault("generated", [])
        self.state.setdefault("chronicles", {})
        self.fresh: dict | None = None      # a generated quote waiting to be shown
        self.ai_turn = False                # AI and built-in quotes take turns
        self.fetching = False
        self.chronicling: str | None = None
        self.scale = 1.0
        self.fonts: dict[tuple[int, str], tkfont.Font] = {}
        self.buttons: dict[tk.Canvas, list] = {}       # canvas -> [text, kind, square]
        self.spaced: list[tuple[tk.Widget, dict]] = []  # packed widgets whose padding scales with the card
        self.resizing: tuple[int, float] | None = None

        load_fonts()
        self.root = tk.Tk()
        hide_dock_icon()
        self.root.overrideredirect(True)
        self.root.attributes("-transparent", True)
        self.root.configure(bg=BG)
        self.voice = Voice(self.root)

        self.frame = frame = tk.Frame(self.root, bg=BG)
        frame.pack(fill="both", expand=True)
        self.left = left = tk.Frame(frame, bg=BG)
        left.pack(side="left", fill="y")
        self.avatar = Avatar(left, TICK_MS)
        self.avatar.label_img.pack()
        self.avatar.tick()

        right = tk.Frame(frame, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        top = tk.Frame(right, bg=BG)
        top.pack(fill="x")
        tk.Label(top, text="MO WUJI", bg=BG, fg=GOLD, font=self.font(12, "title"), pady=0).pack(side="left")
        self.button(top, "×", self.root.destroy, kind="close").pack(side="right")
        self.progress = self.link(top, "", self.open_cultivation, fg=DIM, font=self.font(12))
        self.progress.configure(pady=0)
        self.progress.pack(side="right", padx=(0, self.px(SM)))

        self.views = {name: tk.Frame(right, bg=BG) for name in ("quote", "setup", "session")}
        self.build_quote_view(self.views["quote"])
        self.build_setup_view(self.views["setup"])
        self.build_session_view(self.views["session"])
        self.grip = tk.Canvas(self.root, bg=BG, highlightthickness=0, cursor="bottom_right_corner")
        self.actions[self.grip] = self.begin_resize
        self.root.bind_all("<Enter>", self.watch_pointer, add="+")
        self.apply_scale(self.state.get("scale", 1.0), place=False)

        self.next_quote()
        self.refresh_progress()
        self.show_view("quote", resize=False)
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        h = self.root.winfo_reqheight()
        w = self.px(WIDTH)
        x, y = self.state.get("pos", (sw - w - 24, sh - h - 110))
        if not (0 <= x <= sw - 60 and 0 <= y <= sh - 60):
            x, y = sw - w - 24, sh - h - 110
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.win = pin_to_desktop()
        make_glass(self.win, w, h)
        self.avatar.output = SceneLayer(self.win, self.avatar).show
        self.avatar.tick()

        active = self.state.get("active")
        if active and time.time() >= active["end"]:
            self.enter_session()
            self.complete_session()
        elif active:
            self.enter_session()
        self.root.after(REFRESH_MS, self.auto_quote)
        self.animate()

    # ---------- size ----------
    def px(self, value: float) -> int:
        return round(value * self.scale)

    def font(self, size: int, style: str = "body") -> tkfont.Font:
        """Named fonts, so a size change updates every label that uses them.
        title = Lora SemiBold, body = Lora Medium, quote = Lora Medium Italic."""
        if (size, style) not in self.fonts:
            self.fonts[(size, style)] = tkfont.Font(family=FONT, size=self.px(size),
                                                    weight="bold" if style == "title" else "normal",
                                                    slant="italic" if style == "quote" else "roman")
        return self.fonts[(size, style)]

    def apply_scale(self, scale: float, place: bool = True) -> None:
        self.scale = scale
        for (size, _), f in self.fonts.items():
            f.configure(size=max(min(size, 11), self.px(size)))   # labels stay readable at 80%
        self.refit(self.root)
        self.frame.configure(padx=self.px(PAD), pady=self.px(PAD))
        self.left.pack_configure(padx=(0, self.px(PAD)))
        for c in self.buttons:
            self.draw_button(c)
        for label in (self.quote, self.chronicle_text):
            label.configure(wraplength=self.px(TEXT_W - 4))   # italic overhang stays inside the column
        for widget, opts in self.spaced:
            if widget.winfo_manager() == "pack":
                widget.pack_configure(**self.scaled(opts))
        self.chart.configure(width=self.px(TEXT_W), height=self.px(50))
        self.bar.configure(width=self.px(TEXT_W), height=max(3, self.px(4)))
        if self.state.get("active") is None:
            self.draw_bar(0)
        self.avatar.set_display(scale)
        g = self.px(14)
        self.grip.configure(width=g, height=g)
        self.grip.delete("all")
        for i in (0.3, 0.6, 0.9):
            self.grip.create_line(g, g - g * i, g - g * i, g, fill=BAR_DIM, width=max(1, self.px(1)))
        self.grip.place(relx=1, rely=1, x=-self.px(4), y=-self.px(4), anchor="se")
        self.root.tk.call("raise", self.grip._w)  # Canvas.lift raises canvas items, not the widget
        if self.views["setup"].winfo_ismapped():
            self.refresh_setup()
        if not place:
            return
        # resizing from the bottom-right grip keeps the top-left corner still
        x, y = self.root.winfo_x(), self.root.winfo_y()
        self.root.update_idletasks()
        self.root.geometry(f"{self.px(WIDTH)}x{self.root.winfo_reqheight()}+{x}+{y}")
        active = self.state.get("active")
        if active and self.views["session"].winfo_ismapped():
            self.draw_bar(min(1, (time.time() - active["start"]) / (active["end"] - active["start"])))

    def refit(self, widget: tk.Widget) -> None:
        """Tk keeps a label's old size when its named font changes; setting the font again re-measures it."""
        if isinstance(widget, (tk.Label, tk.Entry)):
            widget.configure(font=widget.cget("font"))
        for child in widget.winfo_children():
            self.refit(child)

    def begin_resize(self) -> None:
        self.resizing = (self.root.winfo_pointerxy()[0], self.scale)
        self.dragging = True
        self.follow_resize()

    def follow_resize(self) -> None:
        if not mouse_down():
            self.dragging, self.resizing = False, None
            self.state["scale"] = self.scale
            save_state(self.state)
            return
        start_x, start_scale = self.resizing
        width = WIDTH * start_scale + self.root.winfo_pointerxy()[0] - start_x
        scale = round(min(SCALES[1], max(SCALES[0], round(width / WIDTH / 0.05) * 0.05)), 2)
        if abs(scale - self.scale) > 1e-6:
            self.apply_scale(scale)
        self.root.after(16, self.follow_resize)

    # ---------- building ----------
    def link(self, parent: tk.Widget, text: str, command, fg: str = GOLD, font: tkfont.Font | None = None) -> tk.Label:
        label = tk.Label(parent, text=text, bg=BG, fg=fg, font=font or self.font(13), cursor="hand2")
        self.actions[label] = command
        return label

    def text(self, parent: tk.Widget, text: str = "", fg: str = DIM, size: int = 13, style: str = "body",
             **kw) -> tk.Label:
        return tk.Label(parent, text=text, bg=BG, fg=fg, font=self.font(size, style), **kw)

    def spaced_pack(self, widget: tk.Widget, **opts) -> None:
        """pack() with padding given in spacing units, kept in proportion when the card is resized."""
        self.spaced.append((widget, opts))
        widget.pack(**self.scaled(opts))

    def scaled(self, opts: dict) -> dict:
        def one(v):
            return tuple(self.px(x) for x in v) if isinstance(v, tuple) else self.px(v)
        return {k: one(v) if k in ("padx", "pady") else v for k, v in opts.items()}

    def button(self, parent: tk.Widget, text: str, command, kind: str = "secondary", square: bool = False) -> tk.Canvas:
        """A rounded button with a 28pt hit area. kind: primary (gold fill), secondary (outline) or ghost."""
        c = tk.Canvas(parent, bg=BG, highlightthickness=0, cursor="hand2")
        self.buttons[c] = [text, kind, square]
        self.actions[c] = command
        self.draw_button(c)
        return c

    def set_kind(self, c: tk.Canvas, kind: str) -> None:
        self.buttons[c][1] = kind
        self.draw_button(c)

    def draw_button(self, c: tk.Canvas) -> None:
        text, kind, square = self.buttons[c]
        if kind == "close":   # sits in the header line, its glyph flush with the column's right edge
            f = self.font(16)
            h, w = self.font(12).metrics("linespace"), self.px(24)
            c.configure(width=w, height=h)
            c.delete("all")
            c.create_text(w, h / 2, text=text, font=f, fill=DIM, anchor="e")
            return
        f = self.font(16, "body") if square else self.font(13, "body")
        h = max(24, self.px(28))
        w = h if square else f.measure(text) + 2 * self.px(10)
        c.configure(width=w, height=h)
        c.delete("all")
        if kind != "ghost":
            r, x1, y1, x2, y2 = self.px(7), 1, 1, w - 1, h - 1
            pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
                   x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
            c.create_polygon(pts, smooth=True, fill=GOLD if kind == "primary" else "",
                             outline=GOLD if kind == "primary" else BAR_DIM)
        c.create_text(w / 2, h / 2 - (1 if square else 0), text=text, font=f,
                      fill=INK if kind == "primary" else (DIM if kind == "ghost" else FG))

    def build_quote_view(self, v: tk.Frame) -> None:
        self.quote = tk.Label(v, bg=BG, fg=FG, font=self.font(16, "quote"), justify="left", anchor="w", pady=0)
        self.spaced_pack(self.quote, fill="x", pady=(SM, MD))
        bottom = tk.Frame(v, bg=BG)
        bottom.pack(fill="x", side="bottom")
        self.theme = self.text(bottom, style="quote", anchor="w")
        self.theme.pack(side="left")
        self.button(bottom, "Cultivate", self.open_cultivation, kind="primary").pack(side="right")
        self.button(bottom, "Next", self.next_quote).pack(side="right", padx=(0, 8))

    def build_setup_view(self, v: tk.Frame) -> None:
        self.text(v, "Closed-door cultivation", fg=FG, size=16, style="quote", anchor="w").pack(fill="x", pady=(6, 6))

        row = tk.Frame(v, bg=BG)
        row.pack(fill="x", pady=2)
        self.text(row, "Session", width=9, anchor="w").pack(side="left")
        self.chips = {}
        for minutes in DURATIONS:
            chip = self.button(row, str(minutes), lambda m=minutes: self.set_minutes(m))
            chip.pack(side="left", padx=(0, 6))
            self.chips[minutes] = chip
        self.text(row, "min").pack(side="left", padx=(2, 0))

        row = tk.Frame(v, bg=BG)
        row.pack(fill="x", pady=2)
        self.text(row, "Daily goal", width=9, anchor="w").pack(side="left")
        self.button(row, "\u2212", lambda: self.change_goal(-1), square=True).pack(side="left")
        self.goal_label = tk.Label(row, bg=BG, fg=FG, font=self.font(13, "title"), width=3)
        self.goal_label.pack(side="left")
        self.button(row, "+", lambda: self.change_goal(1), square=True).pack(side="left")
        self.text(row, "a day").pack(side="left", padx=(8, 0))

        row = tk.Frame(v, bg=BG)
        row.pack(fill="x", pady=(4, 2))
        self.text(row, "Intention", width=9, anchor="w").pack(side="left")
        self.intention = tk.Entry(row, bg=FIELD_BG, fg=FG, insertbackground=FG, relief="flat", highlightthickness=1,
                                  highlightbackground=BAR_DIM, highlightcolor=GOLD, font=self.font(13))
        self.intention.pack(side="left", fill="x", expand=True, ipady=3)
        self.intention.bind("<Return>", lambda e: self.begin_session())
        self.actions[self.intention] = self.focus_intention

        self.chart = tk.Canvas(v, bg=BG, highlightthickness=0)
        self.chart.pack(anchor="w", pady=(8, 2))
        self.stats = self.text(v, anchor="w", justify="left")
        self.stats.pack(fill="x")
        self.chronicle_text = self.text(v, style="quote", anchor="w", justify="left")

        bottom = tk.Frame(v, bg=BG)
        bottom.pack(fill="x", side="bottom", pady=(8, 0))
        self.button(bottom, "Back", lambda: self.show_view("quote")).pack(side="left")
        self.button(bottom, "Begin", self.begin_session, kind="primary").pack(side="right")

    def build_session_view(self, v: tk.Frame) -> None:
        self.session_title = self.text(v, anchor="w", pady=0)
        self.spaced_pack(self.session_title, fill="x", pady=(XS, 0))
        self.timer = tk.Label(v, bg=BG, fg=FG, font=self.font(34, "title"), anchor="w", pady=0)
        self.timer.pack(fill="x")
        self.bar = tk.Canvas(v, bg=BG, highlightthickness=0)
        self.spaced_pack(self.bar, anchor="w", pady=(XS, SM))
        self.debrief = self.text(v, fg=FG, style="quote", anchor="w", justify="left", pady=0)

        bottom = tk.Frame(v, bg=BG)
        bottom.pack(fill="x", side="bottom")
        self.session_actions = tk.Frame(bottom, bg=BG)
        self.session_actions.pack(side="right", anchor="se")
        info = tk.Frame(bottom, bg=BG)
        info.pack(side="left", fill="x", expand=True, anchor="sw")
        self.session_note = self.text(info, anchor="w", justify="left", pady=0)
        self.session_aim = self.text(info, fg=FG, anchor="w", justify="left", pady=0)
        self.confirm_text = self.text(info, "End it now? It won't count.", anchor="w", justify="left", pady=0)

        self.end_link = self.button(self.session_actions, "End session", self.ask_end)
        self.confirm = tk.Frame(self.session_actions, bg=BG)
        self.button(self.confirm, "Keep going", self.keep_going, kind="primary").pack(side="left")
        self.button(self.confirm, "End", self.end_early).pack(side="left", padx=(self.px(6), 0))
        self.continue_link = self.button(self.session_actions, "Continue", self.leave_session, kind="primary")

    def show_session_parts(self, info: tuple, action: tk.Widget, message: str = "") -> None:
        """Bottom row: detail lines on the left, one action group on the right. An optional message
        (Mo Wuji's debrief) gets the full width above that row."""
        for w in (self.session_note, self.session_aim, self.confirm_text, self.end_link, self.confirm,
                  self.continue_link, self.debrief):
            w.pack_forget()
        action.pack(side="right")
        self.root.update_idletasks()
        room = self.px(TEXT_W) - action.winfo_reqwidth() - self.px(SM)
        for w in info:
            w.configure(wraplength=room)
            w.pack(fill="x")
        if message:
            self.debrief.configure(text=message, wraplength=self.px(TEXT_W))
            self.spaced_pack(self.debrief, fill="x", pady=(0, MD))
        self.resize()

    def fit_line(self, text: str, font: tkfont.Font, width: int) -> str:
        """Shortens text with an ellipsis so it stays on one line."""
        if font.measure(text) <= width:
            return text
        while text and font.measure(text + "…") > width:
            text = text[:-1]
        return text.rstrip() + "…"

    # ---------- views ----------
    def show_view(self, name: str, resize: bool = True) -> None:
        for view in self.views.values():
            view.pack_forget()
        self.views[name].pack(fill="both", expand=True)
        if name == "setup":
            self.refresh_setup()
        if resize:
            self.resize()

    def resize(self) -> None:
        """Fits the card to its content, keeping the bottom edge where it was."""
        old_h = self.root.winfo_height()
        self.root.update_idletasks()
        h = self.root.winfo_reqheight()
        y = self.root.winfo_y() + old_h - h if old_h > 1 else self.root.winfo_y()
        self.root.geometry(f"{self.px(WIDTH)}x{h}+{self.root.winfo_x()}+{max(0, y)}")

    def next_quote(self) -> None:
        self.ai_turn = not self.ai_turn
        if self.ai_turn and self.fresh:
            quote, theme, mood = self.fresh["quote"], self.fresh["theme"], self.fresh["mood"]
            self.fresh = None
            self.state["generated"] = (self.state["generated"] + [quote])[-40:]
            save_state(self.state)
        else:
            quote, theme, mood = random.choice([e for e in self.entries if e[0] != self.current] or self.entries)
        self.current = quote
        self.quote.config(text=f"“{quote}”")
        self.theme.config(text=f"— {theme}")
        if "active" not in self.state:
            self.avatar.show(mood)
        self.resize()
        self.fetch_quote()

    def fetch_quote(self) -> None:
        """Prepares the next quote with the AI voice, so it is ready the moment it is needed."""
        if not self.voice.enabled or self.fetching or self.fresh:
            return
        self.fetching = True
        s = summarize(self.state["sessions"], self.state["goal"])
        context = (f"it is {time_of_day(datetime.now().hour)} on a {date.today():%A}; today they have finished "
                   f"{s['today']} of {self.state['goal']} closed-door cultivation sessions; their streak is "
                   f"{plural(s['streak'], 'day')}")
        mood = random.choices(["calm", "battle", "god-like"], weights=[45, 35, 20])[0]

        def done(result: dict | None) -> None:
            self.fetching = False
            self.fresh = result

        examples = random.sample([e[0] for e in self.entries if e[2] == mood], 6)
        self.voice.quote(mood, context, examples, self.state["generated"] + [self.current], done)

    def auto_quote(self) -> None:
        if "active" not in self.state:
            self.next_quote()
        self.root.after(REFRESH_MS, self.auto_quote)

    # ---------- goal and summary ----------
    def set_minutes(self, minutes: int) -> None:
        self.state["minutes"] = minutes
        save_state(self.state)
        self.refresh_setup()

    def change_goal(self, delta: int) -> None:
        self.state["goal"] = min(12, max(1, self.state["goal"] + delta))
        save_state(self.state)
        self.refresh_setup()
        self.refresh_progress()

    def refresh_progress(self) -> None:
        s = summarize(self.state["sessions"], self.state["goal"])
        self.progress.config(text=f"{s['today']} of {self.state['goal']} today",
                             fg=GOLD if s["today"] >= self.state["goal"] else DIM)

    def refresh_setup(self) -> None:
        goal = self.state["goal"]
        for minutes, chip in self.chips.items():
            self.set_kind(chip, "primary" if minutes == self.state["minutes"] else "secondary")
        self.goal_label.config(text=str(goal))
        s = summarize(self.state["sessions"], goal)

        c, w = self.chart, self.px(TEXT_W)
        c.delete("all")
        top, base, col = self.px(4), self.px(34), w / 7
        peak = max([goal] + [n for _, n in s["week"]])
        goal_y = base - (base - top) * goal / peak
        c.create_line(0, goal_y, w, goal_y, fill=DIM, dash=(2, 3))
        for i, (day, n) in enumerate(s["week"]):
            x0 = i * col + col * 0.28
            if n:
                c.create_rectangle(x0, base - (base - top) * n / peak, x0 + col * 0.44, base,
                                   fill=GOLD if n >= goal else BAR_DIM, outline="")
            c.create_text(x0 + col * 0.22, base + self.px(9), text=day.strftime("%a")[0], fill=FG if day == date.today() else DIM,
                          font=self.font(10))

        self.show_chronicle()
        self.stats.config(text=f"Today {s['today']} of {goal} · {s['today_minutes']} min · "
                               f"streak {plural(s['streak'], 'day')}\n"
                               f"All time {plural(s['total'], 'session')} · {s['hours']:.1f} hours")

    def show_chronicle(self) -> None:
        """Mo Wuji's account of the week: this week on Sundays, otherwise last week."""
        today = date.today()
        start = today - timedelta(days=today.weekday())
        if today.weekday() != 6:
            start -= timedelta(days=7)
        week = f"{start.isocalendar().year}-W{start.isocalendar().week:02d}"
        days = [start + timedelta(days=i) for i in range(7)]
        done = [x for x in self.state["sessions"] if date.fromisoformat(x["date"]) in days]
        text = self.state["chronicles"].get(week)
        if text:
            label = "This week" if today.weekday() == 6 else "Last week"
            self.chronicle_text.config(text=f"{label}: {text}")
            self.chronicle_text.pack(fill="x", pady=(4, 0))
            return
        self.chronicle_text.pack_forget()
        if not done or not self.voice.enabled or self.chronicling == week:
            return
        self.chronicling = week
        per_day = Counter(x["date"] for x in done)
        aims = [aim for aim, _ in Counter(x["intention"] for x in done if x.get("intention")).most_common(3)]
        record = [f"{plural(len(done), 'session')} on {plural(len(per_day), 'day')}, "
                  f"{sum(x['minutes'] for x in done) / 60:.1f} hours in total",
                  f"Daily goal of {self.state['goal']} met on {plural(sum(n >= self.state['goal'] for n in per_day.values()), 'day')}"]
        if aims:
            record.append("Worked on: " + ", ".join(aims))

        def store(result: str | None) -> None:
            self.chronicling = None
            if result:
                self.state["chronicles"][week] = result
                save_state(self.state)
                if self.views["setup"].winfo_ismapped():
                    self.show_chronicle()
                    self.resize()

        self.voice.chronicle("\n".join(record), store)

    def focus_intention(self) -> None:
        # desktop-level windows only take keyboard input once the app is active and the window is key
        msg(ns_app(), b"activateIgnoringOtherApps:", 1, argtypes=(ctypes.c_bool,))
        msg(self.win, b"makeKeyWindow")
        self.intention.focus_force()

    # ---------- closed-door cultivation ----------
    def open_cultivation(self) -> None:
        self.show_view("session" if "active" in self.state else "setup")

    def begin_session(self) -> None:
        now = time.time()
        minutes = self.state["minutes"]
        self.state["active"] = {"start": now, "end": now + minutes * 60, "minutes": minutes,
                                "intention": self.intention.get().strip()[:120]}
        self.intention.delete(0, "end")
        save_state(self.state)
        self.enter_session()

    def enter_session(self) -> None:
        s = summarize(self.state["sessions"], self.state["goal"])
        self.session_title.config(text="In closed-door cultivation")
        active = self.state["active"]
        self.session_note.config(text=f"Session {s['today'] + 1} of {self.state['goal']} · {active['minutes']} min")
        self.avatar.show("calm", seated=True)
        self.show_view("session", resize=False)
        self.show_session_parts((self.session_note, self.session_aim), self.end_link)
        room = self.px(TEXT_W) - self.end_link.winfo_reqwidth() - self.px(SM)
        self.session_aim.config(text=self.fit_line(active.get("intention", ""), self.font(13), room))
        self.session_tick()

    def session_tick(self) -> None:
        active = self.state.get("active")
        if not active:
            return
        remaining = active["end"] - time.time()
        if remaining <= 0:
            self.complete_session()
            return
        mins, secs = divmod(int(remaining + 0.999), 60)
        self.timer.config(text=f"{mins // 60}:{mins % 60:02d}:{secs:02d}" if mins >= 60 else f"{mins:02d}:{secs:02d}")
        self.draw_bar(1 - remaining / (active["end"] - active["start"]))
        self.timer_job = self.root.after(1000, self.session_tick)

    def draw_bar(self, fraction: float) -> None:
        w, h = self.px(TEXT_W), max(3, self.px(4))
        self.bar.delete("all")
        self.bar.create_rectangle(0, 0, w, h, fill=BAR_DIM, outline="")
        self.bar.create_rectangle(0, 0, w * fraction, h, fill=GOLD, outline="")

    def complete_session(self) -> None:
        active = self.state.pop("active")
        record = {"date": date.today().isoformat(), "end": datetime.now().isoformat(timespec="seconds"),
                  "minutes": active["minutes"], "intention": active.get("intention", "")}
        self.state["sessions"].append(record)
        save_state(self.state)
        s = summarize(self.state["sessions"], self.state["goal"])
        goal_met = s["today"] == self.state["goal"]
        self.session_title.config(text="Closed-door cultivation complete")
        self.timer.config(text="Breakthrough")
        self.draw_bar(1)
        progress = f"{s['today']} of {self.state['goal']} today" + (" · goal reached" if goal_met else "")
        self.session_note.config(text=progress)

        def show_debrief(text: str | None) -> None:
            if text:
                record["debrief"] = text
                save_state(self.state)
            if self.views["session"].winfo_ismapped() and "active" not in self.state:
                self.show_session_parts((self.session_note,), self.continue_link, f"“{text}”" if text else "")

        self.voice.debrief(active["minutes"], record["intention"], f"They have now finished {s['today']} of "
                           f"{self.state['goal']} sessions today", show_debrief)
        self.show_session_parts((self.session_note,), self.continue_link,
                                "Mo Wuji is reflecting…" if self.voice.enabled else "")
        self.avatar.show("god-like")
        self.refresh_progress()
        notify("Breakthrough", f"{active['minutes']} minutes of closed-door cultivation complete. "
                               f"{s['today']} of {self.state['goal']} today.")

    def ask_end(self) -> None:
        self.show_session_parts((self.confirm_text,), self.confirm)

    def keep_going(self) -> None:
        self.show_session_parts((self.session_note, self.session_aim), self.end_link)

    def end_early(self) -> None:
        self.state.pop("active", None)
        save_state(self.state)
        if self.timer_job:
            self.root.after_cancel(self.timer_job)
        self.leave_session()

    def leave_session(self) -> None:
        self.show_view("quote", resize=False)
        self.next_quote()

    def animate(self) -> None:
        # skip rendering while app windows cover the card
        if is_visible(self.win):
            self.avatar.tick()
            self.root.after(TICK_MS, self.animate)
        else:
            self.root.after(1000, self.animate)

    # ---------- mouse ----------
    # macOS drops most clicks on this card while another app is active, but hover events still arrive.
    # So while the pointer is over the card, the widget reads the mouse button itself and acts on presses.
    def watch_pointer(self, e: tk.Event | None = None) -> None:
        if not self.watching:
            self.watching = True
            self.was_down = mouse_down()
            self.poll_pointer()

    def poll_pointer(self) -> None:
        px, py = self.root.winfo_pointerxy()
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        inside = x <= px < x + self.root.winfo_width() and y <= py < y + self.root.winfo_height()
        down = mouse_down()
        if down and not self.was_down and inside and not self.dragging and card_is_under_pointer(self.win):
            self.press(px, py)
        self.was_down = down
        if inside or self.dragging:
            self.root.after(15, self.poll_pointer)
        else:
            self.watching = False

    def press(self, px: int, py: int) -> None:
        action = self.actions.get(self.root.winfo_containing(px, py))
        if action:
            action()
        else:
            self.dragging = True
            frame = msg(self.win, b"frame", restype=CGRect)
            self.drag_from = (mouse_location(), frame.x, frame.y)
            self.follow()

    def follow(self) -> None:
        """Moves the native window directly; going through Tk re-lays out the whole card on every step."""
        start, ox, oy = self.drag_from
        now = mouse_location()
        x, y = ox + now.x - start.x, oy + now.y - start.y
        msg(self.win, b"setFrameOrigin:", NSPoint(x, y), argtypes=(NSPoint,))
        if mouse_down():
            self.root.after(8, self.follow)
            return
        self.dragging = False
        # tell Tk where the card ended up (Tk measures from the top-left, macOS from the bottom-left)
        top = self.root.winfo_screenheight() - (y + self.root.winfo_height())
        self.root.geometry(f"+{round(x)}+{round(top)}")
        self.state["pos"] = [round(x), round(top)]
        save_state(self.state)


if __name__ == "__main__":
    # Only one copy may run; a second one would stack an identical card on top.
    lock = open(Path.home() / "Library/Caches/mo-wuji-widget.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("mo-wuji-widget is already running")
    QuoteWidget().root.mainloop()
