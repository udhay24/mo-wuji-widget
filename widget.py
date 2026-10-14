import ctypes
import fcntl
import random
import sys
import tkinter as tk
from pathlib import Path

from avatar import Avatar

BASE = Path(__file__).resolve().parent
REFRESH_MS = 30 * 60 * 1000
TICK_MS = 180
WIDTH = 470
TITLE_FONT, QUOTE_FONT = "Cinzel", "Cormorant Garamond"
BG, FG, GOLD, DIM = "systemTransparent", "#f4f0e8", "#e8c47c", "#b4aabe"


objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.dylib")
appkit = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
objc.objc_getClass.restype = ctypes.c_void_p
objc.sel_registerName.restype = ctypes.c_void_p
appkit.CGEventSourceButtonState.restype = ctypes.c_bool
appkit.CGEventSourceButtonState.argtypes = [ctypes.c_int32, ctypes.c_uint32]


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
    msg(msg(content, b"superview"), b"addSubview:positioned:relativeTo:", glass, -1, content,
        argtypes=(ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p))


def is_visible(win: int) -> bool:
    return bool(msg(win, b"occlusionState", restype=ctypes.c_ulong) & 2)


def mouse_down() -> bool:
    return appkit.CGEventSourceButtonState(0, 0)


class QuoteWidget:
    def __init__(self) -> None:
        self.entries = [l.split("|") for l in (BASE / "quotes.txt").read_text().splitlines() if "|" in l]
        self.current = ""
        self.dragging = False

        load_fonts()
        self.root = tk.Tk()
        hide_dock_icon()
        self.root.overrideredirect(True)
        self.root.attributes("-transparent", True)
        self.root.configure(bg=BG)

        frame = tk.Frame(self.root, bg=BG, padx=14, pady=12)
        frame.pack(fill="both", expand=True)

        left = tk.Frame(frame, bg=BG)
        left.pack(side="left", fill="y", padx=(0, 14))
        self.avatar = Avatar(left, TICK_MS)
        self.avatar.label_img.pack()
        self.avatar.tick()

        right = tk.Frame(frame, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        top = tk.Frame(right, bg=BG)
        top.pack(fill="x")
        tk.Label(top, text="MO WUJI", bg=BG, fg=GOLD, font=(TITLE_FONT, 10, "bold")).pack(side="left")
        close = tk.Label(top, text="×", bg=BG, fg=DIM, font=(QUOTE_FONT, 18, "italic"), cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.root.destroy())

        self.quote = tk.Label(right, bg=BG, fg=FG, font=(QUOTE_FONT, 17, "italic"),
                              wraplength=WIDTH - 200, justify="left", anchor="w")
        self.quote.pack(fill="x", pady=(6, 6))
        bottom = tk.Frame(right, bg=BG)
        bottom.pack(fill="x", side="bottom")
        self.theme = tk.Label(bottom, bg=BG, fg=DIM, font=(QUOTE_FONT, 13, "italic"), anchor="w")
        self.theme.pack(side="left")
        nxt = tk.Label(bottom, text="NEXT ›", bg=BG, fg=GOLD, font=(TITLE_FONT, 9, "bold"), cursor="hand2")
        nxt.pack(side="right")
        nxt.bind("<Button-1>", lambda e: self.next_quote())

        for w in (frame, left, right, top, bottom, self.quote, self.theme, self.avatar.label_img):
            w.bind("<ButtonPress-1>", self.start_drag)

        self.next_quote()
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        h = self.root.winfo_reqheight()
        self.root.geometry(f"{WIDTH}x{h}+{sw - WIDTH - 24}+{sh - h - 110}")
        self.win = pin_to_desktop()
        make_glass(self.win, WIDTH, h)
        self.root.after(REFRESH_MS, self.auto_quote)
        self.animate()

    def next_quote(self) -> None:
        quote, theme = random.choice([e for e in self.entries if e[0] != self.current] or self.entries)
        self.current = quote
        self.quote.config(text=f"“{quote}”")
        self.theme.config(text=f"— {theme}")
        self.avatar.next_pose()
        self.root.update_idletasks()
        self.root.geometry(f"{WIDTH}x{self.root.winfo_reqheight()}")

    def auto_quote(self) -> None:
        self.next_quote()
        self.root.after(REFRESH_MS, self.auto_quote)

    def animate(self) -> None:
        # skip rendering while app windows cover the card
        if is_visible(self.win):
            self.avatar.tick()
            self.root.after(TICK_MS, self.animate)
        else:
            self.root.after(1000, self.animate)

    # Mouse-move events get dropped for desktop-level windows, so track the pointer directly.
    def start_drag(self, e: tk.Event) -> None:
        if self.dragging:
            return
        self.dragging = True
        self.dx, self.dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()
        self.follow()

    def follow(self) -> None:
        if not mouse_down():
            self.dragging = False
            return
        px, py = self.root.winfo_pointerxy()
        self.root.geometry(f"+{px - self.dx}+{py - self.dy}")
        self.root.after(8, self.follow)


# Only one copy may run; a second one would stack an identical card on top.
lock = open(Path.home() / "Library/Caches/mo-wuji-widget.lock", "w")
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit("mo-wuji-widget is already running")

QuoteWidget().root.mainloop()
