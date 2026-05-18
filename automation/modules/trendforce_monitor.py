"""
trendforce_monitor.py — TrendForce 研究報告與新聞監控
涵蓋：記憶體（DRAM / NAND / HBM）× CPO 產業鏈 × 半導體封裝
來源：TrendForce RSS + 分類頁面抓取
輸出：Telegram 卡片推播 + output/trendforce_YYYYMMDD.json
"""

import json
import os
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../automation/.env"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "")

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "../../automation/output")

LOOKBACK_HOURS = 25   # 覆蓋昨日 + 今日

# ─── 監控主題定義 ──────────────────────────────────────────────────────────────
#
# 每個主題有獨立 RSS URL（TrendForce 支援 tag-level RSS）
# 及關鍵字清單（二次過濾，避免不相關文章）

TOPICS = [
    {
        "id":       "memory",
        "label":    "記憶體（DRAM / NAND / HBM）",
        "emoji":    "🧠",
        "urls": [
            "https://www.trendforce.com/tag/dram/feed/",
            "https://www.trendforce.com/tag/nand-flash/feed/",
            "https://www.trendforce.com/tag/hbm/feed/",
        ],
        "fallback_url": "https://www.trendforce.com/feed/",
        "keywords": [
            "DRAM", "NAND", "HBM", "HBM3", "HBM4", "memory", "DDR5",
            "LPDDR5", "flash", "SSD", "eMMC", "UFS",
            "Samsung", "SK hynix", "Micron", "YMTC", "Kioxia", "WD",
            "ASP", "price", "supply", "demand", "inventory", "bit output",
            "CapEx", "fab", "node", "1beta", "1gamma", "CAPA",
        ],
        "investment_tickers": ["MU", "AVGO", "8299.TWO"],
    },
    {
        "id":       "cpo",
        "label":    "CPO 產業鏈",
        "emoji":    "🔆",
        "urls": [
            "https://www.trendforce.com/tag/cpo/feed/",
            "https://www.trendforce.com/tag/silicon-photonics/feed/",
            "https://www.trendforce.com/tag/optical/feed/",
        ],
        "fallback_url": "https://www.trendforce.com/feed/",
        "keywords": [
            "CPO", "co-packaged optic", "silicon photonics", "optical interconnect",
            "800G", "1.6T", "coherent", "transceiver", "laser", "photonic",
            "VSCEL", "fiber", "InP", "GaAs", "EML",
            "AAOI", "LITE", "COHR", "MRVL", "Broadcom", "NVIDIA",
            "Fabrinet", "FN", "Lumentum", "II-VI",
            "datacenter optical", "optics", "pluggable",
        ],
        "investment_tickers": ["AAOI", "LITE", "COHR", "FN", "MRVL"],
    },
    {
        "id":       "satellite",
        "label":    "衛星通訊 / ISL 雷射鏈路",
        "emoji":    "🛰️",
        "urls": [
            "https://www.trendforce.com/tag/satellite/feed/",
            "https://www.trendforce.com/tag/leo/feed/",
        ],
        "fallback_url": "https://www.trendforce.com/feed/",
        "keywords": [
            "satellite", "LEO", "MEO", "GEO", "constellation", "Starlink",
            "Kuiper", "OneWeb", "Telesat", "Iridium",
            "inter-satellite link", "ISL", "laser communication",
            "free-space optical", "FSO", "Mynaric", "Tesat",
            "direct-to-device", "D2D", "NTN", "non-terrestrial",
            "ASTS", "AST SpaceMobile", "Rocket Lab", "RKLB",
            "satellite broadband", "satellite IoT", "space",
            "launch", "payload", "orbit", "transponder",
        ],
        "investment_tickers": ["ASTS", "RKLB", "IRDM", "MYNA", "GSAT", "COHR"],
    },
    {
        "id":       "semi_packaging",
        "label":    "先進封裝 / AI 晶片",
        "emoji":    "⚙️",
        "urls": [
            "https://www.trendforce.com/tag/advanced-packaging/feed/",
            "https://www.trendforce.com/tag/ai-chip/feed/",
            "https://www.trendforce.com/tag/tsmc/feed/",
        ],
        "fallback_url": "https://www.trendforce.com/feed/",
        "keywords": [
            "CoWoS", "SoIC", "advanced packaging", "HBM stacking",
            "TSMC", "wafer", "N2", "N3", "N3E", "2nm",
            "NVIDIA", "AMD", "Broadcom", "custom silicon", "ASIC",
            "AI accelerator", "GPU", "TPU", "inference", "training",
            "CapEx", "wafer capacity", "loading", "utilization",
        ],
        "investment_tickers": ["TSM", "NVDA", "AMD", "AVGO"],
    },
]

# ─── RSS 抓取 ─────────────────────────────────────────────────────────────────

_HEADERS = {"User-Agent": "TrendForceMonitor/1.0 (research bot)"}


def _fetch_rss(url: str, hours: int) -> list[dict]:
    """從 RSS URL 抓取文章，回傳 {title, link, summary, published} 清單"""
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            root = ET.fromstring(resp.read())
    except Exception as e:
        print(f"  [trendforce] RSS 抓取失敗 {url}: {e}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    articles = []

    for item in root.iter("item"):
        title   = (item.findtext("title") or "").strip()
        link    = (item.findtext("link")  or "").strip()
        pub_raw = item.findtext("pubDate") or ""
        desc    = (item.findtext("description") or "").strip()

        # 清除 HTML tags
        import re
        desc_clean = re.sub(r"<[^>]+>", "", desc)[:400]

        try:
            from email.utils import parsedate_to_datetime
            pub_dt = parsedate_to_datetime(pub_raw).astimezone(timezone.utc)
        except Exception:
            pub_dt = datetime.now(timezone.utc)

        if pub_dt < cutoff:
            continue

        articles.append({
            "title":     title,
            "link":      link,
            "summary":   desc_clean,
            "published": pub_dt.isoformat(),
        })

    return articles


def fetch_topic(topic: dict, hours: int = LOOKBACK_HOURS) -> list[dict]:
    """嘗試每個 tag RSS；若均為空，用 fallback 主 RSS 再過濾關鍵字"""
    seen_links = set()
    results    = []

    for url in topic["urls"]:
        for art in _fetch_rss(url, hours):
            if art["link"] not in seen_links:
                seen_links.add(art["link"])
                results.append(art)
        time.sleep(0.3)

    # 若 tag RSS 收不到資料，用主 feed 過濾
    if not results and topic.get("fallback_url"):
        for art in _fetch_rss(topic["fallback_url"], hours):
            text = (art["title"] + " " + art["summary"]).lower()
            if any(k.lower() in text for k in topic["keywords"]):
                if art["link"] not in seen_links:
                    seen_links.add(art["link"])
                    results.append(art)

    return results


# ─── 關鍵字二次過濾 ───────────────────────────────────────────────────────────

def _is_relevant(art: dict, keywords: list[str]) -> bool:
    text = (art["title"] + " " + art["summary"]).lower()
    return any(k.lower() in text for k in keywords)


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
        print(f"  [trendforce] Telegram 推播失敗: {e}")
        return False


def _format_card(topic: dict, articles: list[dict]) -> str:
    now   = datetime.now().strftime("%Y-%m-%d %H:%M")
    emoji = topic["emoji"]
    label = topic["label"]
    ticks = "  ".join(f"#{t}" for t in topic["investment_tickers"])

    lines = [
        f"{emoji} <b>TrendForce — {label}</b>  {now}",
        f"<i>關聯標的：{ticks}</i>",
        "",
    ]

    for art in articles[:6]:
        pub = art["published"][:10]
        title_short = art["title"][:120]
        summary_short = art["summary"][:200].replace("\n", " ")
        lines.append(f"📄 <b>{title_short}</b>  [{pub}]")
        if summary_short:
            lines.append(f"   {summary_short}…")
        lines.append(f'   <a href="{art["link"]}">→ 原文</a>')
        lines.append("")

    lines.append(f"共 {len(articles)} 篇命中（顯示前 6）")
    return "\n".join(lines)


# ─── 主流程 ───────────────────────────────────────────────────────────────────

def run() -> dict:
    print("[trendforce] 開始抓取 TrendForce 報告...")
    date_str = datetime.now().strftime("%Y%m%d")

    all_results   = {}
    all_alerts    = []
    total_articles = 0

    for topic in TOPICS:
        tid   = topic["id"]
        label = topic["label"]
        print(f"  [{tid}] 抓取 {label}...")

        articles = fetch_topic(topic)

        # 二次關鍵字過濾
        filtered = [a for a in articles if _is_relevant(a, topic["keywords"])]
        total_articles += len(filtered)

        if filtered:
            _tg_send(_format_card(topic, filtered))
            print(f"  [{tid}] {len(filtered)} 篇命中 → 已推播")
            for art in filtered[:3]:
                all_alerts.append({
                    "level":  "觀察",
                    "source": "TrendForce",
                    "topic":  label,
                    "title":  art["title"],
                    "link":   art["link"],
                })
        else:
            print(f"  [{tid}] 過去 {LOOKBACK_HOURS}h 無新文章")

        all_results[tid] = {
            "topic":    label,
            "count":    len(filtered),
            "articles": filtered,
        }
        time.sleep(0.5)

    # 存檔
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"trendforce_{date_str}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"[trendforce] ✅ 結果存入 {out_path}（共 {total_articles} 篇）")

    return {
        "status": "ok",
        "total":  total_articles,
        "topics": all_results,
        "alerts": all_alerts,
        "report": f"TrendForce 今日命中 {total_articles} 篇（記憶體 / CPO / 封裝）",
    }


if __name__ == "__main__":
    run()
