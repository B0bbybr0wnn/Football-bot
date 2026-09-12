import requests
import feedparser
import google.generativeai as genai
from datetime import datetime
import random
import json
import os
import time

# ====== FILL THESE IN ======
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
GOOGLE_CSE_ID = os.environ["GOOGLE_CSE_ID"]
FOOTBALL_DATA_KEY = os.environ["FOOTBALL_DATA_KEY"]
# ===========================

genai.configure(api_key=GEMINI_API_KEY)

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
MESSAGES_FILE = "live_messages.json"
DELETE_AFTER = 48 * 3600

STARS = [
    "messi", "ronaldo", "mbappe", "haaland", "vinicius", "bellingham",
    "salah", "kane", "de bruyne", "modric", "neymar", "lewandowski",
    "saka", "foden", "rodri", "yamal", "pedri", "mainoo", "rashford",
    "grealish", "bruno fernandes", "odegaard", "rice", "palmer"
]

CLUBS = [
    "arsenal", "chelsea", "liverpool", "manchester united", "man city",
    "tottenham", "real madrid", "barcelona", "psg", "bayern",
    "juventus", "inter milan", "ac milan", "napoli", "dortmund"
]

COMPETITIONS = ["PL", "CL", "PD", "SA", "BL1", "FL1"]

def load_posted():
    try:
        with open(POSTED_FILE, "r") as f:
            data = json.load(f)
            return {
                "links": set(data.get("links", [])),
                "titles": data.get("titles", [])[-50:],
            }
    except (FileNotFoundError, json.JSONDecodeError):
        return {"links": set(), "titles": []}

def save_posted(posted_data):
    links = list(posted_data["links"])[-200:]
    titles = posted_data["titles"][-50:]
    with open(POSTED_FILE, "w") as f:
        json.dump({"links": links, "titles": titles}, f)

def is_similar(title, past_titles, threshold=0.65):
    def words(t):
        return set(w.lower().strip(".,!?:;\"'") for w in t.split() if len(w) > 3)
    t_words = words(title)
    if not t_words:
        return False
    for past in past_titles:
        p_words = words(past)
        if not p_words:
            continue
        overlap = len(t_words & p_words) / len(t_words)
        if overlap >= threshold:
            return True
    return False

def load_messages():
    try:
        with open(MESSAGES_FILE, "r") as f:
            return json.load(f).get("messages", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_messages(messages):
    with open(MESSAGES_FILE, "w") as f:
        json.dump({"messages": messages}, f)

def track_message(message_id):
    msgs = load_messages()
    msgs.append({
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "ts": int(time.time()),
    })
    save_messages(msgs)

def cleanup_old_messages():
    """Delete only tracked (recap) messages older than 48h."""
    msgs = load_messages()
    now = int(time.time())
    kept = []
    deleted = 0
    base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

    for m in msgs:
        age = now - m["ts"]
        if age > DELETE_AFTER:
            try:
                r = requests.post(f"{base}/deleteMessage", data={
                    "chat_id": m["chat_id"],
                    "message_id": m["message_id"],
                }, timeout=15)
                if r.status_code == 200:
                    deleted += 1
                    print(f"Deleted recap msg {m['message_id']} (age {age//3600}h)")
            except Exception as e:
                print(f"Delete error: {e}")
        else:
            kept.append(m)

    save_messages(kept)
    print(f"Cleanup done. Deleted: {deleted}, Remaining: {len(kept)}")

def get_topic():
    hour = datetime.utcnow().hour
    mapping = {
        5: "Player Spotlight",
        7: "Transfer News",
        9: "Club Focus",
        11: "Scandal & Drama",
        14: "Match Preview",
        17: "Match Recap",
        20: "Player Spotlight",
        23: "Transfer News",
    }
    return mapping.get(hour, "Player Spotlight")

def fetch_fixtures():
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    all_fixtures = []
    for comp in COMPETITIONS:
        try:
            url = f"https://api.football-data.org/v4/competitions/{comp}/matches?status=SCHEDULED"
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            for m in r.json().get("matches", [])[:5]:
                home = m["homeTeam"]["name"]
                away = m["awayTeam"]["name"]
                date = m["utcDate"]
                comp_name = m["competition"]["name"]
                all_fixtures.append(f"- [{comp_name}] {home} vs {away} on {date}")
        except Exception as e:
            print(f"Fixture error {comp}: {e}")
    return "\n".join(all_fixtures[:12]) if all_fixtures else "No upcoming fixtures."

def fetch_recent_results():
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    results = []
    for comp in COMPETITIONS:
        try:
            url = f"https://api.football-data.org/v4/competitions/{comp}/matches?status=FINISHED"
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            matches = r.json().get("matches", [])
            matches = sorted(matches, key=lambda m: m["utcDate"], reverse=True)[:5]
            for m in matches:
                home = m["homeTeam"]["name"]
                away = m["awayTeam"]["name"]
                score = m["score"]["fullTime"]
                if score.get("home") is None or score.get("away") is None:
                    continue
                date = m["utcDate"][:10]
                comp_name = m["competition"]["name"]
                results.append(
                    f"- [{comp_name}] {home} {score['home']}-{score['away']} {away} on {date}"
                )
        except Exception as e:
            print(f"Results error {comp}: {e}")
    return "\n".join(results[:12]) if results else "No recent results."

def fetch_news(topic, posted):
    posted_links = posted["links"]
    posted_titles = posted["titles"]

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
                if link in posted_links:
                    continue
                if is_similar(entry.title, posted_titles):
                    continue
                all_items.append({
                    "title": entry.title,
                    "summary": entry.get("summary", "")[:250],
                    "link": link,
                })
        except Exception as e:
            print(f"RSS error {url}: {e}")

    espn_leagues = ["eng.1", "esp.1", "uefa.champions", "ita.1", "ger.1", "fra.1"]
    for league in espn_leagues:
        try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/news"
            res = requests.get(url, timeout=15).json()
            for article in res.get("articles", []):
                link = article.get("links", {}).get("web", {}).get("href", "")
                if not link or link in posted_links:
                    continue
                headline = article.get("headline", "")
                if is_similar(headline, posted_titles):
                    continue
                all_items.append({
                    "title": headline,
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
        star_score = sum(3 for star in STARS if star in text)
        return topic_score + star_score

    all_items.sort(key=score, reverse=True)
    top_items = all_items[:15]
    context = "\n".join([f"- {i['title']}: {i['summary']}" for i in top_items])
    source = random.choice(top_items[:5])["link"]
    return context, source

def write_post(topic, news, fixtures="", results=""):
    model = genai.GenerativeModel("gemini-3.6-flash")

    if topic == "Match Preview" and fixtures:
        prompt = f"""You are writing a Telegram post for a football/soccer channel.
TOPIC: Match Preview
UPCOMING FIXTURES: {fixtures}
RECENT NEWS: {news}
Write a LONGER post (300-400 words):
- Bold headline in **double asterisks**
- Preview 3-4 biggest upcoming matches with real team names + kickoff days
- Humor, banter, funny comparisons like a pundit
- No hashtags, no links, max 3 emojis"""
    elif topic == "Match Recap" and results:
        prompt = f"""You are writing a Telegram post for a football/soccer channel.
TOPIC: Match Recap
RECENT RESULTS: {results}
RECENT NEWS: {news}
Write a LONGER post (300-400 words):
- Bold headline in **double asterisks**
- Recap 3-4 biggest results with real scores
- Standout performers + drama from news
- Banter, hot takes, one laugh-out-loud line
- No hashtags, no links, max 3 emojis"""
    else:
        prompt = f"""You are writing a Telegram post for a football/soccer channel.
TOPIC: {topic}
RECENT NEWS: {news}
Write an engaging LONGER post (300-400 words):
- Bold headline in **double asterisks**
- Cover the biggest story with real depth
- Humor, banter, funny observations
- Sound like a football mate, not a boring reporter
- No hashtags, no links, max 3 emojis"""

    try:
        return model.generate_content(prompt).text.strip()
    except Exception as e:
        print(f"Gemini error: {e}")
        return f"**{topic} Update**\n\nBig things happening in football. Stay tuned! ⚽"

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

def send_telegram(image_url, text, track=False):
    """
    Send a post.
    track=True → save message ID for auto-delete (recaps only)
    """
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
                if track:
                    msg_id = r.json().get("result", {}).get("message_id")
                    if msg_id:
                        track_message(msg_id)
                return
            print(f"Photo failed: {r.text}")
        except Exception as e:
            print(f"Photo download error: {e}")

    if len(text) > 4000:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            r = requests.post(f"{base}/sendMessage", data={
                "chat_id": CHAT_ID,
                "text": chunk,
                "parse_mode": "Markdown",
            })
            if r.status_code == 200 and track:
                msg_id = r.json().get("result", {}).get("message_id")
                if msg_id:
                    track_message(msg_id)
            time.sleep(1)
    else:
        r = requests.post(f"{base}/sendMessage", data={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
        })
        if r.status_code == 200 and track:
            msg_id = r.json().get("result", {}).get("message_id")
            if msg_id:
                track_message(msg_id)

if __name__ == "__main__":
    print("=== Cleanup: deleting old recaps (>48h) ===")
    cleanup_old_messages()

    posted = load_posted()
    print(f"Already posted: {len(posted['links'])} articles")

    topic = get_topic()
    print(f"Topic: {topic}")

    news, source_link = fetch_news(topic, posted)

    fixtures = ""
    results = ""
    if topic == "Match Preview":
        fixtures = fetch_fixtures()
        print(f"Fixtures:\n{fixtures}")
    elif topic == "Match Recap":
        results = fetch_recent_results()
        print(f"Results:\n{results}")

    post = write_post(topic, news, fixtures, results)

    if source_link and topic != "Match Recap":
        post += f"\n\n📰 [Full story]({source_link})"

    img = get_image(topic, news)
    print(f"Image: {img}")

    # Only track recaps for auto-delete
    should_track = (topic == "Match Recap")
    send_telegram(img, post, track=should_track)

    if source_link:
        posted["links"].add(source_link)
    first_line = post.split("\n")[0].strip("* ")
    posted["titles"].append(first_line)
    save_posted(posted)

    print(f"Saved. Links: {len(posted['links'])}, titles: {len(posted['titles'])}")
    print("Posted.")
