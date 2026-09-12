import os
import json
import requests
import google.generativeai as genai
from datetime import datetime, timedelta

# ====== CONFIG FROM SECRETS ======
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
FOOTBALL_DATA_KEY = os.environ["FOOTBALL_DATA_KEY"]
GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
GOOGLE_CSE_ID = os.environ["GOOGLE_CSE_ID"]
# ================================

genai.configure(api_key=GEMINI_API_KEY)


def generate_reaction(post_text):
    """Generate a short comment-bait reaction to the announcement."""
    model = genai.GenerativeModel("gemini-3.6-flash")
    prompt = f"""You just read this football match announcement post on a Telegram channel:

{post_text[:800]}

Write ONE short casual reaction sentence that:
- Sounds like a real football fan, not a bot
- Picks one specific match from the list to react to
- Ends with a question OR a hot take that makes people want to reply
- Max 15 words
- Max 2 emojis
- No hashtags
- No "What do you think?" generic shit
- Sound human, opinionated, a bit funny

Just write the sentence. Nothing else."""
    try:
        return model.generate_content(prompt).text.strip()
    except Exception as e:
        print(f"Reaction error: {e}")
        return None
        

ANNOUNCED_2DAYS = "announced_2days.json"
ANNOUNCED_TOMORROW = "announced_tomorrow.json"

COMPETITIONS = ["PL", "CL", "PD", "SA", "BL1", "FL1"]

BIG_CLUBS = [
    "arsenal", "chelsea", "liverpool", "manchester united", "manchester city",
    "tottenham", "real madrid", "barcelona", "atletico madrid", "psg",
    "bayern", "borussia dortmund", "juventus", "inter", "ac milan",
    "napoli", "roma", "lazio", "sevilla", "valencia", "newcastle",
    "aston villa", "brighton", "west ham", "everton"
]

def load_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"matches": []}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)

def is_big_match(home, away):
    h = home.lower()
    a = away.lower()
    return any(club in h for club in BIG_CLUBS) or any(club in a for club in BIG_CLUBS)

def fetch_fixtures():
    """Get all scheduled matches from Football-Data.org."""
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    fixtures = []

    for comp in COMPETITIONS:
        try:
            url = f"https://api.football-data.org/v4/competitions/{comp}/matches?status=SCHEDULED"
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                print(f"Fixture {comp} failed: {r.status_code}")
                continue
            for m in r.json().get("matches", []):
                home = m["homeTeam"]["name"]
                away = m["awayTeam"]["name"]
                if not is_big_match(home, away):
                    continue
                fixtures.append({
                    "id": str(m["id"]),
                    "home": home,
                    "away": away,
                    "utc_date": m["utcDate"],
                    "competition": m["competition"]["name"],
                })
        except Exception as e:
            print(f"Fixture error {comp}: {e}")

    return fixtures

def generate_post(matches, kind):
    """kind = '2days' or 'tomorrow'"""
    model = genai.GenerativeModel("gemini-3.6-flash")

    match_lines = "\n".join([
        f"- {m['home']} vs {m['away']} ({m['competition']}) — {m['utc_date']}"
        for m in matches
    ])

    if kind == "tomorrow":
        intro = "These big matches are TOMORROW. Get ready."
        time_note = "Tomorrow"
    else:
        intro = "These big matches are coming up in 2 days."
        time_note = "In 2 days"

    prompt = f"""You are writing a Telegram post for a football/soccer channel.

CONTEXT: {intro}

MATCHES:
{match_lines}

Write a hype post (150-250 words) that:
- Has a bold headline in **double asterisks**
- Lists each match with a line of hype (1-2 sentences each)
- Adds banter, humor, and predictions
- Ends with a "don't miss it" line
- No hashtags, no links, max 3 emojis

Start the post with a time hint like "📅 {time_note}:"
"""

    try:
        return model.generate_content(prompt).text.strip()
    except Exception as e:
        print(f"Gemini error: {e}")
        return f"📅 **{time_note}**\n\n" + "\n".join([
            f"⚽ {m['home']} vs {m['away']} ({m['competition']})"
            for m in matches
        ])

def get_image():
    query = "football stadium big match"
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CSE_ID,
        "q": query,
        "searchType": "image",
        "num": 5,
        "imgSize": "large",
        "safe": "active",
    }
    try:
        res = requests.get(url, params=params, timeout=15).json()
        items = res.get("items", [])
        if not items:
            return None
        return items[datetime.utcnow().minute % len(items)]["link"]
    except Exception as e:
        print(f"Image error: {e}")
        return None

def send_telegram(image_url, text):
    base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

    if image_url:
        try:
            img_data = requests.get(image_url, timeout=20, headers={
                "User-Agent": "Mozilla/5.0"
            }).content
            r = requests.post(
                f"{base}/sendPhoto",
                data={
                    "chat_id": CHAT_ID,
                    "caption": text[:1024],
                    "parse_mode": "Markdown",
                },
                files={"photo": ("image.jpg", img_data)},
                timeout=30,
            )
            if r.status_code == 200:
                return
            print(f"Photo failed: {r.text}")
        except Exception as e:
            print(f"Photo error: {e}")

    requests.post(f"{base}/sendMessage", data={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    })

def main():
    # Check what time it is
    now = datetime.utcnow()
    hour = now.hour

    # Windows: 10:00 UTC = 11 AM WAT (2-day reminder) OR 19:00 UTC = 8 PM WAT (tomorrow reminder)
    mode = None
    if 9 <= hour < 11:
        mode = "2days"
    elif 19 <= hour < 21:
        mode = "tomorrow"
    else:
        print(f"Not a reminder window (UTC hour {hour}). Exiting.")
        return

    print(f"Mode: {mode}")

    fixtures = fetch_fixtures()
    print(f"Total big matches upcoming: {len(fixtures)}")

    if mode == "2days":
        target_date = (now + timedelta(days=2)).date()
        announced = load_json(ANNOUNCED_2DAYS)
        announced_ids = set(announced["matches"])

        selected = [
            m for m in fixtures
            if datetime.strptime(m["utc_date"][:10], "%Y-%m-%d").date() == target_date
            and m["id"] not in announced_ids
        ]
        print(f"Matches 2 days out: {len(selected)}")

        if not selected:
            print("Nothing to announce.")
            return

        post = generate_post(selected, "2days")
        img = get_image()
        send_telegram(img, post)

        
        import time as _time
        _time.sleep(30)
        reaction = generate_reaction(post)
        if reaction:
            base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
            requests.post(f"{base}/sendMessage", data={
                "chat_id": CHAT_ID,
                "text": reaction,
            }, timeout=20)
            print(f"Reaction sent: {reaction}")
    

        for m in selected:
            announced_ids.add(m["id"])
        save_json(ANNOUNCED_2DAYS, {"matches": list(announced_ids)})
        print(f"Announced {len(selected)} matches for 2 days out.")

    elif mode == "tomorrow":
        target_date = (now + timedelta(days=1)).date()
        announced = load_json(ANNOUNCED_TOMORROW)
        announced_ids = set(announced["matches"])

        selected = [
            m for m in fixtures
            if datetime.strptime(m["utc_date"][:10], "%Y-%m-%d").date() == target_date
            and m["id"] not in announced_ids
        ]
        print(f"Matches tomorrow: {len(selected)}")

        if not selected:
            print("Nothing to announce.")
            return

        post = generate_post(selected, "tomorrow")
        img = get_image()
        send_telegram(img, post)
        
        import time as _time
        _time.sleep(30)
        reaction = generate_reaction(post)
        if reaction:
            base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
            requests.post(f"{base}/sendMessage", data={
                "chat_id": CHAT_ID,
                "text": reaction,
            }, timeout=20)
            print(f"Reaction sent: {reaction}")
    

        for m in selected:
            announced_ids.add(m["id"])
        save_json(ANNOUNCED_TOMORROW, {"matches": list(announced_ids)})
        print(f"Announced {len(selected)} matches for tomorrow.")

if __name__ == "__main__":
    main()
