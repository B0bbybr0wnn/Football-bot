import requests
import feedparser
import google.generativeai as genai
from datetime import datetime
import random
import json
import os
import time

# ====== FILL THESE IN ======
TELEGRAM_TOKEN = "8632190175:AAETnurIp5CPEISN5mJLcYMQw94TY_-9VxQ"
CHAT_ID = "-1003852610001"
GEMINI_API_KEY = "AQ.Ab8RN6INzzKf-iKpk8CFiY_6QQyyCs-diCHx-MbRimVqZw477w"
GOOGLE_API_KEY = "AIzaSyAG0yjPU5PWXTHYkw1QQSnTcsX60rb3pXQ"
GOOGLE_CSE_ID = "013036536707430787589:_pqjad5hr1a"
FOOTBALL_DATA_KEY = "afc1741c21a04ee69faf74902dce20c8"
# ===========================

genai.configure(api_key=GEMINI_API_KEY)

# ====== EXPANDED RSS FEEDS (covers more outlets) ======
RSS_FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.espn.com/espn/rss/soccer/news",
    "https://www.skysports.com/rss/11095",
    "https://www.goal.com/feeds/en/news",
    "https://www.theguardian.com/football/rss",
    "https://www.fourfourtwo.com/feeds.xml",
    "https://theathletic.com/rss/",
]

POSTED_FILE = "posted.json"

# ====== TOP STARS TO PRIORITIZE ======
STARS = [
    "messi", "ronaldo", "mbappe", "haaland", "vinicius", "bellingham",
    "salah", "kane", "de bruyne", "modric", "neymar", "lewandowski",
    "saka", "foden", "rodri", "yamal", "pedri", "mainoo", "rashford",
    "grealish", "bruno fernandes", "odegaard", "rice", "palmer"
]

# ====== TOP CLUBS FOR IMAGE MATCHING ======
CLUBS = [
    "arsenal", "chelsea", "liverpool", "manchester united", "man city",
    "tottenham", "real madrid", "barcelona", "psg", "bayern",
    "juventus", "inter milan", "ac milan", "napoli", "dortmund"
]

def load_posted():
    try:
        with open(POSTED_FILE, "r") as f:
            data = json.load(f)
            return set(data.get("links", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_posted(posted_set):
    links = list(posted_set)[-200:]
    with open(POSTED_FILE, "w") as f:
        json.dump({"links": links}, f)

def get_topic():
    hour = datetime.utcnow().hour
    if hour < 6:
        return "Player Spotlight"
    elif hour < 9:
        return "Transfer News"
    elif hour < 12:
        return "Club Focus"
    elif hour < 15:
        return "Scandal & Drama"
    elif hour < 18:
        return "Match Preview"
    elif hour < 21:
        return "Match Recap"
    else:
        return "Player Spotlight"  # repeats — biggest crowd pleaser

def fetch_fixtures():
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    all_fixtures = []
    competitions = ["PL", "CL", "PD", "SA", "BL1", "FL1"]

    for comp in competitions:
        try:
            url = f"https://api.football-data.org/v4/competitions/{comp}/matches?status=SCHEDULED"
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            matches = r.json().get("matches", [])[:5]
            for m in matches:
                home = m["homeTeam"]["name"]
                away = m["awayTeam"]["name"]
                date = m["utcDate"]
                comp_name = m["competition"]["name"]
                all_fixtures.append(f"- [{comp_name}] {home} vs {away} on {date}")
        except Exception as e:
            print(f"Fixture error {comp}: {e}")

    return "\n".join(all_fixtures[:12]) if all_fixtures else "No upcoming fixtures available."

def fetch_news(topic, posted):
    topic_keywords = {
        "Player Spotlight": ["player", "star", "scored", "goal", "striker", "midfielder"],
        "Transfer News": ["transfer", "sign", "deal", "move", "loan", "fee"],
        "Club Focus": ["club", "manager", "boss", "squad", "team"],
        "Scandal & Drama": ["ban", "fine", "controversy", "sacked", "row", "slam"],
        "Match Preview": ["preview", "clash", "face", "fixture", "match"],
        "Match Recap": ["recap", "result", "won", "lost", "beat", "draw"],
    }.get(topic, [])

    all_items = []

    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                link = entry.link
                if link in posted:
                    continue
                all_items.append({
                    "title": entry.title,
                    "summary": entry.get("summary", "")[:250],
                    "link": link,
                })
        except Exception as e:
            print(f"RSS error {url}: {e}")

    # ESPN API - more articles
    espn_leagues = ["eng.1", "esp.1", "uefa.champions", "ita.1", "ger.1", "fra.1"]
    for league in espn_leagues:
        try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/news"
            res = requests.get(url, timeout=15).json()
            for article in res.get("articles", []):
                link = article.get("links", {}).get("web", {}).get("href", "")
                if not link or link in posted:
                    continue
                all_items.append({
                    "title": article.get("headline", ""),
                    "summary": article.get("description", "")[:250],
                    "link": link,
                })
        except Exception as e:
            print(f"ESPN error {league}: {e}")

    if not all_items:
        return "No recent news available.", None

    def score(item):
        text = (item["title"] + " " + item["summary"]).lower()
        topic_score = sum(1 for kw in topic_keywords if kw in text)
        star_score = sum(3 for star in STARS if star in text)  # Stars heavily weighted
        return topic_score + star_score

    all_items.sort(key=score, reverse=True)
    top_items = all_items[:15]
    context = "\n".join([f"- {i['title']}: {i['summary']}" for i in top_items])
    source = random.choice(top_items[:5])["link"]
    return context, source

def write_post(topic, news, fixtures=""):
    model = genai.GenerativeModel("gemini-3.6-flash")

    if topic == "Match Preview" and fixtures:
        prompt = f"""
You are writing a Telegram post for a football/soccer channel.

TOPIC: Match Preview

UPCOMING FIXTURES (real data):
{fixtures}

RECENT NEWS FOR CONTEXT:
{news}

Write a LONGER, engaging post (aim for 4-5 paragraphs, 300-400 words) that:
- Has a bold headline (wrap in **double asterisks**)
- Previews 3-4 of the biggest upcoming matches
- Mentions actual team names, kickoff days, and what's at stake
- Adds humor and banter like a football pundit with personality
- Includes at least one laugh-out-loud observation or funny comparison
- No hashtags, no links, max 3 emojis

Style: Exciting, funny, opinionated. Make people want to read it and share it.
"""
    else:
        prompt = f"""
You are writing a Telegram post for a football/soccer channel.

TOPIC: {topic}

RECENT NEWS FOR CONTEXT:
{news}

Write an engaging, LONGER post (aim for 4-5 paragraphs, 300-400 words) that:
- Has a bold headline (wrap in **double asterisks**)
- Covers the biggest story here with real depth
- Adds humor, banter, and a laugh or two
- Sounds like a mate who knows football talking, not a boring reporter
- Includes at least one funny observation about a player, manager, or situation
- No hashtags, no links, max 3 emojis

Style: Exciting, funny, opinionated. Make people want to read it and share it.
"""
    try:
        return model.generate_content(prompt).text.strip()
    except Exception as e:
        print(f"Gemini error: {e}")
        return f"**{topic} Update**\n\nBig things happening in football right now. Stay tuned! ⚽"

def get_image(topic, news):
    query = {
        "Player Spotlight": "football player celebrating goal",
        "Transfer News": "football transfer signing contract",
        "Club Focus": "football club stadium fans",
        "Scandal & Drama": "football referee controversy",
        "Match Preview": "football stadium night match",
        "Match Recap": "football match goal celebration",
    }.get(topic, "football soccer")

    news_lower = news.lower()
    for club in CLUBS:
        if club in news_lower:
            query = f"{club} football"
            break

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CSE_ID,
        "q": query,
        "searchType": "image",
        "num": 10,
        "imgSize": "large",
        "safe": "active",
    }
    try:
        res = requests.get(url, params=params, timeout=15).json()
        items = res.get("items", [])
        print(f"Google image results: {len(items)}")
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

    # Telegram message limit is 4096 chars - split if needed
    if len(text) > 4000:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            requests.post(f"{base}/sendMessage", data={
                "chat_id": CHAT_ID,
                "text": chunk,
                "parse_mode": "Markdown",
            })
            time.sleep(1)
    else:
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

    news, source_link = fetch_news(topic, posted)

    fixtures = ""
    if topic == "Match Preview":
        fixtures = fetch_fixtures()
        print(f"Fixtures pulled:\n{fixtures}")

    post = write_post(topic, news, fixtures)

    if source_link:
        post += f"\n\n📰 [Full story]({source_link})"

    img = get_image(topic, news)
    print(f"Image: {img}")

    send_telegram(img, post)

    if source_link:
        posted.add(source_link)
        save_posted(posted)
        print(f"Saved. Total tracked: {len(posted)}")

    print("Posted.")
