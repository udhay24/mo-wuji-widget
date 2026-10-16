import ctypes
import fcntl
import json
import random
import subprocess
import sys
import time
import tkinter as tk
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from avatar import Avatar, time_of_day
from voice import Voice

BASE = Path(__file__).resolve().parent
REFRESH_MS = 30 * 60 * 1000
TICK_MS = 180
WIDTH = 470
TITLE_FONT, QUOTE_FONT = "Cinzel", "Cormorant Garamond"
BG, FG, GOLD, DIM = "systemTransparent", "#f4f0e8", "#e8c47c", "#b4aabe"
BAR_DIM = "#6f6680"
FIELD_BG = "#262330"
STATE_FILE = Path.home() / "Library/Application Support/mo-wuji-widget/state.json"
DURATIONS = (25, 50, 90)


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
        self.links: set[tk.Widget] = set()
        self.timer_job: str | None = None
        self.state = load_state()
        self.state.setdefault("goal", 4)
        self.state.setdefault("minutes", 50)
        self.state.setdefault("sessions", [])
        self.state.setdefault("generated", [])
        self.state.setdefault("chronicles", {})
        self.fresh: dict | None = None      # a generated quote waiting to be shown
        self.fetching = False
        self.chronicling: str | None = None

        load_fonts()
        self.root = tk.Tk()
        hide_dock_icon()
        self.root.overrideredirect(True)
        self.root.attributes("-transparent", True)
        self.root.configure(bg=BG)
        self.voice = Voice(self.root)

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
        self.link(top, "×", self.root.destroy, fg=DIM, font=(QUOTE_FONT, 18, "italic")).pack(side="right")
        self.progress = self.link(top, "", self.open_cultivation, fg=DIM, font=(QUOTE_FONT, 13, "italic"))
        self.progress.pack(side="right", padx=(0, 10))

        self.views = {name: tk.Frame(right, bg=BG) for name in ("quote", "setup", "session")}
        self.build_quote_view(self.views["quote"])
        self.build_setup_view(self.views["setup"])
        self.build_session_view(self.views["session"])
        self.bind_drag(self.root)

        self.next_quote()
        self.refresh_progress()
        self.show_view("quote", resize=False)
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        h = self.root.winfo_reqheight()
        x, y = self.state.get("pos", (sw - WIDTH - 24, sh - h - 110))
        if not (0 <= x <= sw - 60 and 0 <= y <= sh - 60):
            x, y = sw - WIDTH - 24, sh - h - 110
        self.root.geometry(f"{WIDTH}x{h}+{x}+{y}")
        self.win = pin_to_desktop()
        make_glass(self.win, WIDTH, h)

        active = self.state.get("active")
        if active and time.time() >= active["end"]:
            self.enter_session()
            self.complete_session()
        elif active:
            self.enter_session()
        self.root.after(REFRESH_MS, self.auto_quote)
        self.animate()

    # ---------- building ----------
    def link(self, parent: tk.Widget, text: str, command, fg: str = GOLD, font: tuple | None = None) -> tk.Label:
        label = tk.Label(parent, text=text, bg=BG, fg=fg, font=font or (TITLE_FONT, 9, "bold"), cursor="hand2")
        label.bind("<Button-1>", lambda e: command())
        self.links.add(label)
        return label

    def text(self, parent: tk.Widget, text: str = "", fg: str = DIM, size: int = 13, **kw) -> tk.Label:
        return tk.Label(parent, text=text, bg=BG, fg=fg, font=(QUOTE_FONT, size, "italic"), **kw)

    def bind_drag(self, widget: tk.Widget) -> None:
        if widget not in self.links and widget is not self.root:
            widget.bind("<ButtonPress-1>", self.start_drag)
        for child in widget.winfo_children():
            self.bind_drag(child)

    def build_quote_view(self, v: tk.Frame) -> None:
        self.quote = tk.Label(v, bg=BG, fg=FG, font=(QUOTE_FONT, 17, "italic"),
                              wraplength=WIDTH - 200, justify="left", anchor="w")
        self.quote.pack(fill="x", pady=(6, 6))
        bottom = tk.Frame(v, bg=BG)
        bottom.pack(fill="x", side="bottom")
        self.theme = self.text(bottom, anchor="w")
        self.theme.pack(side="left")
        self.link(bottom, "NEXT ›", self.next_quote).pack(side="right")
        self.link(bottom, "CULTIVATE", self.open_cultivation, fg=DIM).pack(side="right", padx=(0, 14))

    def build_setup_view(self, v: tk.Frame) -> None:
        self.text(v, "Closed-door cultivation", fg=FG, size=17, anchor="w").pack(fill="x", pady=(6, 4))

        row = tk.Frame(v, bg=BG)
        row.pack(fill="x", pady=1)
        self.text(row, "Session", width=9, anchor="w").pack(side="left")
        self.chips = {}
        for minutes in DURATIONS:
            chip = self.link(row, f"{minutes} MIN", lambda m=minutes: self.set_minutes(m))
            chip.pack(side="left", padx=(0, 12))
            self.chips[minutes] = chip

        row = tk.Frame(v, bg=BG)
        row.pack(fill="x", pady=1)
        self.text(row, "Daily goal", width=9, anchor="w").pack(side="left")
        self.link(row, "−", lambda: self.change_goal(-1), fg=GOLD, font=(TITLE_FONT, 12, "bold")).pack(side="left")
        self.goal_label = tk.Label(row, bg=BG, fg=FG, font=(TITLE_FONT, 11, "bold"), width=3)
        self.goal_label.pack(side="left")
        self.link(row, "+", lambda: self.change_goal(1), fg=GOLD, font=(TITLE_FONT, 12, "bold")).pack(side="left")
        self.text(row, "sessions a day").pack(side="left", padx=(8, 0))

        row = tk.Frame(v, bg=BG)
        row.pack(fill="x", pady=(4, 1))
        self.text(row, "Intention", width=9, anchor="w").pack(side="left")
        self.intention = tk.Entry(row, bg=FIELD_BG, fg=FG, insertbackground=FG, relief="flat", highlightthickness=1,
                                  highlightbackground=BAR_DIM, highlightcolor=GOLD, font=(QUOTE_FONT, 14, "italic"))
        self.intention.pack(side="left", fill="x", expand=True, ipady=2)
        self.intention.bind("<Button-1>", self.focus_intention)
        self.intention.bind("<Return>", lambda e: self.begin_session())
        self.links.add(self.intention)

        self.chart = tk.Canvas(v, width=WIDTH - 200, height=50, bg=BG, highlightthickness=0)
        self.chart.pack(anchor="w", pady=(8, 2))
        self.stats = self.text(v, anchor="w", justify="left")
        self.stats.pack(fill="x")
        self.chronicle_text = self.text(v, anchor="w", justify="left", wraplength=WIDTH - 200)

        bottom = tk.Frame(v, bg=BG)
        bottom.pack(fill="x", side="bottom", pady=(6, 0))
        self.link(bottom, "BACK", lambda: self.show_view("quote"), fg=DIM).pack(side="left")
        self.link(bottom, "BEGIN ›", self.begin_session).pack(side="right")

    def build_session_view(self, v: tk.Frame) -> None:
        self.session_title = self.text(v, anchor="w")
        self.session_title.pack(fill="x", pady=(6, 0))
        self.timer = tk.Label(v, bg=BG, fg=FG, font=(TITLE_FONT, 30, "bold"), anchor="w")
        self.timer.pack(fill="x")
        self.bar = tk.Canvas(v, width=WIDTH - 200, height=4, bg=BG, highlightthickness=0)
        self.bar.pack(anchor="w", pady=(2, 6))
        self.session_note = self.text(v, anchor="w", justify="left", wraplength=WIDTH - 200)
        self.session_note.pack(fill="x")

        bottom = tk.Frame(v, bg=BG)
        bottom.pack(fill="x", side="bottom", pady=(6, 0))
        self.end_link = self.link(bottom, "END EARLY", self.ask_end, fg=DIM)
        self.confirm = tk.Frame(bottom, bg=BG)
        self.text(self.confirm, "End without counting it?").pack(side="left")
        self.link(self.confirm, "END", self.end_early, fg=DIM).pack(side="left", padx=(10, 0))
        self.link(self.confirm, "KEEP GOING", self.keep_going).pack(side="left", padx=(12, 0))
        self.continue_link = self.link(bottom, "CONTINUE ›", self.leave_session)

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
        self.root.geometry(f"{WIDTH}x{h}+{self.root.winfo_x()}+{max(0, y)}")

    def next_quote(self) -> None:
        if self.fresh:
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
            chip.config(fg=GOLD if minutes == self.state["minutes"] else BAR_DIM)
        self.goal_label.config(text=str(goal))
        s = summarize(self.state["sessions"], goal)

        c, w = self.chart, WIDTH - 200
        c.delete("all")
        top, base, col = 4, 34, w / 7
        peak = max([goal] + [n for _, n in s["week"]])
        goal_y = base - (base - top) * goal / peak
        c.create_line(0, goal_y, w, goal_y, fill=BAR_DIM, dash=(2, 3))
        for i, (day, n) in enumerate(s["week"]):
            x0 = i * col + col * 0.28
            if n:
                c.create_rectangle(x0, base - (base - top) * n / peak, x0 + col * 0.44, base,
                                   fill=GOLD if n >= goal else BAR_DIM, outline="")
            c.create_text(x0 + col * 0.22, base + 9, text=day.strftime("%a")[0], fill=FG if day == date.today() else DIM,
                          font=(QUOTE_FONT, 11, "italic"))

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

    def focus_intention(self, e: tk.Event) -> None:
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
        self.end_link.pack(side="left")
        self.confirm.pack_forget()
        self.continue_link.pack_forget()
        s = summarize(self.state["sessions"], self.state["goal"])
        self.session_title.config(text="In closed-door cultivation")
        active = self.state["active"]
        note = f"Session {s['today'] + 1} of {self.state['goal']} today · {active['minutes']} min"
        self.session_note.config(text=note + (f"\n{active['intention']}" if active.get("intention") else ""))
        self.avatar.show("calm", seated=True)
        self.show_view("session")
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
        w = WIDTH - 200
        self.bar.delete("all")
        self.bar.create_rectangle(0, 1, w, 3, fill=BAR_DIM, outline="")
        self.bar.create_rectangle(0, 1, w * fraction, 3, fill=GOLD, outline="")

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
        progress = f"{s['today']} of {self.state['goal']} today" + (" · daily goal reached" if goal_met else "")
        self.session_note.config(text=progress + ("\nMo Wuji is reflecting…" if self.voice.enabled else ""))

        def show_debrief(text: str | None) -> None:
            if text:
                record["debrief"] = text
                save_state(self.state)
            if self.views["session"].winfo_ismapped() and "active" not in self.state:
                self.session_note.config(text=progress + (f"\n“{text}”" if text else ""))
                self.resize()

        self.voice.debrief(active["minutes"], record["intention"], f"They have now finished {s['today']} of "
                           f"{self.state['goal']} sessions today", show_debrief)
        self.end_link.pack_forget()
        self.confirm.pack_forget()
        self.continue_link.pack(side="right")
        self.avatar.show("god-like")
        self.refresh_progress()
        self.resize()
        notify("Breakthrough", f"{active['minutes']} minutes of closed-door cultivation complete. "
                               f"{s['today']} of {self.state['goal']} today.")

    def ask_end(self) -> None:
        self.end_link.pack_forget()
        self.confirm.pack(side="left")

    def keep_going(self) -> None:
        self.confirm.pack_forget()
        self.end_link.pack(side="left")

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
            self.state["pos"] = [self.root.winfo_x(), self.root.winfo_y()]
            save_state(self.state)
            return
        px, py = self.root.winfo_pointerxy()
        self.root.geometry(f"+{px - self.dx}+{py - self.dy}")
        self.root.after(8, self.follow)


if __name__ == "__main__":
    # Only one copy may run; a second one would stack an identical card on top.
    lock = open(Path.home() / "Library/Caches/mo-wuji-widget.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("mo-wuji-widget is already running")
    QuoteWidget().root.mainloop()
