import requests
import feedparser
import google.generativeai as genai
from datetime import datetime
import random
import json
import os

# ====== FILL THESE IN ======
TELEGRAM_TOKEN = "8632190175:AAETnurIp5CPEISN5mJLcYMQw94TY_-9VxQ"
CHAT_ID = "-1003852610001"
GEMINI_API_KEY = "AQ.Ab8RN6INzzKf-iKpk8CFiY_6QQyyCs-diCHx-MbRimVqZw477w"
GOOGLE_API_KEY = "AQ.Ab8RN6INzzKf-iKpk8CFiY_6QQyyCs-diCHx-MbRimVqZw477w"
GOOGLE_CSE_ID = "013036536707430787589:_pqjad5hr1a"
# ===========================

genai.configure(api_key=GEMINI_API_KEY)

RSS_FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.espn.com/espn/rss/soccer/news",
    "https://www.skysports.com/rss/11095",
    "https://www.goal.com/feeds/en/news",
    "https://www.theguardian.com/football/rss",
    "https://www.fourfourtwo.com/feeds.xml",
]

POSTED_FILE = "posted.json"

def load_posted():
    """Load set of previously posted article links."""
    try:
        with open(POSTED_FILE, "r") as f:
            data = json.load(f)
            return set(data.get("links", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_posted(posted_set):
    """Save the posted links, keeping only the last 200 to avoid bloat."""
    links = list(posted_set)[-200:]
    with open(POSTED_FILE, "w") as f:
        json.dump({"links": links}, f)

def get_topic():
    hour = datetime.utcnow().hour
    if hour < 8:
        return "Player Spotlight"
    elif hour < 12:
        return "Transfer News"
    elif hour < 16:
        return "Club Focus"
    elif hour < 20:
        return "Scandal & Drama"
    else:
        return "Match Preview"

def fetch_news(topic, posted):
    """Pull news, skip anything already posted, prefer topic-relevant items."""
    topic_keywords = {
        "Player Spotlight": ["player", "star", "scored", "goal", "striker", "midfielder"],
        "Transfer News": ["transfer", "sign", "deal", "move", "loan", "fee"],
        "Club Focus": ["club", "manager", "boss", "squad", "team"],
        "Scandal & Drama": ["ban", "fine", "controversy", "sacked", "row", "slam"],
        "Match Preview": ["preview", "clash", "face", "fixture", "match"],
    }.get(topic, [])

    all_items = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                link = entry.link
                if link in posted:
                    continue  # skip already posted
                all_items.append({
                    "title": entry.title,
                    "summary": entry.get("summary", "")[:250],
                    "link": link,
                })
        except Exception as e:
            print(f"RSS error {url}: {e}")

    if not all_items:
        return "No recent news available.", None, None

    def score(item):
        text = (item["title"] + " " + item["summary"]).lower()
        return sum(1 for kw in topic_keywords if kw in text)

    all_items.sort(key=score, reverse=True)
    top_items = all_items[:8]

    context = "\n".join([f"- {i['title']}: {i['summary']}" for i in top_items])
    chosen = random.choice(top_items[:3])
    return context, chosen["link"], chosen["title"]

def write_post(topic, news):
    model = genai.GenerativeModel("gemini-3.6-flash")
    prompt = f"""
You are writing a Telegram post for a football/soccer channel.

TOPIC: {topic}

RECENT NEWS FOR CONTEXT:
{news}

Write:
- A bold headline (wrap in **double asterisks** for Telegram bold)
- 2-3 punchy paragraphs
- Exciting tone, like a football pundit
- No hashtags, no links, max 2 emojis

Keep it under 150 words.
"""
    try:
        return model.generate_content(prompt).text.strip()
    except Exception as e:
        print(f"Gemini error: {e}")
        return f"**{topic} Update**\n\nBig things happening in football right now. Stay tuned for more! ⚽"

def get_image(topic, news):
    query = {
        "Player Spotlight": "football player celebrating goal",
        "Transfer News": "football transfer signing contract",
        "Club Focus": "football club stadium fans",
        "Scandal & Drama": "football referee controversy",
        "Match Preview": "football stadium night match",
    }.get(topic, "football soccer")

    clubs = ["arsenal", "chelsea", "liverpool", "manchester united",
             "manchester city", "tottenham", "real madrid", "barcelona",
             "psg", "bayern", "juventus", "inter milan", "ac milan"]
    news_lower = news.lower()
    for club in clubs:
        if club in news_lower:
            query = f"{club} football"
            break

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CSE_ID,
        "q": query,
        "searchType": "image",
        "num": 5,
        "imgSize": "xxlarge",
        "imgType": "photo",
        "safe": "active",
    }
    try:
        res = requests.get(url, params=params, timeout=15).json()
        items = res.get("items", [])
        if not items:
            return None
        idx = datetime.utcnow().minute % len(items)
        return items[idx]["link"]
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
            print(f"Photo download error: {e}")

    requests.post(f"{base}/sendMessage", data={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    })

if __name__ == "__main__":
    posted = load_posted()
    print(f"Already posted: {len(posted)} articles")

    topic = get_topic()
    print(f"Topic: {topic}")

    news, source_link, source_title = fetch_news(topic, posted)
    post = write_post(topic, news)

    if source_link:
        post += f"\n\n📰 [Full story]({source_link})"

    img = get_image(topic, news)
    print(f"Image: {img}")

    send_telegram(img, post)

    # Mark this article as posted
    if source_link:
        posted.add(source_link)
        save_posted(posted)
        print(f"Saved. Total tracked: {len(posted)}")

    print("Posted.")
