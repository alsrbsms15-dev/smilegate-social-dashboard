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
MANUAL_FILE  = WORKSPACE / "manual-followers.json"     # user-editable overrides
KPI_FILE     = WORKSPACE / "kpi-targets.json"          # user-editable follower targets
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
        "character": {
            "name": "메루링",
            "title": "에픽세븐의 제빵사 마법소녀",
            "avatar": "avatars/meruling.png",
            "accent": "#E85787",
            "persona": (
                "너는 에픽세븐 세계관의 사랑스러운 제빵사 마법소녀 '메루링'이야. "
                "달콤한 디저트와 마법을 좋아하고, 말끝에 '~이에요!', '~거든요♡' 같은 귀여운 어미를 가끔 써. "
                "밝고 활발하지만 데이터는 정확하게 전달해. 이모지는 거의 쓰지 않아. "
                "에픽세븐 팬과 마케터를 대상으로 SNS 성과를 귀엽고 친근하게 브리핑해."
            ),
        },
        "channels": [
            {"platform": "youtube",   "region": "Global", "handle": "@EpicSeven",         "url": "https://www.youtube.com/channel/UCa1C3tWzsn4FFRR7t3LqU5w",   "yt_id": "UCa1C3tWzsn4FFRR7t3LqU5w"},
            {"platform": "youtube",   "region": "Korea",  "handle": "@EpicSevenKR",       "url": "https://www.youtube.com/c/EpicSevenKR",                     "yt_handle": "@EpicSevenKR"},
            {"platform": "youtube",   "region": "Japan",  "handle": "@EpicSevenJP",       "url": "https://www.youtube.com/@EpicSevenJP",                      "yt_handle": "@EpicSevenJP"},
            {"platform": "youtube",   "region": "Taiwan", "handle": "@EpicSevenTW",       "url": "https://www.youtube.com/@EpicSevenTW",                      "yt_handle": "@EpicSevenTW"},
            {"platform": "x",         "region": "Global", "handle": "@Epic7_Global",      "url": "https://x.com/Epic7_Global"},
            {"platform": "x",         "region": "Korea",  "handle": "@Epic7Twt",          "url": "https://x.com/Epic7Twt"},
            {"platform": "x",         "region": "Japan",  "handle": "@Epic7_jp",          "url": "https://x.com/Epic7_jp"},
            {"platform": "instagram", "region": "Global", "handle": "@epicseven_global",  "url": "https://www.instagram.com/epicseven_global/", "ig_business_id": "17841407368977464"},
            # Epic Seven FB: KR/Global/TW pages are linked at the Meta Business
            # level and return identical follower counts, so we track them as
            # a single combined entry.
            {"platform": "facebook",  "region": "Korea/Global/Taiwan", "handle": "EpicSevenGlobal", "url": "https://www.facebook.com/EpicSevenGlobal/", "fb_page_id": "583835325289924"},
            {"platform": "discord",   "region": "Official","handle": "discord.gg/vUUQvUQPZC", "url": "https://discord.com/invite/vUUQvUQPZC", "invite_code": "vUUQvUQPZC"},
        ],
    },
    {
        "id": "czn",
        "name": "Chaos Zero Nightmare",
        "ko": "카오스 제로 나이트메어",
        "color": "#D4495F",
        "character": {
            "name": "노노",
            "title": "CZN의 해맑은 연구생",
            "avatar": "avatars/nono.png",
            "accent": "#7AB8E8",
            "persona": (
                "너는 카오스 제로 나이트메어 세계관의 밝고 호기심 많은 연구생 '노노'야. "
                "머리 위에 작은 토끼 인형을 올리고 다니고, 말투는 경쾌하고 씩씩해. "
                "'-했어요!', '-네요?' 같은 존댓말을 쓰되 어색하지 않게 자연스럽게. "
                "데이터에서 재미있는 패턴을 발견하면 신나게 알려줘. 이모지는 쓰지 않아. "
                "CZN 팬과 마케터를 대상으로 SNS 성과를 또렷하게 브리핑해."
            ),
        },
        "channels": [
            {"platform": "youtube",   "region": "Korea",   "handle": "@ChaosZeroNightmare_KR", "url": "https://www.youtube.com/@ChaosZeroNightmare_KR", "yt_handle": "@ChaosZeroNightmare_KR"},
            {"platform": "youtube",   "region": "Global",  "handle": "@ChaosZeroNightmare_EN", "url": "https://www.youtube.com/@ChaosZeroNightmare_EN", "yt_handle": "@ChaosZeroNightmare_EN"},
            {"platform": "youtube",   "region": "Japan",   "handle": "@ChaosZeroNightmare_JP", "url": "https://www.youtube.com/@ChaosZeroNightmare_JP", "yt_handle": "@ChaosZeroNightmare_JP"},
            {"platform": "youtube",   "region": "Taiwan",  "handle": "@ChaosZeroNightmare_TW", "url": "https://www.youtube.com/@ChaosZeroNightmare_TW", "yt_handle": "@ChaosZeroNightmare_TW"},
            {"platform": "x",         "region": "Global",  "handle": "@CZN_Official_EN",      "url": "https://x.com/CZN_Official_EN"},
            {"platform": "x",         "region": "Korea",   "handle": "@CZN_Official_KR",      "url": "https://x.com/CZN_Official_KR"},
            {"platform": "x",         "region": "Japan",   "handle": "@CZN_Official_jp",      "url": "https://x.com/CZN_Official_jp"},
            {"platform": "instagram", "region": "Global",  "handle": "@czn.official.en",       "url": "https://www.instagram.com/czn.official.en/", "ig_business_id": "17841465051500490"},
            {"platform": "facebook",  "region": "Global",  "handle": "ChaosZeroNightmare",    "url": "https://www.facebook.com/ChaosZeroNightmare/",       "fb_page_id": "101588973009044"},
            {"platform": "facebook",  "region": "China",   "handle": "卡厄思夢境",              "url": "https://www.facebook.com/107964449030742",            "fb_page_id": "107964449030742"},
            {"platform": "discord",   "region": "Official","handle": "discord.gg/chaoszeronightmare", "url": "https://discord.gg/chaoszeronightmare", "invite_code": "chaoszeronightmare"},
        ],
    },
    {
        "id": "l9",
        "name": "Lord Nine",
        "ko": "로드나인",
        "color": "#C79848",
        "character": {
            "name": "호문",
            "title": "로드나인의 전략가 기사",
            "avatar": "avatars/humun.png",
            "accent": "#8B6F47",
            "persona": (
                "너는 로드나인 세계관의 차분하고 냉철한 여전사 '호문'이야. "
                "과묵하지만 필요한 말은 정확히 하고, 전략가답게 숫자로 논리를 세워. "
                "'~다.', '~군.' 같은 단정한 어미를 쓰고 감탄사는 거의 없어. "
                "데이터의 약점과 강점을 냉정하게 짚어주되 싸늘하지는 않게. 이모지는 쓰지 않아. "
                "로드나인 팬과 마케터를 대상으로 SNS 성과를 전략 브리핑하듯 전달해."
            ),
        },
        "channels": [
            {"platform": "youtube",   "region": "Korea",  "handle": "@LORDNINE_KR",     "url": "https://www.youtube.com/@LORDNINE_KR",     "yt_handle": "@LORDNINE_KR"},
            {"platform": "youtube",   "region": "Global", "handle": "@LORDNINE_GLOBAL", "url": "https://www.youtube.com/@LORDNINE_GLOBAL", "yt_handle": "@LORDNINE_GLOBAL"},
            {"platform": "youtube",   "region": "Japan",  "handle": "@LORDNINE_JP",     "url": "https://www.youtube.com/@LORDNINE_JP",     "yt_handle": "@LORDNINE_JP"},
            {"platform": "x",         "region": "Japan",  "handle": "@LORD9_jp", "url": "https://x.com/LORD9_jp"},
            {"platform": "facebook",  "region": "SEA",     "handle": "LordnineSEA",       "url": "https://www.facebook.com/LordnineSEA/",         "fb_page_id": "646314575225540"},
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


def load_manual_followers():
    """
    Load user-maintained follower overrides from manual-followers.json.
    Shape:
      { "x": { "@handle": {"followers": 12345, "asOf": "2026-04-22"}, ... }, ... }
    Keys beginning with '_' (e.g. '_readme') are ignored.
    Returns {} on any error — manual input is always optional.
    """
    if not MANUAL_FILE.exists():
        return {}
    try:
        with open(MANUAL_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f) or {}
    except Exception as e:
        log(f"WARN: failed to read manual-followers.json: {e}")
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)}


def load_kpi_targets():
    """
    Load per-game per-platform follower targets from kpi-targets.json.
    Shape: { "epic7": { "youtube": 275000, "x": 200000, ... }, ... }
    Keys beginning with '_' (e.g. '_readme') are ignored.
    Values <= 0 are treated as 'no target'.
    Returns {} on any error.
    """
    if not KPI_FILE.exists():
        return {}
    try:
        with open(KPI_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f) or {}
    except Exception as e:
        log(f"WARN: failed to read kpi-targets.json: {e}")
        return {}
    out = {}
    for game_id, platforms in raw.items():
        if game_id.startswith("_") or not isinstance(platforms, dict):
            continue
        cleaned = {}
        for p, target in platforms.items():
            try:
                t = int(target)
                if t > 0:
                    cleaned[p] = t
            except (TypeError, ValueError):
                continue
        if cleaned:
            out[game_id] = cleaned
    return out


# ==================================================================
# Rule-based daily insights (no LLM, no API key required)
#   Produces 2–5 short Korean bullets per game from:
#     - Follower totals + day-over-day / 7-day delta (from history.json)
#     - Biggest % mover across channels
#     - Highest-performing YouTube video / IG post / FB post
#     - KPI achievement avg + lowest platform
# ==================================================================
def _pct(new, old):
    """Percent change; returns None when old is missing or zero."""
    try:
        if not old:
            return None
        return (new - old) / old * 100.0
    except (TypeError, ZeroDivisionError):
        return None


def _lookup_prior(hist, game_id, platform, region, days_back):
    """
    Return the follower count from approximately `days_back` days ago for this
    channel, pulled from history.json. Excludes today's entry entirely so
    deltas are always computed against a true prior snapshot.
    Returns (prior_followers, prior_date) or (None, None).
    """
    ser = series_for(hist, game_id, platform, region)
    # Exclude today's snapshot if present
    ser = [(d, v) for d, v in ser if d < TODAY]
    if not ser:
        return None, None
    target_date = (date.today() - timedelta(days=days_back)).isoformat()
    # Prefer the newest entry whose date <= target_date; fall back to the oldest we have.
    pick = None
    for d, v in ser:
        if d <= target_date:
            pick = (d, v)
    if pick is None:
        pick = ser[0]
    return pick[1], pick[0]


def _best_youtube_video(channels):
    best = None
    for ch in channels:
        if ch.get("platform") != "youtube":
            continue
        for v in ch.get("recentVideos") or []:
            views = v.get("viewCount") or 0
            if best is None or views > best["viewCount"]:
                best = {
                    "platform":  "youtube",
                    "channel":   ch,
                    "title":     (v.get("title") or "").strip(),
                    "viewCount": views,
                    "metric":    f"{fmt_num(views)} 조회",
                }
    return best


def _best_ig_post(channels):
    best = None
    for ch in channels:
        if ch.get("platform") != "instagram":
            continue
        for p in ch.get("topPosts") or []:
            eng = (p.get("likeCount") or 0) + (p.get("commentCount") or 0)
            if best is None or eng > best["engagement"]:
                cap = (p.get("caption") or "").strip().split("\n")[0]
                best = {
                    "platform":   "instagram",
                    "channel":    ch,
                    "title":      cap[:50] or "(캡션 없음)",
                    "engagement": eng,
                    "metric":     f"♥ {fmt_num(p.get('likeCount') or 0)} / 💬 {fmt_num(p.get('commentCount') or 0)}",
                }
    return best


def _best_fb_post(channels):
    best = None
    for ch in channels:
        if ch.get("platform") != "facebook":
            continue
        for p in ch.get("topPosts") or []:
            eng = (p.get("likeCount") or 0) + (p.get("commentCount") or 0) + (p.get("shareCount") or 0)
            if best is None or eng > best["engagement"]:
                cap = (p.get("caption") or "").strip().split("\n")[0]
                best = {
                    "platform":   "facebook",
                    "channel":    ch,
                    "title":      cap[:50] or "(본문 없음)",
                    "engagement": eng,
                    "metric":     f"👍 {fmt_num(p.get('likeCount') or 0)} / 💬 {fmt_num(p.get('commentCount') or 0)}",
                }
    return best


def _pick_top_content(channels):
    """Pick the single most notable piece of content across YT/IG/FB.
    YT ranks by views, IG/FB rank by engagement — so we compare by platform-normalized priority:
      1) YT video with most views (absolute)
      2) IG post with top engagement
      3) FB post with top engagement
    Return whichever has the highest 'score' (views for YT, eng×10 for IG/FB since
    follower scales are smaller on IG/FB than YT views).
    """
    y = _best_youtube_video(channels)
    ig = _best_ig_post(channels)
    fb = _best_fb_post(channels)
    candidates = []
    if y:  candidates.append(("youtube",   y.get("viewCount", 0),     y))
    if ig: candidates.append(("instagram", ig.get("engagement", 0)*10, ig))
    if fb: candidates.append(("facebook",  fb.get("engagement", 0)*10, fb))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[1], reverse=True)
    return candidates[0][2]


def _platform_follower_delta(game_id, platform, channels, hist):
    """Aggregate follower total + day-over-day delta across all regions of one platform.
    Returns (today_total, yday_total_or_None).
    """
    today_total = 0
    yday_total  = 0
    yday_found  = False
    for c in channels:
        if c.get("platform") != platform:
            continue
        if c.get("missing") or c.get("followers") is None:
            continue
        today_total += int(c["followers"])
        prior, _ = _lookup_prior(hist, game_id, platform, c["region"], days_back=1)
        if prior is not None:
            yday_total += int(prior)
            yday_found = True
    return today_total, (yday_total if yday_found else None)


def _fmt_follower_line(total, yday_total):
    """Build the '전체 팔로워 X명 · 전일 ...' bullet line."""
    if not total:
        return None
    if yday_total is None:
        return f"팔로워 <b>{fmt_num(total)}</b>명 · 전일 데이터 축적 중"
    delta = total - yday_total
    if delta == 0:
        return f"팔로워 <b>{fmt_num(total)}</b>명 · 전일 동일"
    pct = _pct(total, yday_total)
    sign = "+" if delta >= 0 else "−"
    pct_str = f"{abs(pct):.2f}%" if pct is not None else ""
    return (
        f"팔로워 <b>{fmt_num(total)}</b>명 · 전일 대비 "
        f"{sign}{fmt_num(abs(delta))} ({sign}{pct_str})"
    )


def _yt_latest_video_across(channels):
    """Return (video, channel) for the most recently published video across all
    YT channels of a game, or (None, None) if nothing found."""
    best = None
    for ch in channels:
        if ch.get("platform") != "youtube":
            continue
        vids = ch.get("recentVideos") or []
        for v in vids:
            ts = v.get("publishedAt") or ""
            if best is None or ts > best[0].get("publishedAt", ""):
                best = (v, ch)
    return (best[0], best[1]) if best else (None, None)


def _yt_avg_of_recent(ch, n=5, skip_latest=False):
    """Return {views, likes, comments} averaged over recent n videos of one channel.
    Returns None when not enough data."""
    vids = ch.get("recentVideos") or []
    if skip_latest:
        vids = vids[1:]
    vids = vids[:n]
    if not vids:
        return None
    views = [int(v.get("viewCount") or 0) for v in vids]
    likes = [int(v.get("likeCount") or 0) for v in vids]
    comms = [int(v.get("commentCount") or 0) for v in vids]
    return {
        "views":    sum(views) // len(views),
        "likes":    sum(likes) // len(likes),
        "comments": sum(comms) // len(comms),
        "n":        len(vids),
    }


def _insight_youtube(game, channels, hist):
    """YouTube-specific briefing bullets."""
    bullets = []
    yt_ch = [c for c in channels if c.get("platform") == "youtube"]
    if not yt_ch:
        return None

    # 1) Total subs + 1-day delta
    today_total, yday_total = _platform_follower_delta(game["id"], "youtube", channels, hist)
    line = _fmt_follower_line(today_total, yday_total)
    if line:
        bullets.append(line)

    # 2) Latest video metrics
    latest, ch_of_latest = _yt_latest_video_across(yt_ch)
    if latest and ch_of_latest:
        title = (latest.get("title") or "").replace("<", "&lt;").replace(">", "&gt;")[:42]
        trim_ellipsis = "…" if latest.get("title") and len(latest["title"]) > 42 else ""
        views = int(latest.get("viewCount") or 0)
        likes = int(latest.get("likeCount") or 0)
        comms = int(latest.get("commentCount") or 0)
        ago = ""
        try:
            pub = datetime.fromisoformat((latest.get("publishedAt") or "").replace("Z", "+00:00"))
            hours = (datetime.now(pub.tzinfo) - pub).total_seconds() / 3600
            ago = f"{int(hours)}h 전" if hours < 24 else f"{int(hours/24)}일 전"
        except Exception:
            pass
        bullets.append(
            f"최신 영상 <b>{ch_of_latest['region']}</b>"
            f"{(' · ' + ago) if ago else ''}: "
            f"\"{title}{trim_ellipsis}\" · "
            f"▶ {fmt_num(views)} · ♥ {fmt_num(likes)} · 💬 {fmt_num(comms)}"
        )

        # 3) Latest vs recent-5 avg (same channel, excluding latest)
        avg = _yt_avg_of_recent(ch_of_latest, n=5, skip_latest=True)
        if avg and avg["views"]:
            diff_pct = _pct(views, avg["views"])
            if diff_pct is not None:
                sign = "+" if diff_pct >= 0 else ""
                bullets.append(
                    f"이전 5개 평균 조회수 <b>{fmt_num(avg['views'])}</b> 대비 "
                    f"<b>{sign}{diff_pct:.1f}%</b>"
                )

    # 4) Content history — day-1 view count when we have it
    #    Uses content_entries: find the earliest snapshot after publishedAt for the latest video.
    if latest and ch_of_latest:
        vid_id = latest.get("videoId")
        series = content_history_for(hist, game["id"], "youtube", ch_of_latest["region"], vid_id) if vid_id else []
        # Find snapshots at "day 1" (first snapshot after publish date)
        day1_views = None
        try:
            pub_date = (latest.get("publishedAt") or "")[:10]
            if pub_date and series:
                # earliest snapshot whose date is strictly AFTER pub_date
                for s in series:
                    if s.get("date") > pub_date and s.get("views") is not None:
                        day1_views = int(s["views"])
                        break
        except Exception:
            pass
        if day1_views is not None and day1_views > 0:
            bullets.append(f"업로드 1일차 조회수 <b>{fmt_num(day1_views)}</b>")

    return {"bullets": bullets, "generatedAt": NOW_ISO} if bullets else None


def _insight_meta_platform(game, channels, hist, platform, like_emoji, label_ko):
    """Shared generator for Instagram & Facebook."""
    bullets = []
    plat_ch = [c for c in channels if c.get("platform") == platform]
    if not plat_ch:
        return None

    # 1) Total followers + 1-day delta
    today_total, yday_total = _platform_follower_delta(game["id"], platform, channels, hist)
    line = _fmt_follower_line(today_total, yday_total)
    if line:
        bullets.append(line)

    # 2) Most-recent post with engagement across all regions
    latest = None
    latest_ch = None
    for ch in plat_ch:
        posts = ch.get("recentPosts") or []
        if not posts:
            continue
        p = posts[0]  # recentPosts is newest-first
        ts = p.get("timestamp") or ""
        if latest is None or ts > (latest.get("timestamp") or ""):
            latest = p
            latest_ch = ch

    if latest and latest_ch:
        likes = int(latest.get("likeCount") or 0)
        comms = int(latest.get("commentCount") or 0)
        shares = int(latest.get("shareCount") or 0) if platform == "facebook" else None
        ago = ""
        try:
            ts = datetime.fromisoformat((latest.get("timestamp") or "").replace("Z", "+00:00"))
            hours = (datetime.now(ts.tzinfo) - ts).total_seconds() / 3600
            ago = f"{int(hours)}h 전" if hours < 24 else f"{int(hours/24)}일 전"
        except Exception:
            pass
        cap = (latest.get("caption") or "").replace("<", "&lt;").replace(">", "&gt;")[:38]
        trim_ellipsis = "…" if latest.get("caption") and len(latest["caption"]) > 38 else ""
        metric_parts = [f"{like_emoji} {fmt_num(likes)}", f"💬 {fmt_num(comms)}"]
        if shares is not None and shares > 0:
            metric_parts.append(f"↗ {fmt_num(shares)}")
        bullets.append(
            f"최신 포스트 <b>{latest_ch['region']}</b>"
            f"{(' · ' + ago) if ago else ''}: "
            f"\"{cap}{trim_ellipsis}\" · " + " · ".join(metric_parts)
        )

        # 3) Latest vs avg of prior 9 posts (same channel)
        prior_posts = (latest_ch.get("recentPosts") or [])[1:10]
        if prior_posts:
            avg_likes = sum(int(p.get("likeCount") or 0) for p in prior_posts) // len(prior_posts)
            avg_comms = sum(int(p.get("commentCount") or 0) for p in prior_posts) // len(prior_posts)
            latest_eng = likes + comms
            avg_eng    = avg_likes + avg_comms
            if avg_eng:
                diff_pct = _pct(latest_eng, avg_eng)
                if diff_pct is not None:
                    sign = "+" if diff_pct >= 0 else ""
                    bullets.append(
                        f"이전 포스트 평균 참여 대비 <b>{sign}{diff_pct:.1f}%</b> "
                        f"(평균 {like_emoji} {fmt_num(avg_likes)} · 💬 {fmt_num(avg_comms)})"
                    )

    # 4) Top-engagement post highlight (when different from latest)
    best_post = None
    best_ch = None
    for ch in plat_ch:
        for p in ch.get("topPosts") or []:
            if best_post is None or p.get("engagement", 0) > best_post.get("engagement", 0):
                best_post = p
                best_ch = ch
    if best_post and best_ch and best_post is not latest:
        cap = (best_post.get("caption") or "").replace("<", "&lt;").replace(">", "&gt;")[:38]
        trim_ellipsis = "…" if best_post.get("caption") and len(best_post["caption"]) > 38 else ""
        likes = int(best_post.get("likeCount") or 0)
        comms = int(best_post.get("commentCount") or 0)
        shares = int(best_post.get("shareCount") or 0) if platform == "facebook" else None
        metric_parts = [f"{like_emoji} {fmt_num(likes)}", f"💬 {fmt_num(comms)}"]
        if shares is not None and shares > 0:
            metric_parts.append(f"↗ {fmt_num(shares)}")
        bullets.append(
            f"참여 TOP <b>{best_ch['region']}</b>: "
            f"\"{cap}{trim_ellipsis}\" · " + " · ".join(metric_parts)
        )

    return {"bullets": bullets, "generatedAt": NOW_ISO} if bullets else None


def _insight_instagram(game, channels, hist):
    return _insight_meta_platform(game, channels, hist, "instagram", "♥", "Instagram")


def _insight_facebook(game, channels, hist):
    return _insight_meta_platform(game, channels, hist, "facebook", "👍", "Facebook")


def _insight_x(game, channels, hist):
    """X briefing — follower delta only until API integration ships."""
    bullets = []
    x_ch = [c for c in channels if c.get("platform") == "x"]
    if not x_ch:
        return None
    today_total, yday_total = _platform_follower_delta(game["id"], "x", channels, hist)
    line = _fmt_follower_line(today_total, yday_total)
    if line:
        bullets.append(line)
    # Note the manual-input limitation so readers know why content-level metrics are absent
    manual_count = sum(1 for c in x_ch if c.get("followersSource") == "manual")
    if manual_count and manual_count == len(x_ch):
        bullets.append("콘텐츠 분석은 API 연동 후 제공 예정 · 현재 수동 입력")
    return {"bullets": bullets, "generatedAt": NOW_ISO} if bullets else None


def _insight_discord(game, channels, hist):
    """Discord briefing — member delta + online ratio."""
    bullets = []
    dc_ch = [c for c in channels if c.get("platform") == "discord"]
    if not dc_ch:
        return None
    today_total, yday_total = _platform_follower_delta(game["id"], "discord", channels, hist)
    line = _fmt_follower_line(today_total, yday_total)
    if line:
        # Custom wording: Discord uses 멤버 instead of 팔로워
        line = line.replace("팔로워", "멤버")
        bullets.append(line)

    # Online ratio (sum of online / sum of members)
    total_online  = sum(int(c.get("onlineCount") or 0) for c in dc_ch if c.get("onlineCount") is not None)
    total_members = sum(int(c.get("followers") or 0) for c in dc_ch if c.get("followers") is not None)
    if total_members:
        ratio = total_online / total_members * 100
        bullets.append(
            f"온라인 <b>{fmt_num(total_online)}</b>명 / 전체 {fmt_num(total_members)}명 "
            f"(활성도 {ratio:.1f}%)"
        )
    return {"bullets": bullets, "generatedAt": NOW_ISO} if bullets else None


def _insight_overview(game, channels, hist, kpi_targets_for_game):
    """Cross-platform overview — biggest mover + KPI snapshot."""
    bullets = []

    # Biggest 7-day mover
    movers = []
    for c in channels:
        if c.get("missing") or c.get("followers") is None:
            continue
        cur = int(c["followers"])
        prior, prior_date = _lookup_prior(hist, game["id"], c["platform"], c["region"], days_back=7)
        if prior is None:
            continue
        pct = _pct(cur, prior)
        if pct is None:
            continue
        movers.append((pct, cur - prior, c))
    if movers:
        movers.sort(key=lambda t: t[0], reverse=True)
        top_pct, top_abs, top_ch = movers[0]
        if top_pct >= 0.3:
            bullets.append(
                f"7일 성장 1위: <b>{top_ch['platform'].title()} {top_ch['region']}</b> "
                f"(+{top_pct:.2f}%, +{fmt_num(int(top_abs))})"
            )
        worst_pct, worst_abs, worst_ch = movers[-1]
        if worst_pct <= -1.0:
            bullets.append(
                f"주의: <b>{worst_ch['platform'].title()} {worst_ch['region']}</b> "
                f"{worst_pct:.2f}% 하락 ({fmt_num(int(worst_abs))})"
            )

    # KPI avg
    if kpi_targets_for_game:
        totals = {}
        for c in channels:
            if c.get("followers") is None:
                continue
            p = c["platform"]
            totals[p] = totals.get(p, 0) + int(c["followers"])
        pcts = []
        for platform, target in kpi_targets_for_game.items():
            if target <= 0:
                continue
            cur = totals.get(platform, 0)
            pcts.append((platform, cur / target * 100.0))
        if pcts:
            avg = sum(p for _, p in pcts) / len(pcts)
            pcts.sort(key=lambda t: t[1])
            low_platform, low_pct = pcts[0]
            bullets.append(
                f"KPI 평균 <b>{avg:.1f}%</b> · 최저 "
                f"<b>{low_platform.title()} {low_pct:.1f}%</b>"
            )
    return {"bullets": bullets, "generatedAt": NOW_ISO} if bullets else None


def generate_per_platform_insights(game, hist, kpi_targets_for_game):
    """Produce per-platform briefings for a single game.

    Returns dict keyed by platform + "overview":
       {"overview": {...} | None, "youtube": {...}, "x": {...}, ...}
    Any platform without data is omitted. Returns empty dict if game has no usable data.
    """
    channels = game.get("channels") or []
    out = {}
    ov = _insight_overview(game, channels, hist, kpi_targets_for_game)
    if ov: out["overview"] = ov
    for key, fn in (
        ("youtube",   _insight_youtube),
        ("x",         _insight_x),
        ("instagram", _insight_instagram),
        ("facebook",  _insight_facebook),
        ("discord",   _insight_discord),
    ):
        result = fn(game, channels, hist)
        if result:
            out[key] = result
    return out


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


def yt_recent_videos(channel_id, api_key, count=7):
    """Fetch recent videos with view/like/comment counts.

    Two-step process:
      1. playlistItems.list on UU{id} → video IDs + titles (1 unit)
      2. videos.list with ids=... → statistics per video (1 unit)
    Total quota cost: 2 units per channel regardless of count (up to 50).

    Returns list of {videoId, title, publishedAt, viewCount, likeCount, commentCount}
    sorted by publishedAt desc. Returns [] on error.
    """
    if not channel_id or not channel_id.startswith("UC") or count <= 0:
        return []
    uploads_playlist_id = "UU" + channel_id[2:]
    try:
        # Step 1 — recent video IDs
        pl_url = (
            "https://www.googleapis.com/youtube/v3/playlistItems?"
            + urllib.parse.urlencode({
                "part": "snippet",
                "playlistId": uploads_playlist_id,
                "maxResults": min(count, 50),
                "key": api_key,
            })
        )
        pl_data = http_get_json(pl_url)
        items = pl_data.get("items") or []
        vids = []
        for it in items:
            snip = it.get("snippet") or {}
            res_id = snip.get("resourceId") or {}
            vid = res_id.get("videoId")
            if vid:
                vids.append({
                    "videoId":     vid,
                    "title":       snip.get("title") or "",
                    "publishedAt": snip.get("publishedAt") or "",
                })
        if not vids:
            return []

        # Step 2 — batch stats lookup
        stats_url = (
            "https://www.googleapis.com/youtube/v3/videos?"
            + urllib.parse.urlencode({
                "part": "statistics",
                "id":   ",".join(v["videoId"] for v in vids),
                "key":  api_key,
            })
        )
        stats_data = http_get_json(stats_url)
        stats_by_id = {s["id"]: (s.get("statistics") or {}) for s in stats_data.get("items", [])}
        for v in vids:
            s = stats_by_id.get(v["videoId"], {})
            v["viewCount"]    = int(s.get("viewCount", 0))    if s.get("viewCount")    else 0
            v["likeCount"]    = int(s.get("likeCount", 0))    if s.get("likeCount")    else 0
            v["commentCount"] = int(s.get("commentCount", 0)) if s.get("commentCount") else 0
        return vids
    except Exception as e:
        log(f"    WARN: recent videos lookup failed for {channel_id}: {e}")
        return []


def yt_latest_video(channel_id, api_key):
    """Best-effort — returns {title, publishedAt, videoId} or None.

    Uses playlistItems.list on the channel's 'uploads' playlist (cost: 1 unit)
    instead of search.list (cost: 100 units). The uploads playlist ID is the
    channel ID with the 'UC' prefix replaced by 'UU'.
    Docs: https://developers.google.com/youtube/v3/determine_quota_cost
    """
    if not channel_id or not channel_id.startswith("UC"):
        return None
    uploads_playlist_id = "UU" + channel_id[2:]
    try:
        url = (
            "https://www.googleapis.com/youtube/v3/playlistItems?"
            + urllib.parse.urlencode({
                "part": "snippet",
                "playlistId": uploads_playlist_id,
                "maxResults": 1,
                "key": api_key,
            })
        )
        data = http_get_json(url)
        items = data.get("items") or []
        if not items:
            return None
        snip = items[0].get("snippet") or {}
        res_id = snip.get("resourceId") or {}
        return {
            "title":       snip.get("title"),
            "publishedAt": snip.get("publishedAt"),
            "videoId":     res_id.get("videoId"),
        }
    except Exception as e:
        log(f"    WARN: latest video lookup failed for {channel_id}: {e}")
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
        # Recent videos with per-video stats — 10 items for insight + content history
        ch["recentVideos"]  = yt_recent_videos(item["id"], api_key, count=10)
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

            # Normalized recent-post records (chronological, newest first — same order as items)
            recent_posts = []
            for m in items:
                likes = int(m.get("like_count") or 0)
                comms = int(m.get("comments_count") or 0)
                cap   = (m.get("caption") or "").strip().split("\n", 1)[0][:120]
                recent_posts.append({
                    "id":           m.get("id"),
                    "caption":      cap,
                    "likeCount":    likes,
                    "commentCount": comms,
                    "engagement":   likes + comms,
                    "timestamp":    m.get("timestamp"),
                    "mediaType":    m.get("media_type"),
                    "permalink":    m.get("permalink"),
                })
            ch["recentPosts"] = recent_posts

            # Top 3 posts by engagement (for highlights)
            ch["topPosts"] = sorted(recent_posts, key=lambda x: x["engagement"], reverse=True)[:3]
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
        # Diagnostic: log what the API actually returned, so we can spot
        # cases where multiple page_ids resolve to the same canonical page
        # (e.g. merged pages) or where permissions cause silent fallbacks.
        log(f"    FB [{page_id}] returned id={page.get('id')!r} "
            f"name={page.get('name')!r} "
            f"followers_count={page.get('followers_count')!r} "
            f"fan_count={page.get('fan_count')!r}")
        followers = page.get("followers_count")
        followers_source = "followers_count"
        if followers is None:
            followers = page.get("fan_count")  # legacy fallback
            followers_source = "fan_count"
        if followers is None:
            return False, "no followers_count/fan_count in response (check page permissions)"
        ch["followers"] = int(followers)
        ch["title"]     = page.get("name")
        ch["followersSource"] = followers_source
        # Detect ID-remapping: some pages (esp. merged ones) return a different
        # id than requested. Store for later inspection in the JSON snapshot.
        returned_id = str(page.get("id") or "")
        if returned_id and returned_id != str(page_id):
            ch["fbResolvedId"] = returned_id
            log(f"    ⚠ FB page_id mismatch: requested {page_id} but API returned {returned_id}")
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

            # Normalized recent-post records (chronological, newest first)
            recent_posts = []
            for p in items:
                reacts = ((p.get("reactions") or {}).get("summary") or {}).get("total_count") or 0
                comms  = ((p.get("comments") or {}).get("summary") or {}).get("total_count") or 0
                shrs   = (p.get("shares") or {}).get("count") if p.get("shares") else 0
                m_raw = (p.get("message") or "").strip()
                cap   = m_raw.split("\n", 1)[0][:120] if m_raw else ""
                recent_posts.append({
                    "id":           p.get("id"),
                    "caption":      cap,
                    "likeCount":    int(reacts),
                    "commentCount": int(comms),
                    "shareCount":   int(shrs or 0),
                    "engagement":   int(reacts) + int(comms) + int(shrs or 0),
                    "timestamp":    p.get("created_time"),
                    "permalink":    p.get("permalink_url"),
                })
            ch["recentPosts"] = recent_posts
            ch["topPosts"]    = sorted(recent_posts, key=lambda x: x["engagement"], reverse=True)[:3]
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
                data = json.load(f)
                # Back-compat: ensure content_entries exists for schema v2
                if "content_entries" not in data:
                    data["content_entries"] = []
                return data
        except Exception:
            pass
    return {"entries": [], "content_entries": []}
    # entries:         [{date, channels: {game:platform:region: followers}}]
    # content_entries: [{date, game, platform, region, content_id, publishedAt, views, likes, comments, shares?}]


def save_history(hist, today_data):
    """Append today's entry (followers + content snapshots) and trim retention."""
    # ----- 1) Channel follower snapshot (90-day retention, legacy) -----
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

    # ----- 2) Per-content snapshots (60-day retention) -----
    today = today_data["snapshotDate"]
    content = [e for e in hist.get("content_entries", []) if e.get("date") != today]
    for g in today_data["games_list"]:
        for c in g["channels"]:
            plat = c.get("platform")
            region = c.get("region")
            # YouTube — track recent 10 videos
            if plat == "youtube":
                for v in (c.get("recentVideos") or [])[:10]:
                    vid = v.get("videoId")
                    if not vid:
                        continue
                    content.append({
                        "date":        today,
                        "game":        g["id"],
                        "platform":    "youtube",
                        "region":      region,
                        "content_id":  vid,
                        "publishedAt": v.get("publishedAt"),
                        "title":       (v.get("title") or "")[:120],
                        "views":       v.get("viewCount"),
                        "likes":       v.get("likeCount"),
                        "comments":    v.get("commentCount"),
                    })
            # Instagram — track recent 10 posts (stored on channel as recentPosts)
            elif plat == "instagram":
                for p in (c.get("recentPosts") or [])[:10]:
                    pid = p.get("permalink") or p.get("id") or ""
                    if not pid:
                        continue
                    content.append({
                        "date":        today,
                        "game":        g["id"],
                        "platform":    "instagram",
                        "region":      region,
                        "content_id":  pid,
                        "publishedAt": p.get("timestamp"),
                        "title":       (p.get("caption") or "")[:120],
                        "views":       None,  # IG Graph API doesn't expose post play count for plain images
                        "likes":       p.get("likeCount"),
                        "comments":    p.get("commentCount"),
                    })
            # Facebook — track recent 10 posts
            elif plat == "facebook":
                for p in (c.get("recentPosts") or [])[:10]:
                    pid = p.get("permalink") or p.get("id") or ""
                    if not pid:
                        continue
                    content.append({
                        "date":        today,
                        "game":        g["id"],
                        "platform":    "facebook",
                        "region":      region,
                        "content_id":  pid,
                        "publishedAt": p.get("timestamp"),
                        "title":       (p.get("caption") or "")[:120],
                        "views":       None,
                        "likes":       p.get("likeCount"),
                        "comments":    p.get("commentCount"),
                        "shares":      p.get("shareCount"),
                    })

    content_cutoff = (date.today() - timedelta(days=60)).isoformat()
    content = [e for e in content if e.get("date", "0") >= content_cutoff]
    hist["content_entries"] = content

    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


def content_history_for(hist, game_id, platform, region, content_id):
    """Return chronologically sorted list of daily snapshots for a single content item."""
    return sorted(
        (e for e in hist.get("content_entries", [])
         if e.get("game") == game_id and e.get("platform") == platform
         and e.get("region") == region and e.get("content_id") == content_id),
        key=lambda e: e.get("date") or "",
    )


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
.plogo { width: 20px; height: 20px; border-radius: 5px; display: inline-flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; }
.plogo svg { color: #fff; fill: #fff; }
.plogo.yt { background: var(--yt); }
.plogo.x  { background: #000; color: #fff; }
.plogo.x svg path { fill: #fff !important; }
.plogo.ig { background: linear-gradient(135deg, var(--ig-a), var(--ig-b) 55%, var(--ig-c)); }
.plogo.fb { background: var(--fb); }
.plogo.dc { background: var(--dc); }
.channel-head .ext { color: var(--muted-2); padding: 4px; border-radius: 6px; }
.channel-head .ext:hover { background: var(--bg); color: var(--text); }
.handle { font-size: 12px; color: var(--muted); word-break: break-all; line-height: 1.35; }
.handle a:hover { text-decoration: underline; color: var(--text-2); }
.metric-row { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; flex-wrap: wrap; row-gap: 6px; }
.follower-num { font-size: 22px; font-weight: 700; letter-spacing: -0.015em; flex-shrink: 1; min-width: 0; }
.follower-num small { font-size: 11px; font-weight: 500; color: var(--muted); margin-left: 4px; }
.delta-chip { font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 999px; display: inline-flex; align-items: center; gap: 3px; }
.delta-chip.up { color: var(--pos); background: #E8F7EE; }
.delta-chip.down { color: var(--neg); background: #FDE7ED; }
.delta-chip.flat { color: var(--muted); background: #F1F2F4; }
.delta-chip.nil { color: var(--muted); background: transparent; border: 1px dashed var(--border); font-weight: 500; }
.delta-chip.manual { color: #7A5B00; background: #FFF4D6; border: 1px solid #F0D98A; font-weight: 500; }
.badge-group { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; justify-content: flex-end; max-width: 100%; }
.manual-tag { font-size: 10px; font-weight: 500; color: #7A5B00; background: #FFF4D6; border: 1px solid #F0D98A; padding: 1px 6px; border-radius: 999px; white-space: nowrap; }
.kpi-card { background: #fff; border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px; margin: 14px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
.kpi-title { font-size: 13px; font-weight: 600; color: var(--text-1); margin-bottom: 12px; display: flex; align-items: baseline; gap: 8px; }
.kpi-title .kpi-sub { font-size: 11px; font-weight: 400; color: var(--muted); }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }
.kpi-item { display: flex; flex-direction: column; gap: 6px; }
.kpi-head { display: flex; align-items: center; justify-content: space-between; font-size: 12px; }
.kpi-platform { display: inline-flex; align-items: center; gap: 5px; font-weight: 600; color: var(--text-1); }
.kpi-pct { font-weight: 700; font-size: 13px; color: var(--text-1); }
.kpi-bar { height: 6px; background: #EEF0F3; border-radius: 999px; overflow: hidden; }
.kpi-fill { height: 100%; border-radius: 999px; transition: width 0.3s ease; }
.kpi-item.low  .kpi-fill { background: #E5554D; }
.kpi-item.mid  .kpi-fill { background: #F0A32E; }
.kpi-item.high .kpi-fill { background: #4F8EF7; }
.kpi-item.done .kpi-fill { background: #2CA45A; }
.kpi-item.done .kpi-pct  { color: #2CA45A; }
.kpi-nums { font-size: 11px; color: var(--muted); }
.kpi-nums b { color: var(--text-1); font-weight: 600; }
/* Unified briefing card with per-platform sections */
.insight-card { background: #fff; border: 1px solid var(--border); border-radius: 14px; padding: 16px 20px; margin: 14px 0 18px; box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
.insight-head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
.insight-head-label { font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }
.insight-sections { display: flex; flex-direction: column; gap: 14px; }
.insight-tag { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px; background: var(--accent-bg, rgba(107,95,212,0.10)); color: var(--accent, #6B5FD4); font-size: 11.5px; font-weight: 700; margin-bottom: 8px; letter-spacing: -0.005em; }
.insight-tag-glyph { font-size: 11px; line-height: 1; }
.insight-bullets { list-style: none; padding: 0 0 0 2px; margin: 0; display: flex; flex-direction: column; gap: 4px; }
.insight-bullets li { position: relative; padding-left: 14px; font-size: 12.5px; line-height: 1.6; color: var(--text-2); }
.insight-bullets li::before { content: "·"; position: absolute; left: 3px; top: -3px; color: var(--accent, #6B5FD4); font-weight: 900; font-size: 18px; }
.insight-bullets li b { color: var(--text-1); font-weight: 600; }

/* YouTube stats subnote (latest-vs-avg chip) */
.yt-stats .vs-avg { display: inline-block; margin-left: 6px; padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; }
.yt-stats .vs-avg.up   { background: rgba(18,161,80,0.10);  color: var(--pos); }
.yt-stats .vs-avg.down { background: rgba(225,29,72,0.08); color: var(--neg); }
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
    """Format a number with thousands separators (e.g. 85311 -> '85,311').
    Shows full precision down to the ones digit."""
    if n is None:
        return "—"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
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
    if platform == "youtube" and ch.get("recentVideos"):
        vids = ch["recentVideos"][:5]
        if vids:
            avg_views = sum(int(v.get("viewCount") or 0)    for v in vids) // len(vids)
            avg_likes = sum(int(v.get("likeCount") or 0)    for v in vids) // len(vids)
            avg_comms = sum(int(v.get("commentCount") or 0) for v in vids) // len(vids)
            total_views = sum(int(v.get("viewCount") or 0)  for v in vids)
            total_eng   = sum(int(v.get("likeCount") or 0) + int(v.get("commentCount") or 0)
                              for v in vids)
            eng_rate = (total_eng / total_views * 100) if total_views else 0.0

            # Latest vs prior-4 comparison (skip latest, avg over next 4)
            compare_html = ""
            all_vids = ch["recentVideos"]
            if len(all_vids) >= 2 and int(all_vids[0].get("viewCount") or 0) > 0:
                latest_views = int(all_vids[0].get("viewCount") or 0)
                prior_4 = all_vids[1:5]
                if prior_4:
                    prior_avg = sum(int(v.get("viewCount") or 0) for v in prior_4) // len(prior_4)
                    if prior_avg:
                        diff = (latest_views - prior_avg) / prior_avg * 100
                        sign = "+" if diff >= 0 else ""
                        tone = "up" if diff >= 0 else "down"
                        compare_html = (
                            f' <span class="vs-avg {tone}">최신 vs 평균 {sign}{diff:.0f}%</span>'
                        )

            sub_note += (
                f'<div class="subnote yt-stats" style="border-top:none;padding-top:4px;">'
                f'<b>최근 5개 평균</b> · ▶ {fmt_num(avg_views)} · ♥ {fmt_num(avg_likes)} · '
                f'💬 {fmt_num(avg_comms)} · 참여율 {eng_rate:.2f}%'
                f'{compare_html}'
                f'</div>'
            )
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

    # Manual entries show delta chip + a small "수동" marker so changes are visible.
    # Skip the "no history" placeholder chip for manual entries — the 수동 tag already conveys that state.
    if ch.get("followersSource") == "manual":
        as_of_full = ch.get("manualAsOf") or ""
        # Shorten "2026-04-22" -> "26-04-22" so the badge stays compact
        as_of_short = as_of_full[2:] if len(as_of_full) >= 10 and as_of_full[:2] == "20" else as_of_full
        title_suffix = (" · " + as_of_full) if as_of_full else ""
        manual_tag = (
            f'<span class="manual-tag" title="Manually entered{title_suffix}">'
            f'수동{(" · " + as_of_short) if as_of_short else ""}</span>'
        )
        delta_part = delta_chip_html(delta_week) if delta_week is not None else ""
        badge_html = f'<span class="badge-group">{delta_part}{manual_tag}</span>'
    else:
        badge_html = delta_chip_html(delta_week)

    return f"""
      <div class="channel">
        <div class="channel-head">
          <span class="platform"><span class="plogo {PLATFORM_CSS[platform]}">{platform_icon_svg(platform)}</span>{platform.title()} · {region}</span>
          <a class="ext" href="{ch['url']}" target="_blank" rel="noopener" aria-label="Open">↗</a>
        </div>
        <div class="handle"><a href="{ch['url']}" target="_blank" rel="noopener">{ch['handle']}</a></div>
        <div class="metric-row">
          <div class="follower-num">{fmt_num(ch["followers"])}<small>{meta_metric}</small></div>
          {badge_html}
        </div>
        <div class="spark-wrap"><canvas data-series='{series_json}' data-color="{spark_color}"></canvas></div>
        {sub_note}
      </div>"""


PLATFORM_INSIGHT_META = {
    # key: (display name, accent hex, accent-bg rgba, icon glyph)
    "overview":  ("전체 요약",  "#6B5FD4", "rgba(107,95,212,0.10)", "✦"),
    "youtube":   ("YouTube",    "#FF0033", "rgba(255,0,51,0.08)",   "▶"),
    "x":         ("X",          "#111111", "rgba(17,17,17,0.07)",   "𝕏"),
    "instagram": ("Instagram",  "#DD2A7B", "rgba(221,42,123,0.09)", "◉"),
    "facebook":  ("Facebook",   "#1877F2", "rgba(24,119,242,0.09)", "f"),
    "discord":   ("Discord",    "#5865F2", "rgba(88,101,242,0.10)", "◈"),
}


def insight_card_html(game):
    """
    Render a single unified briefing card with one section per platform.
    Each platform appears as a small colored tag (소제목) followed by its
    bullets. Returns empty string when no platform has insights.
    """
    insights = game.get("insights") or {}
    if not insights:
        return ""

    order = ["overview", "youtube", "x", "instagram", "facebook", "discord"]
    sections = []
    gen_short = ""
    for key in order:
        ins = insights.get(key)
        if not ins or not ins.get("bullets"):
            continue
        if not gen_short:
            gen_short = (ins.get("generatedAt") or "")[:10]
        name, color, bg, icon = PLATFORM_INSIGHT_META.get(
            key, (key.title(), "#6B5FD4", "rgba(107,95,212,0.10)", "•")
        )
        items_html = "".join(f"<li>{b}</li>" for b in ins["bullets"])
        sections.append(
            f'''<div class="insight-section" style="--accent:{color};--accent-bg:{bg}">
                  <span class="insight-tag"><span class="insight-tag-glyph">{icon}</span>{name}</span>
                  <ul class="insight-bullets">{items_html}</ul>
                </div>'''
        )

    if not sections:
        return ""

    date_tag = f'{gen_short} · 오늘의 브리핑' if gen_short else '오늘의 브리핑'
    return f'''
    <div class="insight-card">
      <div class="insight-head"><span class="insight-head-label">{date_tag}</span></div>
      <div class="insight-sections">{"".join(sections)}</div>
    </div>'''


def kpi_row_html(game, targets_for_game):
    """
    Render a row of KPI progress bars for this game.
    targets_for_game: {"youtube": 275000, "x": 200000, ...}
    Shows: platform icon + current (sum across regions) / target + percentage + bar.
    Returns "" when the game has no configured targets.
    """
    if not targets_for_game:
        return ""
    # Sum follower counts per platform across all regions (skip missing)
    totals = {}
    for c in game["channels"]:
        if c.get("followers") is None:
            continue
        p = c["platform"]
        totals[p] = totals.get(p, 0) + int(c["followers"])

    cards = []
    # Render in the order platforms appear in targets (preserve JSON order)
    for platform, target in targets_for_game.items():
        current = totals.get(platform, 0)
        pct = (current / target * 100.0) if target > 0 else 0.0
        pct_capped = min(pct, 100.0)
        # Status tier for bar color
        if pct >= 100:
            tier = "done"
        elif pct >= 75:
            tier = "high"
        elif pct >= 40:
            tier = "mid"
        else:
            tier = "low"
        cards.append(
            f'<div class="kpi-item {tier}">'
            f'  <div class="kpi-head">'
            f'    <span class="kpi-platform"><span class="plogo {PLATFORM_CSS[platform]}">{platform_icon_svg(platform)}</span>{platform.title()}</span>'
            f'    <span class="kpi-pct">{pct:.1f}%</span>'
            f'  </div>'
            f'  <div class="kpi-bar"><div class="kpi-fill" style="width:{pct_capped:.2f}%"></div></div>'
            f'  <div class="kpi-nums"><b>{fmt_num(current)}</b> / {fmt_num(target)}</div>'
            f'</div>'
        )
    return (
        '<div class="kpi-card">'
        '  <div class="kpi-title">KPI 달성 현황 <span class="kpi-sub">전 권역 합산</span></div>'
        f'  <div class="kpi-grid">{"".join(cards)}</div>'
        '</div>'
    )


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
    kpi_targets_all = snapshot.get("kpiTargets", {}) or {}
    game_blocks = []
    trend_charts = []
    for g in snapshot["games_list"]:
        game_total = sum(c["followers"] for c in g["channels"] if c.get("followers") is not None)
        kpi_html = kpi_row_html(g, kpi_targets_all.get(g["id"], {}))

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
        {insight_card_html(g)}
        {kpi_html}
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
        yt_count = sum(1 for g in GAMES for c in g["channels"] if c["platform"] == "youtube")
        log(f"YouTube: API key loaded — fetching {yt_count} channels")
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

    # -------- Apply manual follower overrides (e.g. X counts entered by hand) --------
    manual_data = load_manual_followers()
    if manual_data:
        applied = 0
        for g in GAMES:
            for c in g["channels"]:
                platform = c.get("platform")
                handle   = c.get("handle")
                override = ((manual_data.get(platform) or {}).get(handle) or {})
                followers = override.get("followers")
                if followers is None:
                    continue
                if c.get("followers") is not None:
                    # Live API data already set — skip manual override
                    continue
                try:
                    c["followers"] = int(followers)
                except (TypeError, ValueError):
                    continue
                c["followersSource"] = "manual"
                as_of = override.get("asOf")
                if as_of:
                    c["manualAsOf"] = as_of
                # Clear 'missing' / pending markers so card renders normally
                c.pop("missing", None)
                applied += 1
                log(f"  ✎ manual: {g['id']}/{handle} → {int(followers):,} "
                    f"followers (asOf {as_of or 'n/a'})")
        if applied:
            log(f"Manual overrides: applied {applied} channel(s) from manual-followers.json")
            # If every X channel now has data via manual input, remove 'x' from pending
            x_live = [c for g in GAMES for c in g["channels"]
                      if c["platform"] == "x" and c.get("followers") is not None]
            x_total = [c for g in GAMES for c in g["channels"]
                       if c["platform"] == "x"]
            if x_total and len(x_live) == len(x_total) and "x" in platforms_pending:
                platforms_pending.remove("x")
                credential_status["x"] = {"configured": True, "method": "manual entry"}

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

    # -------- KPI targets --------
    kpi_targets = load_kpi_targets()
    if kpi_targets:
        log(f"KPI targets loaded for {len(kpi_targets)} game(s)")

    # -------- Rule-based daily insights (per-platform) --------
    # Note: load current history (today's entry not yet appended) so deltas
    # compare to the prior snapshots, not to today itself.
    log("Generating per-platform daily insights…")
    _hist_for_insights = load_history()
    for g in GAMES:
        insights = generate_per_platform_insights(g, _hist_for_insights, kpi_targets.get(g["id"], {}))
        if insights:
            g["insights"] = insights
            summary = ", ".join(f"{k}:{len(v['bullets'])}" for k, v in insights.items())
            log(f"  ✓ {g['id']}: {summary}")
        else:
            log(f"  · {g['id']}: no insight bullets available yet")

    # -------- Snapshot assembly --------
    snapshot = {
        "snapshotDate": TODAY,
        "runTimestamp": NOW_ISO,
        "credentialStatus": credential_status,
        "games": {g["id"]: {"name": g["name"], "ko": g["ko"], "channels": g["channels"],
                             "insights": g.get("insights")} for g in GAMES},
        "games_list": GAMES,
        "apiErrors": errors,
        "platformsPendingCredentials": platforms_pending,
        "kpiTargets": kpi_targets,
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

    html_out = build_html(snapshot, hist)
    with open(LATEST_HTML, "w", encoding="utf-8") as f:
        f.write(html_out)
    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html_out)
    dated_html = SNAPSHOTS / f"{TODAY}.html"
    with open(dated_html, "w", encoding="utf-8") as f:
        f.write(html_out)

    # -------- Report --------
    live_cnt = sum(1 for g in GAMES for c in g["channels"] if c.get("followers") is not None)
    total    = sum(c["followers"] for g in GAMES for c in g["channels"] if c.get("followers") is not None)
    log("")
    log(f"Done. {live_cnt} live channels, {len(errors)} errors, {len(platforms_pending)} platforms pending.")
    log(f"Total combined live followers: {total:,}")
    log(f"JSON: {json_path}")
    log(f"HTML: {LATEST_HTML}")
    return 0


if __name__ == "__main__":
    sys.exit(main())