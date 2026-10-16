"""Optional OpenRouter voice for Mo Wuji. Without a key, or offline, the widget uses its built-in text."""
import json
import queue
import re
import subprocess
import threading
import tkinter as tk
import urllib.error
import urllib.request
from typing import Callable

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "mistralai/mistral-nemo"  # cheapest capable text model on OpenRouter
KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT = "mo-wuji-widget", "openrouter"

PERSONA = (
    "You are Mo Wuji, protagonist of the cultivation novel Immortal Mortal. You were born on Earth and reborn "
    "into a cultivation world with no spiritual roots and broken meridians, became an alchemist, and forged your "
    "own Dao through relentless will. You speak with calm, fierce conviction, using cultivation imagery: the Dao, "
    "realms, tribulation, meridians, pills, the heavens. You never mention being an AI. No emojis, no hashtags."
)


def api_key() -> str | None:
    result = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
                            capture_output=True, text=True)
    return result.stdout.strip() or None if result.returncode == 0 else None


def complete(key: str, messages: list[dict], max_tokens: int, model: str = MODEL, **extra) -> dict:
    body = json.dumps({"model": model, "messages": messages, "max_tokens": max_tokens, **extra}).encode()
    request = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/udhay24/mo-wuji-widget",
        "X-Title": "Mo Wuji Widget",
    })
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read())


def parse_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def acceptable(line: str) -> bool:
    """Small models slip; reject run-together words, numbers and app mechanics rather than show them."""
    return (12 < len(line) < 180 and not re.search(r"[a-z][A-Z]|\d", line)
            and not re.search(r"\b(streak|session|goal|widget|AI)\b", line, re.I))


class Voice:
    """Runs requests on a worker thread and hands results back on the Tk thread."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.key = api_key()
        self.results: queue.Queue = queue.Queue()
        self.root.after(300, self.deliver)

    @property
    def enabled(self) -> bool:
        return self.key is not None

    def ask(self, prompt: str, on_done: Callable[[str | None], None], max_tokens: int = 160) -> None:
        if not self.enabled:
            on_done(None)
            return
        messages = [{"role": "system", "content": PERSONA}, {"role": "user", "content": prompt}]

        def work() -> None:
            try:
                text = complete(self.key, messages, max_tokens, temperature=0.9)["choices"][0]["message"]["content"]
                self.results.put((on_done, text.strip()))
            except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError):
                self.results.put((on_done, None))

        threading.Thread(target=work, daemon=True).start()

    def deliver(self) -> None:
        while not self.results.empty():
            on_done, text = self.results.get()
            on_done(text)
        self.root.after(300, self.deliver)

    # ---------- features ----------
    def quote(self, mood: str, context: str, examples: list[str], recent: list[str],
              on_done: Callable[[dict | None], None]) -> None:
        tone = {"calm": "calm and steady", "battle": "fierce and defiant", "god-like": "transcendent and vast"}[mood]
        samples = "\n".join(f"- {q}" for q in examples)
        avoid = "\n".join(f"- {q}" for q in recent[-12:]) or "- (none yet)"
        prompt = (
            f"Write one new motivational line in your voice. Tone: {tone}.\n"
            f"Match the style of these lines: short, plain words, one vivid image, a strong ending.\n{samples}\n"
            f"About the reader, for subtle flavour only: {context}. Never state days, times or numbers.\n"
            f"Under 25 words. It must not repeat or echo any of these:\n{avoid}\n"
            'Reply with JSON only: {"quote": "...", "theme": "On <one or two plain words>"}'
        )

        def done(text: str | None) -> None:
            data = parse_json(text) if text else None
            line = str(data.get("quote", "")).strip().strip('"“”') if data else ""
            if not acceptable(line):
                on_done(None)  # the widget falls back to a built-in quote
                return
            theme = str(data.get("theme") or "the path").strip()
            theme = theme[3:] if theme.lower().startswith("on ") else theme
            on_done({"quote": line, "theme": f"On {theme[:1].lower()}{theme[1:]}", "mood": mood})

        self.ask(prompt, done, max_tokens=120)

    def debrief(self, minutes: int, intention: str, progress: str, on_done: Callable[[str | None], None]) -> None:
        work = f'They were working on: "{intention}".' if intention else "They did not say what they worked on."
        prompt = (f"The reader just finished {minutes} minutes of closed-door cultivation (deep focused work). {work} "
                  f"{progress}. Speak to them as Mo Wuji, using 'you', in at most two short sentences under 35 "
                  "words: honour that specific work through a cultivation image, then urge them on. "
                  "Do not start with 'Well done'. Plain text only, no quotation marks.")
        self.ask(prompt, lambda text: on_done(text.strip('"“”') if text else None), max_tokens=90)

    def chronicle(self, week: str, on_done: Callable[[str | None], None]) -> None:
        prompt = ("As a xianxia narrator, write a short chronicle of the reader's week of cultivation, calling them "
                  "'the cultivator'. Exactly three short sentences, under 60 words in total, flowing prose, no lists, "
                  f"at most one number. Mention what they worked on as quests or battles. The week:\n{week}")

        def done(text: str | None) -> None:
            if text:
                sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
                text = " ".join(sentences[:3])
            on_done(text)

        self.ask(prompt, done, max_tokens=110)
