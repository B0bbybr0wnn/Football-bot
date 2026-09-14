import os
import asyncio
import edge_tts
import requests
import feedparser
import google.generativeai as genai
from datetime import datetime
import json
import random

# ====== CONFIG FROM SECRETS ======
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
# ================================

genai.configure(api_key=GEMINI_API_KEY)

VOICES = {
    "male_uk": "en-GB-RyanNeural",
    "female_uk": "en-GB-SoniaNeural",
    "male_us": "en-US-GuyNeural",
    "female_us": "en-US-AriaNeural",
}
VOICE = VOICES["male_uk"]

STATE_FILE = "voice_state.json"

RSS_FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.espn.com/espn/rss/soccer/news",
    "https://www.skysports.com/rss/11095",
    "https://www.goal.com/feeds/en/news",
    "https://www.theguardian.com/football/rss",
]

STARS = [
    "messi", "ronaldo", "mbappe", "haaland", "vinicius", "bellingham",
    "salah", "kane", "de bruyne", "modric", "neymar", "lewandowski",
    "saka", "foden", "rodri", "yamal", "pedri", "mainoo", "rashford",
    "grealish", "bruno fernandes", "odegaard", "rice", "palmer", "osimhen"
]

CLUBS = [
    "arsenal", "chelsea", "liverpool", "manchester united", "manchester city",
    "tottenham", "real madrid", "barcelona", "atletico madrid", "psg",
    "bayern", "juventus", "inter", "ac milan", "napoli", "newcastle"
]

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"recent_titles": []}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def get_slot():
    """Which of the 4 voice types based on UTC hour."""
    hour = datetime.utcnow().hour
    if hour < 10:
        return "morning_take"
    elif hour < 15:
        return "transfer_reaction"
    elif hour < 19:
        return "matchday_hype"
    else:
        return "postmatch_take"

def fetch_trending():
    items = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:6]:
                items.append({
                    "title": entry.title,
                    "summary": entry.get("summary", "")[:200],
                })
        except Exception as e:
            print(f"RSS error {url}: {e}")

    if not items:
        return []

    def score(item):
        text = (item["title"] + " " + item["summary"]).lower()
        return sum(3 for star in STARS if star in text) + sum(1 for club in CLUBS if club in text)

    items.sort(key=score, reverse=True)
    return items[:5]

def pick_story(trending, recent_titles):
    for item in trending:
        if item["title"] not in recent_titles:
            return item
    return trending[0] if trending else None

def generate_script(slot, story):
    """Gemini writes a hot take — NOT a news recap."""
    model = genai.GenerativeModel("gemini-3.6-flash")

    prompts = {
        "morning_take": f"""You are recording a 30-second voice note for a football Telegram channel called Football Buzz.

THIS JUST HAPPENED IN FOOTBALL:
{story['title']}
{story['summary']}

Your job: record your RAW REACTION as a football fan. Not a news report. A reaction.

Rules:
- Start with a raw reaction — "Bro...", "Yo...", "Wait...", "This is mad..." or similar
- Do NOT explain the news. Assume listeners already saw the text post.
- Instead, give your HOT TAKE. Your opinion. Your angle.
- Ask listeners ONE question at the end (ex: "Am I wrong?" or "Who else saw this coming?")
- Max 70 words
- NO emojis (TTS can't read them)
- NO "Breaking news", "In a shocking turn", or reporter voice
- Sound like a fan ranting to mates
- Slightly cocky, opinionated, casual

Example style (do NOT copy this, just vibe):
"Bro, Chelsea bidding 80 million for a guy with one good season? That's either genius or robbery. I'm leaning robbery. Who else is tired of these inflated prices?"

Write ONLY the script. Nothing else.""",

        "transfer_reaction": f"""You are recording a 30-second voice note for a football Telegram channel called Football Buzz.

TRANSFER NEWS RIGHT NOW:
{story['title']}
{story['summary']}

Your job: react like a fan who just saw the transfer update. Hot take, not report.

Rules:
- Start with something reaction-based: "Oh no...", "This is happening...", "Wait wait wait..."
- Give your OPINION on the move — good deal? Bad deal? Panic buy?
- Name the player and club like you're telling a mate
- End with a question like "Do you take this deal?" or "Upgrade or downgrade?"
- Max 70 words
- NO emojis
- NO reporter voice
- Sound excited, skeptical, or dramatic depending on the deal

Write ONLY the script. Nothing else.""",

        "matchday_hype": f"""You are recording a 30-second voice note for a football Telegram channel called Football Buzz.

BIG MATCH TODAY:
{story['title']}
{story['summary']}

Your job: hype your mates for the match. Prediction-style.

Rules:
- Start with hype — "Matchday.", "Tonight we eat.", "Big one incoming."
- Name the two teams like you're telling your boys
- Give YOUR prediction with a score
- Call out ONE player who decides the game
- End with "Who you got? Let's see." or "Drop your score."
- Max 75 words
- NO emojis
- NO reporter voice
- Sound confident, hype, slightly cocky

Write ONLY the script. Nothing else.""",

        "postmatch_take": f"""You are recording a 30-second voice note for a football Telegram channel called Football Buzz.

MATCH RECAP NEWS:
{story['title']}
{story['summary']}

Your job: post-match reaction — messy, emotional, honest.

Rules:
- Start with a reaction: "Nah that was criminal.", "What did I just watch?", "Called it."
- Give your take on the result — who bottled it, who showed up, who flopped
- Call out a specific player or moment
- End with a spicy question or prediction
- Max 75 words
- NO emojis
- NO reporter voice
- Sound like you just watched the match and have opinions

Write ONLY the script. Nothing else.""",
    }

    try:
        return model.generate_content(prompts[slot]).text.strip()
    except Exception as e:
        print(f"Gemini error: {e}")
        return None

async def text_to_speech(text, output_mp3):
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output_mp3)

def convert_to_ogg(mp3_path, ogg_path):
    os.system(f'ffmpeg -y -i {mp3_path} -c:a libopus -b:a 32k {ogg_path} > /dev/null 2>&1')

def send_voice(ogg_path, caption=""):
    base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    with open(ogg_path, "rb") as f:
        r = requests.post(
            f"{base}/sendVoice",
            data={"chat_id": CHAT_ID, "caption": caption[:1024]},
            files={"voice": ("voice.ogg", f)},
            timeout=30,
        )
    return r.status_code == 200, r.text

def main():
    state = load_state()
    recent = state.get("recent_titles", [])[-20:]

    slot = get_slot()
    print(f"Slot: {slot}")

    trending = fetch_trending()
    print(f"Trending stories found: {len(trending)}")

    if not trending:
        print("No news available. Exiting.")
        return

    story = pick_story(trending, recent)
    print(f"Picked story: {story['title']}")

    script = generate_script(slot, story)
    if not script:
        print("No script generated.")
        return

    print(f"Script:\n{script}\n")
    print(f"Word count: {len(script.split())}")

    mp3_path = "voice.mp3"
    ogg_path = "voice.ogg"

    asyncio.run(text_to_speech(script, mp3_path))
    convert_to_ogg(mp3_path, ogg_path)

    ok, resp = send_voice(ogg_path, caption="🎙️ Football Buzz")
    print(f"Sent: {ok}")
    if not ok:
        print(f"Error: {resp}")

    for f in [mp3_path, ogg_path]:
        if os.path.exists(f):
            os.remove(f)

    recent.append(story["title"])
    save_state({"recent_titles": recent[-20:]})

if __name__ == "__main__":
    main()
