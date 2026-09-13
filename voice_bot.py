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
    "grealish", "bruno fernandes", "odegaard", "rice", "palmer",
    "osimhen", "victor osimhen"
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

def fetch_trending():
    """Pull top football stories right now."""
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
    """Pick the hottest story not recently used."""
    for item in trending:
        if item["title"] not in recent_titles:
            return item
    return trending[0] if trending else None

def generate_script(story):
    """Gemini writes a 30-second voice script based on the actual story."""
    model = genai.GenerativeModel("gemini-3.6-flash")

    prompt = f"""You are writing a 30-second voice note for a football Telegram channel called Football Buzz.

THE STORY RIGHT NOW:
{story['title']}
{story['summary']}

Write it like you're texting your football mate who just heard this news.

Rules:
- Start with a short hook (3-6 words) — NOT "Breaking news" or reporter voice
- Mention the actual story — player names, club, what's happening
- Add ONE hot take or question that makes people want to reply
- End with something like "Full details in the channel" OR "Drop your take in the comments"
- Max 75 words total
- NO emojis (TTS can't read them)
- NO hashtags
- NO "Morning Buzz Fam" or time-based intros
- Sound opinionated, casual, slightly cocky
- It should feel like the FIRST time you're telling someone this news

Write ONLY the script. Nothing else."""

    try:
        return model.generate_content(prompt).text.strip()
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

    trending = fetch_trending()
    print(f"Trending stories found: {len(trending)}")

    if not trending:
        print("No news available. Exiting.")
        return

    story = pick_story(trending, recent)
    print(f"Picked story: {story['title']}")

    script = generate_script(story)
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
