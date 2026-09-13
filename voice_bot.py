import os
import asyncio
import edge_tts
import requests
import google.generativeai as genai
from datetime import datetime
import json

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

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_topic": None}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def get_slot():
    hour = datetime.utcnow().hour
    if hour < 10:
        return "morning"
    elif hour < 18:
        return "transfer"
    else:
        return "matchday"

def generate_script(slot):
    model = genai.GenerativeModel("gemini-3.6-flash")

    prompts = {
        "morning": """You are writing a 30-second morning voice note for a football Telegram channel called Football Buzz.

Write it like you're texting your football mate. Casual, confident, slightly cocky.

Format:
- Start with "Morning Buzz Fam."
- Mention 2-3 quick football things happening right now (transfer rumor, match tonight, drama)
- End with "Full details in the channel. Let's banter."
- Max 75 words total
- No hashtags, no emojis in the text (TTS can't read them)
- No "Breaking news" or reporter voice

Write ONLY the script. Nothing else.""",

        "transfer": """You are writing a 30-second transfer alert voice note for a football Telegram channel called Football Buzz.

Write it like a mate who just heard a rumour and wants your opinion.

Format:
- Start with "Buzz Alert."
- One transfer rumour — player, club, stage of the deal
- Add your hot take or question
- End with "What do you think? Drop it in the comments."
- Max 65 words total
- No hashtags, no emojis in the text
- Sound opinionated, not neutral

Write ONLY the script. Nothing else.""",

        "matchday": """You are writing a 30-second matchday hype voice note for a football Telegram channel called Football Buzz.

Write it like you're getting your mates pumped for a big match.

Format:
- Start with "Matchday."
- Name the biggest match happening today — two teams
- Give a prediction with a score
- Call out one player to watch
- End with "Who you got? Let's see your predictions."
- Max 70 words total
- No hashtags, no emojis in the text
- Sound confident and hype

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
    slot = get_slot()
    print(f"Slot: {slot}")

    script = generate_script(slot)
    if not script:
        print("No script generated.")
        return

    print(f"Script:\n{script}\n")
    print(f"Word count: {len(script.split())}")

    mp3_path = "voice.mp3"
    ogg_path = "voice.ogg"

    asyncio.run(text_to_speech(script, mp3_path))
    convert_to_ogg(mp3_path, ogg_path)

    ok, resp = send_voice(ogg_path, caption="🎙️ Voice update")
    print(f"Sent: {ok}")
    if not ok:
        print(f"Error: {resp}")

    for f in [mp3_path, ogg_path]:
        if os.path.exists(f):
            os.remove(f)

    save_state({"last_topic": slot})

if __name__ == "__main__":
    main()
