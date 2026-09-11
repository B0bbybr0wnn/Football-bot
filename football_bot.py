import requests
import feedparser
import google.generativeai as genai
from datetime import datetime

# ====== FILL THESE IN ======
TELEGRAM_TOKEN = "8632190175:AAETnurIp5CPEISN5mJLcYMQw94TY_-9VxQ"
CHAT_ID = "-1003852610001"
GEMINI_API_KEY = "AQ.Ab8RN6INzzKf-iKpk8CFiY_6QQyyCs-diCHx-MbRimVqZw477w"
GOOGLE_API_KEY = "AIzaSyAG0yjPU5PWXTHYkw1QQSnTcsX60rb3pXQ"
GOOGLE_CSE_ID = "013036536707430787589:_pqjad5hr1a"
# ===========================

genai.configure(api_key=GEMINI_API_KEY)

RSS_FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.espn.com/espn/rss/soccer/news",
]

def get_topic():
    hour = datetime.utcnow().hour
    if hour < 12:
        return "Player Spotlight"
    elif hour < 18:
        return "Transfer News"
    else:
        return "Match Recap"

def fetch_news():
    items = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                items.append(f"- {entry.title}: {entry.summary[:200]}")
        except Exception as e:
            print(f"RSS error {url}: {e}")
    return "\n".join(items[:8]) if items else "No recent news available."

def write_post(topic, news):
    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = f"""
You are writing a Telegram post for a football/soccer channel.

TOPIC: {topic}

RECENT NEWS FOR CONTEXT:
{news}

Write:
- A bold headline
- 2-3 punchy paragraphs
- Exciting tone, like a football pundit
- No hashtags, no links, max 2 emojis

Keep it under 150 words.
"""
    return model.generate_content(prompt).text.strip()

def get_image(topic):
    query = {
        "Player Spotlight": "football player celebrating goal",
        "Transfer News": "football transfer signing contract",
        "Match Recap": "football stadium match action",
    }.get(topic, "football soccer")

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
        r = requests.post(f"{base}/sendPhoto", data={
            "chat_id": CHAT_ID,
            "photo": image_url,
            "caption": text[:1024],
        })
        if r.status_code == 200:
            return
        print(f"Photo failed: {r.text}")

    requests.post(f"{base}/sendMessage", data={
        "chat_id": CHAT_ID,
        "text": text,
    })

if __name__ == "__main__":
    topic = get_topic()
    print(f"Topic: {topic}")
    news = fetch_news()
    post = write_post(topic, news)
    img = get_image(topic)
    print(f"Image: {img}")
    send_telegram(img, post)
    print("Posted.")
