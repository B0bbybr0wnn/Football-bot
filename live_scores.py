import os
import json
import requests
import google.generativeai as genai
from datetime import datetime, timedelta

# ====== CONFIG FROM SECRETS ======
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
# ================================

genai.configure(api_key=GEMINI_API_KEY)

STATE_FILE = "live_matches.json"

# ESPN league slugs
LEAGUES = ["eng.1", "esp.1", "uefa.champions", "ita.1", "ger.1", "fra.1"]

BIG_CLUBS = [
    "arsenal", "chelsea", "liverpool", "manchester united", "manchester city",
    "tottenham", "real madrid", "barcelona", "atletico madrid", "psg",
    "bayern", "borussia dortmund", "juventus", "inter", "ac milan",
    "napoli", "roma", "lazio", "sevilla", "valencia", "newcastle",
    "aston villa", "brighton", "west ham", "everton"
]

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"matches": {}}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def is_big_match(home, away):
    h = home.lower()
    a = away.lower()
    return any(club in h for club in BIG_CLUBS) or any(club in a for club in BIG_CLUBS)

def fetch_live_matches():
    """Get live matches from ESPN for all leagues."""
    matches = []

    for league in LEAGUES:
        try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
            res = requests.get(url, timeout=15).json()
            events = res.get("events", [])

            for event in events:
                competition = event.get("competitions", [{}])[0]
                status = competition.get("status", {})
                state = status.get("type", {}).get("state", "")

                # Only in-progress matches
                if state != "in":
                    continue

                competitors = competition.get("competitors", [])
                if len(competitors) < 2:
                    continue

                home = None
                away = None
                home_score = 0
                away_score = 0

                for c in competitors:
                    team_name = c.get("team", {}).get("displayName", "")
                    score = int(c.get("score", "0"))
                    if c.get("homeAway") == "home":
                        home = team_name
                        home_score = score
                    else:
                        away = team_name
                        away_score = score

                if not home or not away:
                    continue

                if not is_big_match(home, away):
                    continue

                # Get goal details
                details = competition.get("details", [])
                goals = []
                for d in details:
                    if d.get("scoringPlay", False):
                        minute = d.get("clock", {}).get("displayValue", "?")
                        athletes = d.get("athletesInvolved", [])
                        scorer = athletes[0].get("displayName", "Unknown") if athletes else "Unknown"
                        team = d.get("team", {}).get("displayName", "")
                        goals.append({
                            "minute": minute,
                            "scorer": scorer,
                            "team": team,
                        })

                match_id = event.get("id", "")
                matches.append({
                    "id": match_id,
                    "home": home,
                    "away": away,
                    "home_score": home_score,
                    "away_score": away_score,
                    "status": state,
                    "goals": goals,
                })
        except Exception as e:
            print(f"ESPN error {league}: {e}")

    return matches

def generate_goal_post(match, latest_goal):
    """Generate a hype goal post with scorer name."""
    model = genai.GenerativeModel("gemini-3.6-flash")

    prompt = f"""You are writing a LIVE goal alert for a football/soccer Telegram channel.

MATCH: {match['home']} {match['home_score']} - {match['away_score']} {match['away']}
SCORER: {latest_goal['scorer']}
MINUTE: {latest_goal['minute']}
TEAM: {latest_goal['team']}

Write a SHORT, hype post (60-100 words) that:
- Starts with "⚽ GOAL! ({latest_goal['minute']})"
- Shows current score in **bold** like: **{match['home']} {match['home_score']} - {match['away_score']} {match['away']}**
- Names the scorer: {latest_goal['scorer']}
- Adds 1-2 sentences of hype/banter
- Max 3 emojis
- No hashtags

Format exactly:
⚽ GOAL! ({latest_goal['minute']})

**{match['home']} {match['home_score']} - {match['away_score']} {match['away']}**

Scorer: {latest_goal['scorer']}

[1-2 sentences hype]
"""

    try:
        return model.generate_content(prompt).text.strip()
    except Exception as e:
        print(f"Gemini error: {e}")
        return f"""⚽ GOAL! ({latest_goal['minute']})

**{match['home']} {match['home_score']} - {match['away_score']} {match['away']}**

Scorer: {latest_goal['scorer']}

What a moment! 🔥"""

def send_telegram(text):
    base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    r = requests.post(f"{base}/sendMessage", data={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }, timeout=20)
    return r.status_code == 200

def main():
    state = load_state()
    tracked = state["matches"]

    live = fetch_live_matches()
    print(f"Live big matches: {len(live)}")

    if not live:
        print("No live matches right now.")
        return

    for match in live:
        mid = match["id"]
        current_score = f"{match['home_score']}-{match['away_score']}"

        if mid not in tracked:
            tracked[mid] = {
                "score": current_score,
                "home": match["home"],
                "away": match["away"],
                "goals_count": len(match["goals"]),
            }
            print(f"Tracking: {match['home']} vs {match['away']} at {current_score}")
            continue

        prev_score = tracked[mid]["score"]
        prev_goals = tracked[mid].get("goals_count", 0)

        if prev_score != current_score:
            # Goal happened!
            new_goals = match["goals"]
            if len(new_goals) > prev_goals:
                latest_goal = new_goals[-1]
                print(f"GOAL! {latest_goal['scorer']} ({latest_goal['minute']})")
                post = generate_goal_post(match, latest_goal)
                ok = send_telegram(post)
                print(f"Posted: {ok}")
                tracked[mid]["goals_count"] = len(new_goals)
            tracked[mid]["score"] = current_score
        else:
            print(f"No change: {match['home']} vs {match['away']} ({current_score})")

    # Clean up matches no longer live
    live_ids = {m["id"] for m in live}
    tracked = {k: v for k, v in tracked.items() if k in live_ids}

    state["matches"] = tracked
    save_state(state)
    print(f"Tracked: {len(tracked)}")

if __name__ == "__main__":
    main()
