"""
kol_monitor.py — KOL 推文與文章監控
來源：X API v2（Bearer Token）+ RSS fallback
輸出：Telegram 卡片推播
"""

import os
import json
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../automation/.env"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "")
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")      # 填入後 X 抓取才生效

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "../../automation/output")

# ─── KOL 清單 ──────────────────────────────────────────────────────────────────

KOL_LIST = [
    {
        "name":     "Gavin Baker",
        "handle":   "GavinSBaker",
        "x_id":     "",
        "rss":      None,
        "keywords": ["memory", "DRAM", "HBM", "NVDA", "AMD", "MU", "semi",
                     "AI", "datacenter", "capex", "cycle", "supply"],
        "focus":    "半導體/AI buy-side 觀點",
    },
    {
        "name":     "Ming-chi Kuo",
        "handle":   "mingchikuo",
        "x_id":     "",
        "rss":      None,
        "keywords": ["Apple", "iPhone", "supply chain", "shipment", "TSMC",
                     "Vision", "AR", "optical", "component"],
        "focus":    "Apple 供應鏈 / 消費電子需求",
    },
    {
        "name":     "Elon Musk",
        "handle":   "elonmusk",
        "x_id":     "",
        "rss":      None,
        "keywords": ["Tesla", "xAI", "Grok", "AI", "energy", "GPU",
                     "tariff", "China", "Starlink", "DOGE"],
        "focus":    "Tesla / xAI / 政策訊號",
    },
    {
        "name":     "Ben Thompson",
        "handle":   "benthompson",
        "x_id":     "",
        "rss":      "https://stratechery.com/feed/",
        "keywords": ["AI", "Apple", "Microsoft", "Google", "Meta",
                     "platform", "aggregator", "distribution", "moat"],
        "focus":    "科技產業結構分析（Stratechery）",
    },
    {
        "name":     "Invest Like the Best",
        "handle":   "patrick_oshag",
        "x_id":     "",
        "rss":      "https://feeds.megaphone.fm/investlikethebest",
        "keywords": ["semiconductor", "AI", "memory", "software",
                     "capital allocation", "moat", "compounding"],
        "focus":    "頂尖投資人訪談摘要",
    },
]

LOOKBACK_HOURS = 25

# ─── X API v2 ─────────────────────────────────────────────────────────────────

def _x_headers() -> dict:
    return {
        "Authorization": f"Bearer {X_BEARER_TOKEN}",
        "User-Agent": "KOLMonitor/1.0",
    }


def _x_get(url: str) -> dict | None:
    if not X_BEARER_TOKEN:
        return None
    req = urllib.request.Request(url, headers=_x_headers())
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"[kol] X API 錯誤: {e}")
        return None


def get_x_user_id(handle: str) -> str | None:
    data = _x_get(f"https://api.twitter.com/2/users/by/username/{handle}")
    return data["data"]["id"] if data and "data" in data else None


def fetch_x_tweets(handle: str, user_id: str, hours: int = LOOKBACK_HOURS) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = (
        f"https://api.twitter.com/2/users/{user_id}/tweets"
        f"?max_results=20"
        f"&start_time={since}"
        f"&tweet.fields=created_at,text,public_metrics"
        f"&exclude=retweets,replies"
    )
    data = _x_get(url)
    if not data or "data" not in data:
        return []
    return [
        {
            "source":  "x",
            "author":  handle,
            "text":    t["text"],
            "url":     f"https://x.com/{handle}/status/{t['id']}",
            "created": t.get("created_at", ""),
            "likes":   t.get("public_metrics", {}).get("like_count", 0),
        }
        for t in data["data"]
    ]


# ─── RSS 抓取 ─────────────────────────────────────────────────────────────────

def fetch_rss(url: str, kol_name: str, hours: int = LOOKBACK_HOURS) -> list[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "KOLMonitor/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
    except Exception as e:
        print(f"[kol] RSS 錯誤 {url}: {e}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    items  = []

    for item in root.iter("item"):
        title   = (item.findtext("title") or "").strip()
        link    = (item.findtext("link")  or "").strip()
        pub_raw = item.findtext("pubDate") or ""
        desc    = (item.findtext("description") or "").strip()[:300]

        try:
            from email.utils import parsedate_to_datetime
            pub_dt = parsedate_to_datetime(pub_raw).astimezone(timezone.utc)
        except Exception:
            pub_dt = cutoff

        if pub_dt < cutoff:
            continue

        items.append({
            "source":  "rss",
            "author":  kol_name,
            "text":    f"{title}\n{desc}",
            "url":     link,
            "created": pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "likes":   0,
        })

    return items


# ─── 關鍵字過濾 ───────────────────────────────────────────────────────────────

def is_relevant(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in keywords)


# ─── Telegram 推播 ────────────────────────────────────────────────────────────

def _tg_send(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print(text)
        return False
    payload = json.dumps({
        "chat_id":    TELEGRAM_CHAT,
        "text":       text[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"[kol] Telegram 推播失敗: {e}")
        return False


def format_kol_card(kol: dict, hits: list[dict]) -> str:
    now  = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"📡 <b>KOL — {kol['name']}</b>  {now}",
        f"<i>{kol['focus']}</i>",
        "",
    ]
    for h in hits[:5]:
        src_tag = "🐦" if h["source"] == "x" else "📰"
        text = h["text"].replace("\n", " ").strip()[:220]
        lines.append(f"{src_tag} {text}")
        lines.append(f'   <a href="{h["url"]}">→ 原文</a>  ❤️ {h["likes"]}')
        lines.append("")
    lines.append(f"共 {len(hits)} 條命中")
    return "\n".join(lines)


# ─── 主流程 ───────────────────────────────────────────────────────────────────

def run() -> dict:
    print("[kol_monitor] 開始掃描 KOL...")
    has_x = bool(X_BEARER_TOKEN)
    if not has_x:
        print("[kol_monitor] ⚠️  X_BEARER_TOKEN 未設定，僅使用 RSS 來源")

    results = {}

    for kol in KOL_LIST:
        name = kol["name"]
        hits = []

        if has_x:
            uid = kol["x_id"] or get_x_user_id(kol["handle"])
            if uid:
                kol["x_id"] = uid
                hits += [t for t in fetch_x_tweets(kol["handle"], uid)
                         if is_relevant(t["text"], kol["keywords"])]
                time.sleep(1)

        if kol.get("rss"):
            hits += [r for r in fetch_rss(kol["rss"], name)
                     if is_relevant(r["text"], kol["keywords"])]

        if hits:
            _tg_send(format_kol_card(kol, hits))
            print(f"[kol] {name}: {len(hits)} 條命中 → 已推播")
        else:
            print(f"[kol] {name}: 過去 {LOOKBACK_HOURS}h 無命中")

        results[name] = {"hits": len(hits), "items": hits}
        time.sleep(0.5)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, f"kol_{datetime.now().strftime('%Y%m%d')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"[kol_monitor] ✅ 結果存入 {out}")
    return results


if __name__ == "__main__":
    run()
