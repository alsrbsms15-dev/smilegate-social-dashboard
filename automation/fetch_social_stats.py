#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_social_stats.py
  Daily social-stats puller for Smilegate content marketing team.

  Reads  : ../smilegate-sns-credentials.yaml
  Writes : ../dashboard-snapshots/YYYY-MM-DD.json
           ../dashboard-snapshots/history.json         (rolling 90-day series)
           ../latest-dashboard.html                    (standalone dashboard)

  Designed to run on the marketer's Windows PC (unrestricted network)
  either manually or via Windows Task Scheduler.

  Exit codes:
    0 = success (even if some platforms had no credentials — still emits snapshot)
    1 = fatal error (config missing, disk full, etc.)
"""

import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, date, timedelta
from pathlib import Path

try:
    import yaml  # PyYAML — install via: pip install pyyaml
except ImportError:
    print("ERROR: PyYAML is not installed. Run:  pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# SSL context selection, in order of preference:
#   1. truststore  → uses Windows/macOS native cert store (includes corporate CAs
#                    installed by IT, needed when the network does SSL interception)
#   2. certifi     → Mozilla's up-to-date CA bundle (fixes older Python chain issues)
#   3. default     → Python's bundled CAs (fallback)
SSL_CTX = None
try:
    import truststore
    SSL_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
except ImportError:
    pass
if SSL_CTX is None:
    try:
        import certifi
        SSL_CTX = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        SSL_CTX = ssl.create_default_context()


# ==================================================================
# Configuration
# ==================================================================
SCRIPT_DIR   = Path(__file__).resolve().parent
WORKSPACE    = SCRIPT_DIR.parent                       # "Claude Tasks" folder
CRED_FILE    = WORKSPACE / "smilegate-sns-credentials.yaml"
SNAPSHOTS    = WORKSPACE / "dashboard-snapshots"
HISTORY_FILE = SNAPSHOTS / "history.json"
LATEST_HTML  = WORKSPACE / "latest-dashboard.html"
INDEX_HTML   = WORKSPACE / "index.html"  # served by GitHub Pages

TODAY = date.today().isoformat()
NOW_ISO = datetime.now().astimezone().isoformat(timespec="seconds")

# Channel registry — mirrors the Cowork artifact.
# Channels with a `yt_id` are resolved directly; those with `yt_handle`
# get their id looked up via the YouTube Data API on first run.
GAMES = [
    {
        "id": "epic7",
        "name": "Epic Seven",
        "ko": "에픽세븐",
        "color": "#6B5FD4",
        "channels": [
            {"platform": "youtube",   "region": "Global", "handle": "@EpicSeven",         "url": "https://www.youtube.com/channel/UCa1C3tWzsn4FFRR7t3LqU5w",   "yt_id": "UCa1C3tWzsn4FFRR7t3LqU5w"},
            {"platform": "youtube",   "region": "Korea",  "handle": "@EpicSevenKR",       "url": "https://www.youtube.com/c/EpicSevenKR",                     "yt_handle": "@EpicSevenKR"},
            {"platform": "youtube",   "region": "Japan",  "handle": "@EpicSevenJP",       "url": "https://www.youtube.com/@EpicSevenJP",                      "yt_handle": "@EpicSevenJP"},
            {"platform": "youtube",   "region": "Taiwan", "handle": "@EpicSevenTW",       "url": "https://www.youtube.com/@EpicSevenTW",                      "yt_handle": "@EpicSevenTW"},
            {"platform": "x",         "region": "Global", "handle": "@Epic7_Global",      "url": "https://x.com/Epic7_Global"},
            {"platform": "x",         "region": "Korea",  "handle": "@Epic7Twt",          "url": "https://x.com/Epic7Twt"},
            {"platform": "instagram", "region": "Global", "handle": "@epicseven_global",  "url": "https://www.instagram.com/epicseven_global/", "ig_business_id": "17841407368977464"},
            {"platform": "facebook",  "region": "Global", "handle": "EpicSevenGlobal",    "url": "https://www.facebook.com/EpicSevenGlobal/",          "fb_page_id": "583835325289924"},
            {"platform": "facebook",  "region": "Korea",  "handle": "EpicSevenKR",        "url": "https://www.facebook.com/EpicSevenKR/",              "fb_page_id": "487725344745343"},
            {"platform": "facebook",  "region": "Taiwan", "handle": "第七史詩 (TW)",       "url": "https://www.facebook.com/680591358967035",           "fb_page_id": "680591358967035"},
            {"platform": "discord",   "region": "Official","handle": "discord.gg/vUUQvUQPZC", "url": "https://discord.com/invite/vUUQvUQPZC", "invite_code": "vUUQvUQPZC"},
        ],
    },
    {
        "id": "czn",
        "name": "Chaos Zero Nightmare",
        "ko": "카오스 제로 나이트메어",
        "color": "#D4495F",
        "channels": [
            {"platform": "youtube",   "region": "Korea",   "handle": "@ChaosZeroNightmare_KR", "url": "https://www.youtube.com/@ChaosZeroNightmare_KR", "yt_handle": "@ChaosZeroNightmare_KR"},
            {"platform": "youtube",   "region": "Global",  "handle": "@ChaosZeroNightmare_EN", "url": "https://www.youtube.com/@ChaosZeroNightmare_EN", "yt_handle": "@ChaosZeroNightmare_EN"},
            {"platform": "youtube",   "region": "Japan",   "handle": "@ChaosZeroNightmare_JP", "url": "https://www.youtube.com/@ChaosZeroNightmare_JP", "yt_handle": "@ChaosZeroNightmare_JP"},
            {"platform": "youtube",   "region": "Taiwan",  "handle": "@ChaosZeroNightmare_TW", "url": "https://www.youtube.com/@ChaosZeroNightmare_TW", "yt_handle": "@ChaosZeroNightmare_TW"},
            {"platform": "x",         "region": "Global",  "handle": "@CZN_Official_EN",      "url": "https://x.com/CZN_Official_EN"},
            {"platform": "instagram", "region": "Global",  "handle": "@czn.official.en",       "url": "https://www.instagram.com/czn.official.en/", "ig_business_id": "17841465051500490"},
            {"platform": "facebook",  "region": "Global",  "handle": "ChaosZeroNightmare",    "url": "https://www.facebook.com/ChaosZeroNightmare/",       "fb_page_id": "101588973009044"},
            {"platform": "facebook",  "region": "Japan",   "handle": "カオスゼロナイトメア公式",  "url": "https://www.facebook.com/790177604183352",            "fb_page_id": "790177604183352"},
            {"platform": "facebook",  "region": "China",   "handle": "卡厄思夢境",              "url": "https://www.facebook.com/107964449030742",            "fb_page_id": "107964449030742"},
            {"platform": "discord",   "region": "Official","handle": "discord.gg/chaoszeronightmare", "url": "https://discord.gg/chaoszeronightmare", "invite_code": "chaoszeronightmare"},
        ],
    },
    {
        "id": "l9",
        "name": "Lord Nine",
        "ko": "로드나인",
        "color": "#C79848",
        "channels": [
            {"platform": "youtube",   "region": "Korea",  "handle": "@LORDNINE_KR",     "url": "https://www.youtube.com/@LORDNINE_KR",     "yt_handle": "@LORDNINE_KR"},
            {"platform": "youtube",   "region": "Global", "handle": "@LORDNINE_GLOBAL", "url": "https://www.youtube.com/@LORDNINE_GLOBAL", "yt_handle": "@LORDNINE_GLOBAL"},
            {"platform": "youtube",   "region": "Japan",  "handle": "@LORDNINE_JP",     "url": "https://www.youtube.com/@LORDNINE_JP",     "yt_handle": "@LORDNINE_JP"},
            {"platform": "x",         "region": "Global", "handle": "TBD", "url": "", "missing": True, "note": "Unconfirmed — please provide URL"},
            {"platform": "instagram", "region": "Global", "handle": "TBD", "url": "", "missing": True, "note": "Unconfirmed — please provide URL"},
            {"platform": "facebook",  "region": "Korea",   "handle": "LordnineKR",        "url": "https://www.facebook.com/LordnineKR/",          "fb_page_id": "337644159430761"},
            {"platform": "facebook",  "region": "SEA",     "handle": "LordnineSEA",       "url": "https://www.facebook.com/LordnineSEA/",         "fb_page_id": "646314575225540"},
            {"platform": "facebook",  "region": "Japan",   "handle": "ロードナイン",        "url": "https://www.facebook.com/630342166838803",      "fb_page_id": "630342166838803"},
            {"platform": "facebook",  "region": "Thailand","handle": "LORDNINE Thailand", "url": "https://www.facebook.com/561566950382982",      "fb_page_id": "561566950382982"},
            {"platform": "facebook",  "region": "China",   "handle": "權力之望 LORDNINE",    "url": "https://www.facebook.com/293217650546931",      "fb_page_id": "293217650546931"},
            {"platform": "discord",   "region": "SEA",    "handle": "discord.gg/lordninesea", "url": "https://discord.gg/lordninesea", "invite_code": "lordninesea"},
        ],
    },
]


# ==================================================================
# Utilities
# ==================================================================
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def http_get_json(url, timeout=15):
    """GET a URL and parse JSON. Raises on non-2xx."""
    req = urllib.request.Request(url, headers={"User-Agent": "smilegate-sns-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return json.loads(r.read().decode("utf-8"))


def load_credentials():
    """
    Credentials come from two sources (env vars take priority — used by GitHub Actions):
      - YOUTUBE_API_KEY, X_BEARER_TOKEN, META_SYSTEM_TOKEN, DISCORD_BOT_TOKEN
      - smilegate-sns-credentials.yaml (local dev only, gitignored)
    """
    creds = {}
    if CRED_FILE.exists():
        with open(CRED_FILE, "r", encoding="utf-8") as f:
            creds = yaml.safe_load(f) or {}
    # Environment variables override / supplement the YAML
    env_map = {
        ("YOUTUBE_API_KEY",    "youtube",  "api_key"),
        ("X_BEARER_TOKEN",     "x",        "bearer_token"),
        ("META_SYSTEM_TOKEN",  "meta",     "system_token"),
        ("DISCORD_BOT_TOKEN",  "discord",  "bot_token"),
    }
    for env_name, section, key in env_map:
        val = os.environ.get(env_name)
        if val:
            creds.setdefault(section, {})[key] = val
    if not creds:
        log(f"WARN: no credentials found (no YAML, no env vars)")
    return creds


# ==================================================================
# YouTube Data API v3
# ==================================================================
def yt_resolve_handle(handle, api_key):
    """
    Resolve @handle → channel ID + statistics in one call.
    Docs: https://developers.google.com/youtube/v3/docs/channels/list
    """
    h = handle.lstrip("@")
    url = (
        "https://www.googleapis.com/youtube/v3/channels?"
        + urllib.parse.urlencode({
            "part": "snippet,statistics",
            "forHandle": "@" + h,
            "key": api_key,
        })
    )
    data = http_get_json(url)
    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"handle '{handle}' not found")
    return items[0]


def yt_fetch_by_id(channel_id, api_key):
    url = (
        "https://www.googleapis.com/youtube/v3/channels?"
        + urllib.parse.urlencode({
            "part": "snippet,statistics",
            "id": channel_id,
            "key": api_key,
        })
    )
    data = http_get_json(url)
    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"channel id '{channel_id}' not found")
    return items[0]


def yt_latest_video(channel_id, api_key):
    """Best-effort — returns {title, publishedAt, videoId} or None."""
    try:
        url = (
            "https://www.googleapis.com/youtube/v3/search?"
            + urllib.parse.urlencode({
                "part": "snippet",
                "channelId": channel_id,
                "order": "date",
                "maxResults": 1,
                "type": "video",
                "key": api_key,
            })
        )
        data = http_get_json(url)
        items = data.get("items") or []
        if not items:
            return None
        it = items[0]
        return {
            "title":       it["snippet"]["title"],
            "publishedAt": it["snippet"]["publishedAt"],
            "videoId":     it["id"].get("videoId"),
        }
    except Exception as e:
        log(f"WARN: latest video lookup failed for {channel_id}: {e}")
        return None


def fetch_youtube_for_channel(ch, api_key):
    """Populate ch with statistics. Returns (ok: bool, error: str|None)."""
    try:
        item = yt_fetch_by_id(ch["yt_id"], api_key) if "yt_id" in ch \
               else yt_resolve_handle(ch["yt_handle"], api_key)
        stats = item.get("statistics", {})
        snip  = item.get("snippet", {})
        ch["yt_id"]         = item["id"]
        ch["title"]         = snip.get("title")
        ch["thumbnail"]     = (snip.get("thumbnails", {}).get("default") or {}).get("url")
        ch["followers"]     = int(stats.get("subscriberCount", 0)) if stats.get("subscriberCount") else None
        ch["viewCount"]     = int(stats.get("viewCount", 0))       if stats.get("viewCount")       else None
        ch["videoCount"]    = int(stats.get("videoCount", 0))      if stats.get("videoCount")      else None
        ch["latestVideo"]   = yt_latest_video(item["id"], api_key)
        return True, None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return False, f"HTTP {e.code}: {body}"
    except Exception as e:
        return False, str(e)


# ==================================================================
# Instagram Graph API (via Meta system-user token)
#   Docs: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api
#   Endpoints used:
#     GET /{ig-user-id}?fields=followers_count,media_count,username,profile_picture_url
#     GET /{ig-user-id}/media?fields=id,caption,media_type,thumbnail_url,media_url,
#                                    permalink,timestamp,like_count,comments_count&limit=10
# ==================================================================
IG_API_VERSION = "v21.0"

def fetch_instagram_for_channel(ch, token):
    """Populate ch from Instagram Graph API. Returns (ok, error|None)."""
    ig_id = ch.get("ig_business_id")
    if not ig_id:
        return False, "ig_business_id missing"
    try:
        # --- 1. Account-level stats ---
        acct_url = (
            f"https://graph.facebook.com/{IG_API_VERSION}/{ig_id}?"
            + urllib.parse.urlencode({
                "fields": "followers_count,media_count,username,profile_picture_url,name,biography",
                "access_token": token,
            })
        )
        acct = http_get_json(acct_url)
        followers = acct.get("followers_count")
        if followers is None:
            return False, "no followers_count in response (check insights permission)"
        ch["followers"]   = int(followers)
        ch["mediaCount"]  = int(acct.get("media_count") or 0)
        ch["igUsername"]  = acct.get("username")
        ch["thumbnail"]   = acct.get("profile_picture_url")
        ch["title"]       = acct.get("name") or acct.get("username")

        # --- 2. Recent 10 media ---
        media_url = (
            f"https://graph.facebook.com/{IG_API_VERSION}/{ig_id}/media?"
            + urllib.parse.urlencode({
                "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count",
                "limit": 10,
                "access_token": token,
            })
        )
        try:
            media = http_get_json(media_url)
            items = media.get("data") or []
        except Exception as e:
            log(f"    WARN: IG media list failed for {ig_id}: {e}")
            items = []

        if items:
            latest = items[0]
            caption = (latest.get("caption") or "").strip()
            # Trim long captions; keep first line or 150 chars
            first_line = caption.split("\n", 1)[0]
            ch["latestPost"] = {
                "caption":     first_line[:150],
                "timestamp":   latest.get("timestamp"),
                "likeCount":   latest.get("like_count"),
                "commentCount": latest.get("comments_count"),
                "permalink":   latest.get("permalink"),
                "mediaType":   latest.get("media_type"),
                # Images use media_url, videos use thumbnail_url
                "thumbnailUrl": latest.get("thumbnail_url") or latest.get("media_url"),
            }
            # Average engagement across last 10 posts
            likes_sum    = sum(int(m.get("like_count") or 0)     for m in items)
            comments_sum = sum(int(m.get("comments_count") or 0) for m in items)
            ch["recentAvgLikes"]    = likes_sum // len(items)
            ch["recentAvgComments"] = comments_sum // len(items)
            ch["recentSampleSize"]  = len(items)
        return True, None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return False, f"HTTP {e.code}: {body}"
    except Exception as e:
        return False, str(e)


# ==================================================================
# Facebook Graph API (via Meta system-user token — same token as Instagram)
#   Docs: https://developers.facebook.com/docs/graph-api/reference/page/
#   Endpoints used:
#     GET /{page-id}?fields=name,followers_count,fan_count,picture{data{url}}
#     GET /{page-id}/posts?fields=id,message,created_time,permalink_url,
#                                 full_picture,reactions.summary(total_count),
#                                 comments.summary(total_count),shares&limit=10
#   Notes:
#     - followers_count is preferred; fan_count (Page Likes) is legacy fallback.
#     - /posts endpoint returns posts by the Page itself (no user tagging).
# ==================================================================
def fetch_facebook_for_channel(ch, token):
    """Populate ch from Facebook Graph API. Returns (ok, error|None)."""
    page_id = ch.get("fb_page_id")
    if not page_id:
        return False, "fb_page_id missing"
    try:
        # --- 1. Page-level stats ---
        page_url = (
            f"https://graph.facebook.com/{IG_API_VERSION}/{page_id}?"
            + urllib.parse.urlencode({
                "fields": "name,followers_count,fan_count,picture.width(120).height(120){url}",
                "access_token": token,
            })
        )
        page = http_get_json(page_url)
        followers = page.get("followers_count")
        if followers is None:
            followers = page.get("fan_count")  # legacy fallback
        if followers is None:
            return False, "no followers_count/fan_count in response (check page permissions)"
        ch["followers"] = int(followers)
        ch["title"]     = page.get("name")
        pic = (page.get("picture") or {}).get("data") or {}
        ch["thumbnail"] = pic.get("url")

        # --- 2. Recent 10 posts ---
        posts_url = (
            f"https://graph.facebook.com/{IG_API_VERSION}/{page_id}/posts?"
            + urllib.parse.urlencode({
                "fields": "id,message,created_time,permalink_url,full_picture,"
                          "reactions.summary(total_count),comments.summary(total_count),shares",
                "limit": 10,
                "access_token": token,
            })
        )
        try:
            posts = http_get_json(posts_url)
            items = posts.get("data") or []
        except Exception as e:
            log(f"    WARN: FB posts list failed for {page_id}: {e}")
            items = []

        if items:
            latest = items[0]
            msg = (latest.get("message") or "").strip()
            first_line = msg.split("\n", 1)[0] if msg else ""
            reactions_total = ((latest.get("reactions") or {}).get("summary") or {}).get("total_count")
            comments_total  = ((latest.get("comments")  or {}).get("summary") or {}).get("total_count")
            shares_total    = (latest.get("shares") or {}).get("count") if latest.get("shares") else 0
            ch["latestPost"] = {
                "caption":      first_line[:150],
                "timestamp":    latest.get("created_time"),
                "likeCount":    reactions_total,
                "commentCount": comments_total,
                "shareCount":   shares_total,
                "permalink":    latest.get("permalink_url"),
                "thumbnailUrl": latest.get("full_picture"),
            }
            # Average across recent posts
            likes_sum = sum(((p.get("reactions") or {}).get("summary") or {}).get("total_count") or 0
                            for p in items)
            comments_sum = sum(((p.get("comments") or {}).get("summary") or {}).get("total_count") or 0
                               for p in items)
            ch["recentAvgLikes"]    = likes_sum // len(items)
            ch["recentAvgComments"] = comments_sum // len(items)
            ch["recentSampleSize"]  = len(items)
        return True, None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return False, f"HTTP {e.code}: {body}"
    except Exception as e:
        return False, str(e)


# ==================================================================
# Discord — public Invite API (no auth required, no bot token needed)
#   https://discord.com/developers/docs/resources/invite#get-invite
#   GET /invites/{code}?with_counts=true
#   Returns: approximate_member_count (total), approximate_presence_count (online)
# ==================================================================
def fetch_discord_for_channel(ch):
    """Populate ch using the public invite endpoint. Returns (ok, error|None)."""
    code = ch.get("invite_code")
    if not code:
        return False, "invite_code missing"
    try:
        url = f"https://discord.com/api/v10/invites/{urllib.parse.quote(code)}?with_counts=true&with_expiration=true"
        data = http_get_json(url)
        guild = data.get("guild") or {}
        total  = data.get("approximate_member_count")
        online = data.get("approximate_presence_count")
        ch["followers"]    = int(total) if total is not None else None
        ch["onlineCount"]  = int(online) if online is not None else None
        ch["guildName"]    = guild.get("name")
        ch["guildId"]      = guild.get("id")
        if guild.get("icon") and guild.get("id"):
            ch["guildIcon"] = f"https://cdn.discordapp.com/icons/{guild['id']}/{guild['icon']}.png?size=64"
        if not ch["followers"]:
            return False, "no member count in response (invite may be expired or counts disabled)"
        return True, None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        return False, f"HTTP {e.code}: {body}"
    except Exception as e:
        return False, str(e)


# ==================================================================
# History tracking (for trend graphs)
# ==================================================================
def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"entries": []}  # each entry: {date, channels: {game:platform:region: followers}}


def save_history(hist, today_data):
    """Append today's entry and trim to last 90 days."""
    channels_flat = {}
    for g in today_data["games_list"]:
        for c in g["channels"]:
            if c.get("followers") is not None:
                channels_flat[f"{g['id']}:{c['platform']}:{c['region']}"] = c["followers"]
    entry = {"date": today_data["snapshotDate"], "channels": channels_flat}

    # Remove any existing entry for today, then append
    hist["entries"] = [e for e in hist.get("entries", []) if e.get("date") != entry["date"]]
    hist["entries"].append(entry)
    hist["entries"].sort(key=lambda e: e["date"])

    cutoff = (date.today() - timedelta(days=90)).isoformat()
    hist["entries"] = [e for e in hist["entries"] if e["date"] >= cutoff]

    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


def series_for(hist, game_id, platform, region):
    key = f"{game_id}:{platform}:{region}"
    return [(e["date"], e["channels"].get(key)) for e in hist.get("entries", [])
            if e["channels"].get(key) is not None]


# ==================================================================
# HTML template — standalone dashboard with data baked in.
# ==================================================================
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Smilegate Games — Social Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.js"></script>
<style>
:root { color-scheme: light; --bg:#F7F8FA; --surface:#FFFFFF; --border:#ECEEF1; --text:#0E1013; --text-2:#3A3F47; --muted:#6B7280; --muted-2:#9CA3AF; --pos:#12A150; --neg:#E11D48; --yt:#FF0033; --x:#000; --ig-a:#F58529; --ig-b:#DD2A7B; --ig-c:#8134AF; --fb:#1877F2; --dc:#5865F2; --shadow-sm:0 1px 2px rgba(15,17,22,.04), 0 0 0 1px rgba(15,17,22,.04); }
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Noto Sans KR", sans-serif; background: var(--bg); color: var(--text); -webkit-font-smoothing: antialiased; line-height: 1.4; }
a { color: inherit; text-decoration: none; }
.page { max-width: 1240px; margin: 0 auto; padding: 28px 24px 72px; }
header.top { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.brand .eyebrow { font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
.header-right { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }
.owner-tag { font-size: 11px; color: var(--muted); letter-spacing: 0.01em; }
.owner-tag b { color: var(--text-2); font-weight: 600; }
.chip-row { display: flex; align-items: center; }
.brand h1 { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; margin-top: 6px; }
.brand p.sub { font-size: 13px; color: var(--muted); margin-top: 4px; }
.meta-chip { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px; background: var(--surface); border: 1px solid var(--border); font-size: 12px; color: var(--text-2); font-weight: 500; }
.meta-chip .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--pos); }
.meta-chip.part .dot { background: #F59E0B; }
.banner { padding: 14px 16px; background: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 12px; font-size: 13px; color: #166534; margin-bottom: 24px; line-height: 1.55; }
.banner.warn { background: #FFF8E1; border-color: #F7D774; color: #6B4A05; }
.summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 28px; }
.stat { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px; box-shadow: var(--shadow-sm); }
.stat .label { font-size: 12px; color: var(--muted); font-weight: 500; margin-bottom: 8px; }
.stat .value { font-size: 24px; font-weight: 700; letter-spacing: -0.015em; }
.stat .sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
.game-block { margin-bottom: 40px; }
.game-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; gap: 16px; flex-wrap: wrap; }
.game-title { display: flex; align-items: center; gap: 12px; }
.game-title .swatch { width: 10px; height: 28px; border-radius: 3px; }
.game-title h2 { font-size: 20px; font-weight: 700; letter-spacing: -0.015em; }
.game-title .ko { font-size: 13px; color: var(--muted); margin-left: 2px; }
.game-meta { display: flex; gap: 18px; font-size: 12px; color: var(--muted); }
.game-meta b { color: var(--text); font-weight: 600; }
.trend-card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 18px 20px 12px; margin-bottom: 16px; box-shadow: var(--shadow-sm); }
.trend-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.trend-head h3 { font-size: 13px; font-weight: 600; color: var(--text-2); }
.legend { display: flex; gap: 12px; flex-wrap: wrap; }
.legend-item { font-size: 11px; color: var(--muted); display: inline-flex; align-items: center; gap: 5px; }
.legend-item .sw { width: 10px; height: 3px; border-radius: 2px; }
.trend-canvas-wrap { position: relative; height: 160px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 12px; }
.channel { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 16px; display: flex; flex-direction: column; gap: 12px; box-shadow: var(--shadow-sm); position: relative; transition: transform .15s, box-shadow .15s; }
.channel:hover { transform: translateY(-1px); box-shadow: 0 4px 14px rgba(15,17,22,.06), 0 0 0 1px rgba(15,17,22,.04); }
.channel.pending { background: repeating-linear-gradient(45deg,#FAFAFA,#FAFAFA 8px,#F3F4F6 8px,#F3F4F6 16px); }
.channel.missing { background: repeating-linear-gradient(45deg,#FAFAFA,#FAFAFA 8px,#F3F4F6 8px,#F3F4F6 16px); border-style: dashed; }
.channel-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.platform { display: inline-flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 600; color: var(--text-2); }
.platform .plogo { width: 20px; height: 20px; border-radius: 5px; display: inline-flex; align-items: center; justify-content: center; color: #fff; }
.plogo.yt { background: var(--yt); }
.plogo.x  { background: var(--x); }
.plogo.ig { background: linear-gradient(135deg, var(--ig-a), var(--ig-b) 55%, var(--ig-c)); }
.plogo.fb { background: var(--fb); }
.plogo.dc { background: var(--dc); }
.channel-head .ext { color: var(--muted-2); padding: 4px; border-radius: 6px; }
.channel-head .ext:hover { background: var(--bg); color: var(--text); }
.handle { font-size: 12px; color: var(--muted); word-break: break-all; line-height: 1.35; }
.handle a:hover { text-decoration: underline; color: var(--text-2); }
.metric-row { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.follower-num { font-size: 22px; font-weight: 700; letter-spacing: -0.015em; }
.follower-num small { font-size: 11px; font-weight: 500; color: var(--muted); margin-left: 4px; }
.delta-chip { font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 999px; display: inline-flex; align-items: center; gap: 3px; }
.delta-chip.up { color: var(--pos); background: #E8F7EE; }
.delta-chip.down { color: var(--neg); background: #FDE7ED; }
.delta-chip.flat { color: var(--muted); background: #F1F2F4; }
.delta-chip.nil { color: var(--muted); background: transparent; border: 1px dashed var(--border); font-weight: 500; }
.spark-wrap { height: 36px; position: relative; }
.subnote { font-size: 11px; color: var(--muted); padding-top: 8px; border-top: 1px dashed var(--border); }
.subnote b { color: var(--text-2); }
.subnote-latest { display: flex; align-items: baseline; gap: 6px; white-space: nowrap; overflow: hidden; }
.subnote-latest .title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1 1 auto; min-width: 0; }
.subnote-latest .ago { flex: 0 0 auto; color: var(--muted); }
.missing-label { font-size: 12px; color: var(--muted); text-align: center; padding: 16px 4px; border: 1px dashed #DDE0E5; border-radius: 8px; background: #fff; }
.missing-label b { color: #92400E; }
.pending-label { font-size: 12px; color: var(--muted); text-align: center; padding: 8px 4px; }
footer.note { margin-top: 32px; padding: 14px 0; font-size: 12px; color: var(--muted); border-top: 1px solid var(--border); display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
</style>
</head>
<body>
<div class="page">
  <header class="top">
    <div class="brand">
      <h1>Game Social Dashboard</h1>
      <p class="sub">Epic Seven · Chaos Zero Nightmare · Lord Nine — official channels across YouTube, X, Instagram, Facebook, Discord.</p>
    </div>
    <div class="header-right">
      <div class="owner-tag">Managed by <b>SGP Contents Marketing Team</b></div>
      <div class="chip-row">
        <span class="meta-chip __ALLLIVE_CLASS__">
          <span class="dot"></span> __HEADER_STATUS__
        </span>
        <span class="meta-chip" style="margin-left:8px;">Updated __TODAY__</span>
      </div>
    </div>
  </header>

  __BANNER__
  __SUMMARY__
  __GAMES__

  <footer class="note">
    <span>© Smilegate Content Marketing Team · Pulled by fetch_social_stats.py</span>
    <span>Data source: __SOURCE_LINE__</span>
  </footer>
</div>

<script>
const DATA = __DATA_JSON__;

function fmtNum(n) {
  if (n === null || n === undefined) return '—';
  if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 1 : 2) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 1 : 2) + 'K';
  return String(n);
}

const PLATFORM_COLORS = { youtube:'#FF0033', x:'#111111', instagram:'#DD2A7B', facebook:'#1877F2', discord:'#5865F2' };

function drawSparklines() {
  document.querySelectorAll('canvas[data-series]').forEach(el => {
    let pts = [];
    try { pts = JSON.parse(el.dataset.series); } catch(e){}
    if (pts.length < 2) { el.style.display = 'none'; return; }
    const color = el.dataset.color || '#111';
    new Chart(el, {
      type: 'line',
      data: { labels: pts.map((_,i)=>i), datasets: [{ data: pts, borderColor: color, backgroundColor:'transparent', borderWidth:1.75, pointRadius:0, tension:0.35 }] },
      options: { responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false},tooltip:{enabled:false}}, scales:{x:{display:false},y:{display:false}}, animation:false }
    });
  });
}

function drawTrendCharts() {
  (DATA.trendCharts || []).forEach(tc => {
    const el = document.getElementById(tc.canvasId);
    if (!el) return;
    const datasets = tc.datasets.map(ds => ({ label: ds.label, data: ds.data, borderColor: ds.color, backgroundColor:'transparent', borderWidth:2, pointRadius:0, pointHoverRadius:4, tension:0.3 }));
    new Chart(el, {
      type: 'line',
      data: { labels: tc.labels, datasets },
      options: {
        responsive:true, maintainAspectRatio:false,
        plugins: { legend:{display:false}, tooltip: { mode:'index', intersect:false, backgroundColor:'#111', padding:10, cornerRadius:8, callbacks: { label: ctx => `${ctx.dataset.label}: ${fmtNum(ctx.parsed.y)}` } } },
        interaction: { mode:'index', intersect:false },
        scales: {
          x: { grid:{display:false}, ticks:{color:'#9CA3AF',font:{size:10}} },
          y: { grid:{color:'#F1F2F4',drawBorder:false}, ticks:{color:'#9CA3AF',font:{size:10}, callback:v=>fmtNum(v)} }
        }
      }
    });
  });
}

document.addEventListener('DOMContentLoaded', () => { drawSparklines(); drawTrendCharts(); });
</script>
</body>
</html>
"""


def fmt_num(n):
    if n is None:
        return "—"
    if n >= 1e6:
        return f"{n/1e6:.1f}M" if n >= 1e7 else f"{n/1e6:.2f}M"
    if n >= 1e3:
        return f"{n/1e3:.1f}K" if n >= 1e4 else f"{n/1e3:.2f}K"
    return str(n)


def fmt_signed(n):
    if n == 0 or n is None:
        return "±0" if n == 0 else "—"
    sign = "+" if n > 0 else ""
    return sign + fmt_num(n) if n > 0 else "-" + fmt_num(-n)


def delta_chip_html(delta):
    if delta is None:
        return '<span class="delta-chip nil">no history</span>'
    if delta > 0:
        return f'<span class="delta-chip up">▲ {fmt_signed(delta)}</span>'
    if delta < 0:
        return f'<span class="delta-chip down">▼ {fmt_signed(delta)}</span>'
    return '<span class="delta-chip flat">● ±0</span>'


def platform_icon_svg(p):
    icons = {
        "youtube":   '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M23 7.5s-.2-1.6-.9-2.3c-.8-.9-1.8-.9-2.2-1C16.4 4 12 4 12 4s-4.4 0-7.9.2c-.5.1-1.4.1-2.2 1C1.2 5.9 1 7.5 1 7.5S.8 9.4.8 11.3v1.7c0 1.9.2 3.8.2 3.8s.2 1.6.9 2.3c.8.9 1.9.9 2.4 1 1.7.2 7.7.2 7.7.2s4.4 0 7.9-.2c.5-.1 1.4-.1 2.2-1 .7-.7.9-2.3.9-2.3s.2-1.9.2-3.8v-1.7c0-1.9-.2-3.8-.2-3.8zM9.7 15.3V8.7l5.7 3.3-5.7 3.3z"/></svg>',
        "x":         '<svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2H21.5l-7.5 8.56L22.5 22h-6.875l-5.375-7.03L3.75 22H.5l8-9.13L0 2h7l4.875 6.43L18.244 2zm-1.2 18h1.9L7.05 4H5.05l11.994 16z"/></svg>',
        "instagram": '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor"/></svg>',
        "facebook":  '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M13 22v-8h3l1-4h-4V7.5C13 6.1 13.5 5 15.5 5H17V1.2c-.5-.1-1.7-.2-3-.2-3.1 0-5 1.9-5 5.2V10H6v4h3v8h4z"/></svg>',
        "discord":   '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M20.3 4.5A18 18 0 0 0 15.7 3l-.2.4a14 14 0 0 0-7 0L8.3 3a18 18 0 0 0-4.6 1.5A19 19 0 0 0 1 16.3a18 18 0 0 0 5.4 2.7l1-1.5a12 12 0 0 1-1.7-.8l.4-.3a13 13 0 0 0 11.8 0l.4.3a12 12 0 0 1-1.8.8l1 1.5a18 18 0 0 0 5.5-2.7 19 19 0 0 0-2.7-11.8zM8.5 14c-1 0-1.8-1-1.8-2.2s.8-2.2 1.8-2.2 1.8 1 1.8 2.2-.8 2.2-1.8 2.2zm7 0c-1 0-1.8-1-1.8-2.2s.8-2.2 1.8-2.2 1.8 1 1.8 2.2-.8 2.2-1.8 2.2z"/></svg>',
    }
    return icons.get(p, "")


PLATFORM_METRIC = {"youtube": "subscribers", "x": "followers", "instagram": "followers",
                   "facebook": "followers", "discord": "members"}

# CSS class suffix (matches .plogo.yt / .plogo.x / .plogo.ig / .plogo.fb / .plogo.dc in the template)
PLATFORM_CSS = {"youtube": "yt", "x": "x", "instagram": "ig",
                "facebook": "fb", "discord": "dc"}


def channel_card_html(game, ch, hist):
    platform = ch["platform"]
    region = ch["region"]

    if ch.get("missing"):
        return f"""
      <div class="channel missing">
        <div class="channel-head">
          <span class="platform"><span class="plogo {PLATFORM_CSS[platform]}">{platform_icon_svg(platform)}</span>{platform.title()} · {region}</span>
        </div>
        <div class="missing-label"><b>Not located</b><br><span style="font-size:11px;">{ch.get('note','Please confirm the official handle.')}</span></div>
      </div>"""

    if ch.get("followers") is None:
        # Pending credentials
        return f"""
      <div class="channel pending">
        <div class="channel-head">
          <span class="platform"><span class="plogo {PLATFORM_CSS[platform]}">{platform_icon_svg(platform)}</span>{platform.title()} · {region}</span>
          <a class="ext" href="{ch['url']}" target="_blank" rel="noopener">↗</a>
        </div>
        <div class="handle"><a href="{ch['url']}" target="_blank" rel="noopener">{ch['handle']}</a></div>
        <div class="pending-label">⋯ Awaiting API credentials</div>
      </div>"""

    series = series_for(hist, game["id"], platform, region)
    pts = [v for _, v in series[-14:]]
    delta_week = None
    if len(series) >= 2:
        for d, v in reversed(series[:-1]):
            # pick the entry ≥ 6 days before today
            try:
                d_date = date.fromisoformat(d)
                if (date.today() - d_date).days >= 6:
                    delta_week = ch["followers"] - v
                    break
            except Exception:
                pass
    series_json = json.dumps(pts)

    meta_metric = PLATFORM_METRIC.get(platform, "followers")
    spark_color = {"youtube":"#FF0033","x":"#111","instagram":"#DD2A7B","facebook":"#1877F2","discord":"#5865F2"}.get(platform, "#111")

    # Latest video line (YouTube only for now)
    sub_note = ""
    if platform == "youtube" and ch.get("latestVideo"):
        lv = ch["latestVideo"]
        try:
            pub = datetime.fromisoformat(lv["publishedAt"].replace("Z","+00:00"))
            hours = (datetime.now(pub.tzinfo) - pub).total_seconds() / 3600
            ago = f"{int(hours)}h ago" if hours < 24 else f"{int(hours/24)}d ago"
        except Exception:
            ago = ""
        title_safe = (lv["title"] or "").replace("<","&lt;").replace(">","&gt;")
        sub_note = (
            f'<div class="subnote subnote-latest" title="{title_safe}">'
            f'<b>Latest:</b>'
            f'<span class="title">{title_safe}</span>'
            f'<span class="ago">{ago}</span>'
            f'</div>'
        )
    if platform == "youtube" and ch.get("videoCount"):
        sub_note += f'<div class="subnote" style="border-top:none;padding-top:4px;">{fmt_num(ch["videoCount"])} videos · {fmt_num(ch.get("viewCount"))} total views</div>'
    if platform in ("instagram", "facebook") and ch.get("latestPost"):
        lp = ch["latestPost"]
        try:
            pub = datetime.fromisoformat(lp["timestamp"].replace("Z","+00:00"))
            hours = (datetime.now(pub.tzinfo) - pub).total_seconds() / 3600
            ago = f"{int(hours)}h ago" if hours < 24 else f"{int(hours/24)}d ago"
        except Exception:
            ago = ""
        cap_safe = (lp.get("caption") or "").replace("<","&lt;").replace(">","&gt;") or "(no caption)"
        sub_note = (
            f'<div class="subnote subnote-latest" title="{cap_safe}">'
            f'<b>Latest:</b>'
            f'<span class="title">{cap_safe}</span>'
            f'<span class="ago">{ago}</span>'
            f'</div>'
        )
        like_emoji = "♥" if platform == "instagram" else "👍"
        likes     = lp.get("likeCount")
        comments  = lp.get("commentCount")
        shares    = lp.get("shareCount")  # FB only
        avg_likes = ch.get("recentAvgLikes")
        parts = []
        if likes is not None:
            parts.append(f"{like_emoji} {fmt_num(likes)}")
        if comments is not None:
            parts.append(f"💬 {fmt_num(comments)}")
        if shares is not None and shares > 0:
            parts.append(f"↗ {fmt_num(shares)}")
        if avg_likes is not None and ch.get("recentSampleSize"):
            parts.append(f"avg {like_emoji} {fmt_num(avg_likes)}/post")
        if parts:
            sub_note += f'<div class="subnote" style="border-top:none;padding-top:4px;">{" · ".join(parts)}</div>'
    if platform == "instagram" and ch.get("mediaCount") and not ch.get("latestPost"):
        sub_note += f'<div class="subnote" style="border-top:none;padding-top:4px;">{fmt_num(ch["mediaCount"])} posts</div>'
    if platform == "discord" and ch.get("onlineCount") is not None:
        guild_name = ch.get("guildName") or ""
        sub_note = f'<div class="subnote"><b>Online:</b> {fmt_num(ch["onlineCount"])}<span style="float:right;color:var(--muted);">{guild_name[:30]}</span></div>'

    return f"""
      <div class="channel">
        <div class="channel-head">
          <span class="platform"><span class="plogo {PLATFORM_CSS[platform]}">{platform_icon_svg(platform)}</span>{platform.title()} · {region}</span>
          <a class="ext" href="{ch['url']}" target="_blank" rel="noopener" aria-label="Open">↗</a>
        </div>
        <div class="handle"><a href="{ch['url']}" target="_blank" rel="noopener">{ch['handle']}</a></div>
        <div class="metric-row">
          <div class="follower-num">{fmt_num(ch["followers"])}<small>{meta_metric}</small></div>
          {delta_chip_html(delta_week)}
        </div>
        <div class="spark-wrap"><canvas data-series='{series_json}' data-color="{spark_color}"></canvas></div>
        {sub_note}
      </div>"""


def build_html(snapshot, hist):
    # Summary numbers
    live_channels = [(g, c) for g in snapshot["games_list"] for c in g["channels"] if c.get("followers") is not None]
    total = sum(c["followers"] for _, c in live_channels)
    channel_count = sum(len(g["channels"]) for g in snapshot["games_list"])
    missing = sum(1 for g in snapshot["games_list"] for c in g["channels"] if c.get("missing"))
    pending = sum(1 for g in snapshot["games_list"] for c in g["channels"]
                  if not c.get("missing") and c.get("followers") is None)
    connected_platforms = sorted({c["platform"] for _, c in live_channels})

    # Game sections
    game_blocks = []
    trend_charts = []
    for g in snapshot["games_list"]:
        game_total = sum(c["followers"] for c in g["channels"] if c.get("followers") is not None)

        # trend chart data (sum per platform across this game)
        # find all dates present in history
        dates_in_hist = sorted({e["date"] for e in hist.get("entries", [])})
        by_platform = {}
        for c in g["channels"]:
            if c.get("followers") is None or c.get("missing"):
                continue
            ser = dict(series_for(hist, g["id"], c["platform"], c["region"]))
            if not ser:
                continue
            if c["platform"] not in by_platform:
                by_platform[c["platform"]] = {d: 0 for d in dates_in_hist}
            for d in dates_in_hist:
                if d in ser:
                    by_platform[c["platform"]][d] += ser[d]

        tc_datasets = [
            {"label": p.title(), "color": {"youtube":"#FF0033","x":"#111","instagram":"#DD2A7B","facebook":"#1877F2","discord":"#5865F2"}[p],
             "data": [by_platform[p].get(d) for d in dates_in_hist]}
            for p in by_platform
        ]
        canvas_id = f"trend-{g['id']}"
        trend_charts.append({"canvasId": canvas_id, "labels": dates_in_hist, "datasets": tc_datasets})

        cards_html = "".join(channel_card_html(g, c, hist) for c in g["channels"])
        legend = "".join(
            f'<span class="legend-item"><span class="sw" style="background:{ds["color"]}"></span>{ds["label"]}</span>'
            for ds in tc_datasets
        )
        trend_card = (
            f'<div class="trend-card"><div class="trend-head"><h3>Follower trend</h3>'
            f'<div class="legend">{legend}</div></div>'
            f'<div class="trend-canvas-wrap"><canvas id="{canvas_id}"></canvas></div></div>'
            if tc_datasets else ""
        )

        game_blocks.append(f"""
      <section class="game-block">
        <div class="game-header">
          <div class="game-title"><span class="swatch" style="background:{g['color']}"></span><h2>{g['name']}</h2><span class="ko">{g['ko']}</span></div>
          <div class="game-meta"><span><b>{len(g['channels'])}</b> channels</span><span><b>{fmt_num(game_total)}</b> followers</span></div>
        </div>
        {trend_card}
        <div class="grid">{cards_html}</div>
      </section>""")

    summary_html = f"""
      <section class="summary">
        <div class="stat"><div class="label">Total followers (live)</div><div class="value">{fmt_num(total)}</div><div class="sub">{len(live_channels)} of {channel_count} channels reporting</div></div>
        <div class="stat"><div class="label">Connected platforms</div><div class="value" style="font-size:17px;">{', '.join([p.title() for p in connected_platforms]) or '—'}</div><div class="sub">{5 - len(connected_platforms)} platform(s) pending credentials</div></div>
        <div class="stat"><div class="label">Channels tracked</div><div class="value">{channel_count}</div><div class="sub">{missing} unconfirmed · {pending} awaiting keys</div></div>
        <div class="stat"><div class="label">Last refresh</div><div class="value" style="font-size:17px;">{TODAY}</div><div class="sub">{NOW_ISO[11:16]} local</div></div>
      </section>"""

    all_live = pending == 0 and missing == 0
    header_status_class = "" if all_live else "part"
    header_status_text = "All platforms live" if all_live else f"{len(connected_platforms)} of 5 platforms live"

    if pending > 0:
        pending_plats = sorted({c["platform"].title() for g in snapshot["games_list"] for c in g["channels"]
                                if not c.get("missing") and c.get("followers") is None})
        banner = f'<div class="banner warn">✓ {len(connected_platforms)} platform(s) live. {pending} channel(s) across {" / ".join(pending_plats)} still awaiting API credentials — see <b>API_setup_guide.md</b> for each platform\'s setup.</div>'
    elif all_live:
        banner = f'<div class="banner">✓ All {len(live_channels)} channels reporting live data.</div>'
    else:
        banner = ""

    source_line = ", ".join(
        [f"{p.title()} API" for p in connected_platforms]
    ) or "no live sources"

    html = HTML_TEMPLATE
    html = html.replace("__TODAY__", TODAY)
    html = html.replace("__HEADER_STATUS__", header_status_text)
    html = html.replace("__ALLLIVE_CLASS__", header_status_class)
    html = html.replace("__BANNER__", banner)
    html = html.replace("__SUMMARY__", summary_html)
    html = html.replace("__GAMES__", "".join(game_blocks))
    html = html.replace("__SOURCE_LINE__", source_line)
    html = html.replace("__DATA_JSON__", json.dumps({"trendCharts": trend_charts}, ensure_ascii=False))
    return html


# ==================================================================
# Main
# ==================================================================
def main():
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    creds = load_credentials()

    errors = []
    platforms_pending = []
    credential_status = {}

    # -------- YouTube --------
    yt_key = (creds.get("youtube") or {}).get("api_key")
    if yt_key:
        credential_status["youtube"] = {"configured": True}
        log("YouTube: API key loaded — fetching 5 channels")
        for g in GAMES:
            for c in g["channels"]:
                if c["platform"] != "youtube":
                    continue
                ok, err = fetch_youtube_for_channel(c, yt_key)
                if ok:
                    log(f"  ✓ {g['id']}/{c['handle']} → {c.get('followers'):,} subs")
                else:
                    errors.append({"channel": f"{g['id']}/{c['handle']}", "error": err})
                    log(f"  ✗ {g['id']}/{c['handle']}: {err}")
                time.sleep(0.2)
    else:
        credential_status["youtube"] = {"configured": False, "note": "api_key not provisioned"}
        platforms_pending.append("youtube")

    # -------- X --------
    if not (creds.get("x") or {}).get("bearer_token"):
        credential_status["x"] = {"configured": False, "note": "bearer_token not provisioned"}
        platforms_pending.append("x")

    # -------- Instagram (via Meta Graph API system-user token) --------
    meta_token = (creds.get("meta") or {}).get("system_token")
    if meta_token:
        credential_status["instagram"] = {"configured": True, "method": "IG Graph API"}
        ig_channels = [(g, c) for g in GAMES for c in g["channels"]
                       if c["platform"] == "instagram" and c.get("ig_business_id")]
        if ig_channels:
            log(f"Instagram: fetching {len(ig_channels)} channel(s) via Graph API")
            for g, c in ig_channels:
                ok, err = fetch_instagram_for_channel(c, meta_token)
                if ok:
                    log(f"  ✓ {g['id']}/{c['handle']} → {c.get('followers'):,} followers "
                        f"({c.get('mediaCount', 0)} posts)")
                else:
                    errors.append({"channel": f"{g['id']}/{c['handle']}", "error": err})
                    log(f"  ✗ {g['id']}/{c['handle']}: {err}")
                time.sleep(0.3)  # be polite to Graph API
    else:
        credential_status["instagram"] = {"configured": False, "note": "META_SYSTEM_TOKEN not provisioned"}
        platforms_pending.append("instagram")

    # -------- Facebook (shares the Meta system-user token with Instagram) --------
    if meta_token:
        credential_status["facebook"] = {"configured": True, "method": "FB Graph API"}
        fb_channels = [(g, c) for g in GAMES for c in g["channels"]
                       if c["platform"] == "facebook" and c.get("fb_page_id")]
        if fb_channels:
            log(f"Facebook: fetching {len(fb_channels)} page(s) via Graph API")
            for g, c in fb_channels:
                ok, err = fetch_facebook_for_channel(c, meta_token)
                if ok:
                    log(f"  ✓ {g['id']}/{c['handle']} → {c.get('followers'):,} followers")
                else:
                    errors.append({"channel": f"{g['id']}/{c['handle']}", "error": err})
                    log(f"  ✗ {g['id']}/{c['handle']}: {err}")
                time.sleep(0.3)
    else:
        credential_status["facebook"] = {"configured": False, "note": "META_SYSTEM_TOKEN not provisioned"}
        platforms_pending.append("facebook")
    # -------- Discord (public invite API — no credentials needed) --------
    discord_channels = [(g, c) for g in GAMES for c in g["channels"]
                        if c["platform"] == "discord" and c.get("invite_code")]
    if discord_channels:
        credential_status["discord"] = {"configured": True, "method": "public invite API (no auth)"}
        log(f"Discord: fetching {len(discord_channels)} server(s) via invite API")
        for g, c in discord_channels:
            ok, err = fetch_discord_for_channel(c)
            if ok:
                log(f"  ✓ {g['id']}/{c['handle']} → {c.get('followers'):,} members ({c.get('onlineCount', 0):,} online)")
            else:
                errors.append({"channel": f"{g['id']}/{c['handle']}", "error": err})
                log(f"  ✗ {g['id']}/{c['handle']}: {err}")
            time.sleep(0.3)  # be kind to Discord's rate limit
    else:
        credential_status["discord"] = {"configured": False, "note": "no invite_code set on any discord channel"}
        platforms_pending.append("discord")

    # -------- Snapshot assembly --------
    snapshot = {
        "snapshotDate": TODAY,
        "runTimestamp": NOW_ISO,
        "credentialStatus": credential_status,
        "games": {g["id"]: {"name": g["name"], "ko": g["ko"], "channels": g["channels"]} for g in GAMES},
        "games_list": GAMES,
        "apiErrors": errors,
        "platformsPendingCredentials": platforms_pending,
    }

    # Save JSON snapshot (strip games_list to avoid duplicate)
    save_payload = {k: v for k, v in snapshot.items() if k != "games_list"}
    json_path = SNAPSHOTS / f"{TODAY}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(save_payload, f, ensure_ascii=False, indent=2)

    # Update history & generate HTML
    hist = load_history()
    save_history(hist, snapshot)
    hist = load_history()  # reload so today's entry is included

    html_o