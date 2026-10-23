// Variables used by Scriptable.
// These must be at the very top of the file. Do not edit.
// icon-color: deep-gray; icon-glyph: yin-yang;

// Mo Wuji for iPhone: home-screen and lock-screen widgets for the Scriptable app.
// Quotes and paintings come from the public repo and are cached, so the widget also works offline.
// Optional: AI quotes through OpenRouter (the key stays in the iOS Keychain), and cultivation
// progress shared by the Mac widget through Scriptable's iCloud folder.

const REPO = "https://raw.githubusercontent.com/udhay24/mo-wuji-widget/main"
const SLOT_MINUTES = 30                      // a new quote every half hour, like the Mac widget
const KEY_NAME = "mo-wuji-openrouter"
const MODELS = ["nvidia/nemotron-3.5-super-vl:free", "mistralai/mistral-nemo"]
const PROGRESS_FILE = "mo-wuji-progress.json"   // written by the Mac widget
const INK = new Color("#111820"), FG = new Color("#f7f4ee"), DIM = new Color("#d6dbe2"), GOLD = new Color("#e8c47c")

const SCENES = [
  ["dawn meditation", "calm", ["dawn"]],
  ["moonlit bamboo", "calm", ["night"]],
  ["wanderer in the mist", "calm", ["dawn", "day"]],
  ["blossom meditation", "calm", ["dawn", "dusk"]],
  ["snow peak stillness", "calm", ["day"]],
  ["lotus lake", "calm", ["dusk", "night"]],
  ["facing the heavens", "calm", ["night"]],
  ["bamboo duel", "battle", ["dawn", "day"]],
  ["ten thousand swords", "battle", ["dusk", "night"]],
  ["blood moon", "battle", ["night"]],
  ["burning battlefield", "battle", ["day", "dusk"]],
  ["facing the beast", "battle", ["dusk", "night"]],
  ["lightning tribulation", "battle", ["day", "night"]],
  ["ascension", "god-like", ["dawn", "day"]],
  ["lord of the stars", "god-like", ["night"]],
  ["heaven's gate", "god-like", ["day", "dusk"]],
]
const FALLBACK_QUOTES = [   // only used offline before the first download
  { text: "When there is no road, I become the road.", theme: "On forging a path", mood: "calm" },
  { text: "Fate wrote my ending. I burned the book and wrote my own.", theme: "On destiny", mood: "battle" },
  { text: "I am the variable the heavens did not calculate.", theme: "On being underestimated", mood: "god-like" },
]
const IMAGES = ["a river", "a mountain", "a sword", "fire", "the stars", "a pill furnace", "lightning", "a seed",
  "the sea", "a blade being forged", "dawn", "a storm", "a gate", "roots", "the moon", "an ancient tree", "snow", "a path"]
const PERSONA = "You are Mo Wuji, protagonist of the cultivation novel Immortal Mortal. You were born on Earth and " +
  "reborn into a cultivation world with no spiritual roots and broken meridians, became an alchemist, and forged " +
  "your own Dao through relentless will. You speak with calm, fierce conviction, using cultivation imagery: the " +
  "Dao, realms, tribulation, meridians, pills, the heavens. You never mention being an AI. No emojis, no hashtags."

const fm = FileManager.local()
const dir = fm.joinPath(fm.documentsDirectory(), "mo-wuji")
if (!fm.fileExists(dir)) fm.createDirectory(dir, true)
const statePath = fm.joinPath(dir, "state.json")

// ---------- helpers ----------
function seeded(seed) {   // small deterministic generator, so every widget shows the same pick for a slot
  let a = seed >>> 0
  return () => {
    a = (a + 0x6D2B79F5) >>> 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
const choice = (rnd, list) => list[Math.floor(rnd() * list.length)]

function weightedMood(rnd) {
  const r = rnd() * 100
  return r < 45 ? "calm" : r < 80 ? "battle" : "god-like"
}

function timeOfDay(hour) {
  if (hour >= 5 && hour < 9) return "dawn"
  if (hour >= 9 && hour < 17) return "day"
  if (hour >= 17 && hour < 20) return "dusk"
  return "night"
}

function isoDay(d) {
  const z = n => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`
}

function readJSON(path) {
  try { return JSON.parse(fm.readString(path)) } catch (e) { return null }
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`

// ---------- content ----------
async function loadQuotes() {
  const path = fm.joinPath(dir, "quotes.txt")
  const stale = !fm.fileExists(path) || Date.now() - fm.modificationDate(path).getTime() > 24 * 3600 * 1000
  if (stale) {
    try {
      const req = new Request(`${REPO}/quotes.txt`)
      req.timeoutInterval = 10
      const text = await req.loadString()
      if (req.response.statusCode === 200 && text.includes("|")) fm.writeString(path, text)
    } catch (e) { /* keep the cached copy */ }
  }
  if (!fm.fileExists(path)) return FALLBACK_QUOTES
  const quotes = fm.readString(path).split("\n").map(l => l.split("|")).filter(p => p.length === 3)
    .map(([text, theme, mood]) => ({ text, theme, mood }))
  return quotes.length ? quotes : FALLBACK_QUOTES
}

async function loadArt(name) {
  const slug = name.replace(/'/g, "").replace(/ /g, "-")
  const path = fm.joinPath(dir, `${slug}.jpg`)
  if (fm.fileExists(path)) return fm.readImage(path)
  try {
    const req = new Request(`${REPO}/art/${encodeURIComponent(slug)}.jpg`)
    req.timeoutInterval = 15
    const image = await req.loadImage()
    if (req.response.statusCode !== 200) return null
    fm.writeImage(path, image)
    return image
  } catch (e) {
    return null
  }
}

async function readProgress() {
  try {
    const cloud = FileManager.iCloud()
    const path = cloud.joinPath(cloud.documentsDirectory(), PROGRESS_FILE)
    if (!cloud.fileExists(path)) return null
    await cloud.downloadFileFromiCloud(path)
    return JSON.parse(cloud.readString(path))
  } catch (e) {
    return null   // iCloud off, or the Mac widget has not shared anything yet
  }
}

function summarize(progress) {
  if (!progress || !progress.days) return null
  const days = progress.days, goal = progress.goal || 4
  const today = new Date()
  const count = d => days[isoDay(d)] || 0
  // a streak counts days that met the goal; today only joins once it is met
  const day = new Date(today)
  if (count(day) < goal) day.setDate(day.getDate() - 1)
  let streak = 0
  while (count(day) >= goal) { streak++; day.setDate(day.getDate() - 1) }
  return { today: count(today), goal, streak, sessions: progress.sessions || 0, hours: progress.hours || 0 }
}

function sceneFor(mood, rnd) {
  const now = timeOfDay(new Date().getHours())
  const ofMood = SCENES.filter(s => s[1] === mood)
  const fitting = ofMood.filter(s => s[2].includes(now))
  return choice(rnd, fitting.length ? fitting : ofMood)[0]
}

// ---------- AI voice (optional) ----------
function acceptable(line) {   // small models slip; reject run-together words, numbers and app mechanics
  return line.length > 12 && line.length < 180 && !/[a-z][A-Z]|\d/.test(line) &&
    !/\b(streak|session|goal|widget|AI)\b/i.test(line)
}

async function aiQuote(key, quotes, recent, context) {
  const mood = weightedMood(Math.random)
  const tone = { calm: "calm and steady", battle: "fierce and defiant", "god-like": "transcendent and vast" }[mood]
  const pool = quotes.filter(q => q.mood === mood).sort(() => Math.random() - 0.5).slice(0, 6)
  const avoid = recent.slice(-12).map(q => `- ${q}`).join("\n") || "- (none yet)"
  const prompt =
    `Write one new motivational line in your voice. Tone: ${tone}.\n` +
    `Build it around this image: ${choice(Math.random, IMAGES)}.\n` +
    "Match the style of these lines: short, plain words, one vivid image, a strong ending.\n" +
    pool.map(q => `- ${q.text}`).join("\n") + "\n" +
    `About the reader, for subtle flavour only: ${context}. Never state days, times or numbers.\n` +
    "It must make plain, literal sense read aloud: every 'it', 'them' or 'this' clearly points to " +
    "something named in the line, and the ending follows from the image.\n" +
    `Under 25 words. It must not repeat or echo any of these:\n${avoid}\n` +
    'Reply with JSON only: {"quote": "...", "theme": "On <one or two plain words>"}'
  const req = new Request("https://openrouter.ai/api/v1/chat/completions")
  req.method = "POST"
  req.timeoutInterval = 15
  req.headers = {
    "Authorization": `Bearer ${key}`,
    "Content-Type": "application/json",
    "HTTP-Referer": "https://github.com/udhay24/mo-wuji-widget",
    "X-Title": "Mo Wuji Widget",
  }
  req.body = JSON.stringify({
    model: MODELS[0], models: MODELS, max_tokens: 120, temperature: 0.7, reasoning: { enabled: false },
    messages: [{ role: "system", content: PERSONA }, { role: "user", content: prompt }],
  })
  try {
    const res = await req.loadJSON()
    const text = (res.choices && res.choices[0].message.content) || ""
    const match = text.match(/\{[\s\S]*\}/)
    if (!match) return null
    const data = JSON.parse(match[0])
    const line = String(data.quote || "").trim().replace(/^["“”]+|["“”]+$/g, "")
    if (!acceptable(line)) return null
    let theme = String(data.theme || "the path").trim()
    if (theme.toLowerCase().startsWith("on ")) theme = theme.slice(3)
    return { text: line, theme: `On ${theme.charAt(0).toLowerCase()}${theme.slice(1)}`, mood }
  } catch (e) {
    return null
  }
}

function readerContext(stats) {
  const now = new Date()
  const day = now.toLocaleDateString("en-US", { weekday: "long" })
  let context = `it is ${timeOfDay(now.getHours())} on a ${day}`
  if (stats) context += `; today they have finished ${stats.today} of ${stats.goal} closed-door cultivation ` +
    `sessions; their streak is ${plural(stats.streak, "day")}`
  return context
}

// ---------- the pick for this half hour ----------
function choose(state, slot, quotes, key) {
  if (state.slot === slot && state.pick) return
  const rnd = seeded(slot)
  let pick = null
  if (key && slot % 2 === 1 && state.pending) {   // AI and built-in quotes take turns
    pick = state.pending
    state.pending = null
    state.recent = [...(state.recent || []), pick.text].slice(-12)
  }
  if (!pick) {
    const mood = weightedMood(rnd)
    const ofMood = quotes.filter(q => q.mood === mood)
    pick = choice(rnd, ofMood.length ? ofMood : quotes)
  }
  const shorts = quotes.filter(q => q.mood === pick.mood && q.text.length <= 64)
  state.slot = slot
  state.pick = pick
  state.short = pick.text.length <= 64 || !shorts.length ? pick : choice(rnd, shorts)   // for small spaces
  state.scene = sceneFor(pick.mood, rnd)
}

// ---------- layouts ----------
function shaded(art) {   // darkens the painting toward the bottom so text over it stays readable
  const { width, height } = art.size
  const ctx = new DrawContext()
  ctx.size = new Size(width, height)
  ctx.opaque = true
  ctx.respectScreenScale = false
  ctx.drawImageInRect(art, new Rect(0, 0, width, height))
  const bands = 40
  for (let i = 0; i < bands; i++) {
    const f = i / bands
    const alpha = f < 0.3 ? 0.35 - f * 0.5 : Math.min(0.88, 0.2 + (f - 0.3) * 1.2)
    ctx.setFillColor(new Color("#111820", alpha))
    ctx.fillRect(new Rect(0, Math.floor(height * f), width, Math.ceil(height / bands) + 1))
  }
  return ctx.getImage()
}

function header(stack, stats, size) {
  const row = stack.addStack()
  row.layoutHorizontally()
  row.centerAlignContent()
  const title = row.addText("MO WUJI")
  title.font = new Font("Georgia-Bold", size)
  title.textColor = GOLD
  row.addSpacer()
  if (stats) {
    const count = row.addText(`${stats.today} of ${stats.goal} today`)
    count.font = new Font("Georgia", size)
    count.textColor = DIM
  }
}

function addQuote(stack, quote, size, lines) {
  const text = stack.addText(`“${quote.text}”`)
  text.font = new Font("Georgia-Italic", size)
  text.textColor = FG
  text.lineLimit = lines
  text.minimumScaleFactor = 0.6
}

function addTheme(stack, quote, size) {
  const text = stack.addText(`— ${quote.theme}`)
  text.font = new Font("Georgia-Italic", size)
  text.textColor = DIM
  text.lineLimit = 1
}

function medium(w, s, art, stats) {   // the Mac card: painting left, words right
  w.backgroundColor = INK
  w.setPadding(14, 14, 14, 14)
  const row = w.addStack()
  row.layoutHorizontally()
  if (art) {
    const image = row.addImage(art)
    image.imageSize = new Size(130, 130)
    image.cornerRadius = 10
    row.addSpacer(14)
  }
  const col = row.addStack()
  col.layoutVertically()
  header(col, stats, 11)
  col.addSpacer(8)
  addQuote(col, s.pick, 14, 5)
  col.addSpacer()
  addTheme(col, s.pick, 11)
}

function small(w, s, art, stats) {
  if (art) w.backgroundImage = shaded(art)
  else w.backgroundColor = INK
  w.setPadding(12, 12, 12, 12)
  header(w, stats, 10)
  w.addSpacer()
  addQuote(w, s.short, 13, 5)
}

function large(w, s, art, stats) {
  if (art) w.backgroundImage = shaded(art)
  else w.backgroundColor = INK
  w.setPadding(18, 18, 18, 18)
  header(w, stats, 13)
  w.addSpacer()
  addQuote(w, s.pick, 20, 7)
  w.addSpacer(10)
  addTheme(w, s.pick, 13)
  if (stats) {
    w.addSpacer(6)
    const line = w.addText(`Streak ${plural(stats.streak, "day")} · ${plural(stats.sessions, "session")} · ` +
      `${stats.hours.toFixed(1)} hours`)
    line.font = new Font("Georgia", 12)
    line.textColor = DIM
  }
}

function rectangular(w, s) {   // lock screen
  const text = w.addText(s.short.text)
  text.font = new Font("Georgia-Italic", 13)
  text.lineLimit = 3
  text.minimumScaleFactor = 0.6
}

function inline(w, s, stats) {   // the line above the lock-screen clock
  w.addText(stats ? `Mo Wuji · ${stats.today} of ${stats.goal} today` : `Mo Wuji · ${s.short.theme}`)
}

function centered(w) {   // list widgets align their rows to the leading edge
  const row = w.addStack()
  row.addSpacer()
  const inner = row.addStack()
  row.addSpacer()
  return inner
}

function circular(w, stats) {
  w.addAccessoryWidgetBackground = true
  if (!stats) {
    centered(w).addImage(SFSymbol.named("mountain.2.fill").image).imageSize = new Size(26, 26)
    return
  }
  const count = centered(w).addText(`${stats.today}/${stats.goal}`)
  count.font = Font.boldRoundedSystemFont(18)
  const label = centered(w).addText("today")
  label.font = Font.systemFont(9)
}

async function build(family, state, stats) {
  const w = new ListWidget()
  const art = ["small", "medium", "large", "extraLarge"].includes(family) ? await loadArt(state.scene) : null
  if (family === "small") small(w, state, art, stats)
  else if (family === "large" || family === "extraLarge") large(w, state, art, stats)
  else if (family === "accessoryRectangular") rectangular(w, state)
  else if (family === "accessoryInline") inline(w, state, stats)
  else if (family === "accessoryCircular") circular(w, stats)
  else medium(w, state, art, stats)
  w.refreshAfterDate = new Date((state.slot + 1) * SLOT_MINUTES * 60000)
  return w
}

// ---------- in the app: preview and the optional AI key ----------
async function menu(key) {
  const sheet = new Alert()
  sheet.title = "Mo Wuji"
  sheet.message = key ? "AI quotes are on: they take turns with the built-in ones."
    : "Add an OpenRouter key to mix AI-written quotes in with the built-in ones."
  const options = ["Preview medium", "Preview small", "Preview large", key ? "Remove AI key" : "Add AI key"]
  options.forEach(o => sheet.addAction(o))
  sheet.addCancelAction("Close")
  const picked = await sheet.presentSheet()
  if (picked < 0) return null
  if (picked < 3) return ["medium", "small", "large"][picked]
  if (key) {
    Keychain.remove(KEY_NAME)
    return null
  }
  const ask = new Alert()
  ask.title = "OpenRouter key"
  ask.message = "Stored only in this iPhone's Keychain."
  ask.addSecureTextField("sk-or-…", "")
  ask.addAction("Save")
  ask.addCancelAction("Cancel")
  if ((await ask.presentAlert()) === 0 && ask.textFieldValue(0).trim()) Keychain.set(KEY_NAME, ask.textFieldValue(0).trim())
  return null
}

// ---------- run ----------
let key = Keychain.contains(KEY_NAME) ? Keychain.get(KEY_NAME) : null
let family = config.widgetFamily || "medium"
if (config.runsInApp) {
  family = await menu(key)
  key = Keychain.contains(KEY_NAME) ? Keychain.get(KEY_NAME) : null
}

const state = readJSON(statePath) || {}
const quotes = await loadQuotes()
const stats = summarize(await readProgress())
const slot = Math.floor(Date.now() / (SLOT_MINUTES * 60000))
choose(state, slot, quotes, key)

if (family) {
  const widget = await build(family, state, stats)
  if (config.runsInWidget) Script.setWidget(widget)
  else if (family === "small") await widget.presentSmall()
  else if (family === "large") await widget.presentLarge()
  else await widget.presentMedium()
}

// prepare the next AI quote now, so a later refresh shows it without waiting
if (key && !state.pending) state.pending = await aiQuote(key, quotes, state.recent || [], readerContext(stats))
fm.writeString(statePath, JSON.stringify(state))
Script.complete()
