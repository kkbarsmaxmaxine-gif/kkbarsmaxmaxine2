"""
optics_report.py — Optical communications daily/weekly report generator (zh-TW)
Reads data/watchlist.yaml + latest decision_packet, outputs reports/daily/YYYYMMDD.md
"""

import json
import os
import yaml
from datetime import datetime
from pathlib import Path

ROOT       = Path(__file__).parents[2]
WATCHLIST  = ROOT / "data" / "watchlist.yaml"
PACKET_DIR = ROOT / "decision_system" / "packets"
DAILY_DIR  = ROOT / "reports" / "daily"
WEEKLY_DIR = ROOT / "reports" / "weekly"


def load_watchlist() -> dict:
    with open(WATCHLIST, encoding="utf-8") as f:
        return yaml.safe_load(f)


def tickers_by_symbol(wl: dict) -> dict:
    """Convert list-based tickers to a dict keyed by symbol for easy lookup."""
    return {t["ticker"]: t for t in wl.get("tickers", [])}


def load_packet(date_str: str) -> dict:
    path = PACKET_DIR / f"decision_packet_{date_str}.json"
    if not path.exists():
        print(f"[optics_report] no packet for {date_str}, using empty data")
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _fmt_ret(val) -> str:
    return f"{val:+.1f}%" if val is not None else "—"


def _fmt_vol(val) -> str:
    return f"{val:.1f}x 均量" if val is not None else "—"


def ticker_section(sym: str, info: dict, raw: dict) -> str:
    company = info.get("company", sym)
    layers  = " / ".join(info.get("layer", []))
    d       = raw.get(sym, {})
    price   = d.get("price", "—")
    ret_1d  = d.get("ret_1d", None)
    rsi     = d.get("rsi", "—")
    vol     = d.get("vol_ratio", None)

    bull = "\n".join(f"  - {t}" for t in info.get("bull_triggers", []))
    bear = "\n".join(f"  - {t}" for t in info.get("bear_triggers", []))
    checkpoints = "\n".join(f"  - {c}" for c in info.get("next_checkpoints", []))

    return f"""### {sym} — {company}
**層位**：{layers}
**現價**：${price}  |  **單日**：{_fmt_ret(ret_1d)}  |  **量比**：{_fmt_vol(vol)}  |  **RSI**：{rsi}

#### 1. 最新動態（過去 48 小時）
_需要即時新聞查詢——本機執行 `/watch-optics` 或透過新聞 API 擴充此腳本。_

#### 2. 論點評估：強化 / 弱化 / 不變
**多頭觸發條件**：
{bull}

**空頭觸發條件**：
{bear}

_評估後標記三選一，對應具體觸發項目。_

#### 3. 產能訊號
_參考 next_checkpoints：_
{checkpoints}

#### 4. 客戶集中度變化
_查閱最新季報及法說會管理層評論。_

#### 5. 毛利率與稀釋訊號
_查閱最新毛利率趨勢、流通股數、負債水位。_

#### 6. 下一個關鍵檢查點
_填入法說會日期、投資人日或產品里程碑。_

---
"""


def priority_signal_table(signals: list[str]) -> str:
    rows = "\n".join(
        f"| {s} | — | — |"
        for s in signals
    )
    return f"""### 跨股訊號掃描

| 訊號類型 | 觸發情況 | 影響標的 |
|---------|---------|---------|
{rows}
"""


def build_daily_report(wl: dict, packet: dict) -> str:
    date_str  = datetime.now().strftime("%Y-%m-%d")
    raw       = packet.get("raw_tickers", {})
    mkt       = packet.get("market_summary", {})
    ticker_map = tickers_by_symbol(wl)
    order      = [t["ticker"] for t in wl.get("tickers", [])]
    signals    = wl.get("monitoring_rules", {}).get("priority_signals", [])
    global_th  = wl.get("global_thesis", [])

    qqq  = mkt.get("qqq_1d",  "—")
    soxx = mkt.get("soxx_1d", "—")
    qqq_str  = f"{qqq:+.2f}%"  if isinstance(qqq,  float) else str(qqq)
    soxx_str = f"{soxx:+.2f}%" if isinstance(soxx, float) else str(soxx)

    lines = [
        f"# 光通訊族群監控日報 — {date_str}",
        "",
        f"**市場基準**：QQQ {qqq_str}  SOXX {soxx_str}",
        "",
        "## 全局假設",
        "",
        *[f"- {t}" for t in global_th],
        "",
        "---",
        "",
    ]

    for sym in order:
        info = ticker_map.get(sym, {"ticker": sym})
        lines.append(ticker_section(sym, info, raw))

    lines.append(priority_signal_table(signals))

    # Sector pulse scaffold
    sorted_ret = sorted(
        order,
        key=lambda s: -(raw.get(s, {}).get("ret_1d") or 0)
    )
    ranking = "  ".join(
        f"{s}（{_fmt_ret(raw.get(s, {}).get('ret_1d'))}）"
        for s in sorted_ret
    )

    lines += [
        "",
        "---",
        "",
        "### 今日族群脈動",
        "",
        f"- **CPO 動能**：_待評估_",
        f"- **單日強弱排序**：{ranking}",
        f"- **供應鏈訊號**：_AXTI → LITE/AAOI → COHR 需求鏈有無異動？_",
        f"- **論點壓力測試**：_今日哪件事最挑戰 CPO 多頭假設？_",
        f"- **下週重點觀察**：_填入跨族群最重要的 2 個事件_",
        "",
    ]
    return "\n".join(lines)


def build_weekly_report(wl: dict) -> str:
    today     = datetime.now()
    week      = today.strftime("W%V")
    order     = [t["ticker"] for t in wl.get("tickers", [])]
    global_th = wl.get("global_thesis", [])

    lines = [
        f"# 光通訊族群週報 — {today.strftime('%Y')}-{week}",
        "",
        "## 本週回顧",
        "",
        "_彙整本週五份日報。_",
        "",
        "## 各標的論點進展",
        "",
        *[f"- **{sym}**：強化 / 弱化 / 不變 — _說明原因_" for sym in order],
        "",
        "## 本週最高信心多頭",
        "_標的 + 一句話理由_",
        "",
        "## 本週最高疑慮標的",
        "_標的 + 一句話理由_",
        "",
        "## CPO 論點整體評級",
        "_上調 / 下調 / 維持 — 一段話說明_",
        "",
        "## Global Thesis 本週驗證",
        "",
        *[f"- "{t}"\n  驗證結果：_填入_" for t in global_th],
        "",
    ]
    return "\n".join(lines)


def run():
    report_type = os.getenv("REPORT_TYPE", "daily")
    date_str    = datetime.now().strftime("%Y%m%d")
    wl          = load_watchlist()

    if report_type == "weekly":
        today = datetime.now()
        week  = today.strftime("W%V")
        out   = WEEKLY_DIR / f"{today.strftime('%Y')}-{week}.md"
        WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
        out.write_text(build_weekly_report(wl), encoding="utf-8")
        print(f"[optics_report] 週報 → {out}")
    else:
        packet = load_packet(date_str)
        out    = DAILY_DIR / f"{date_str}.md"
        DAILY_DIR.mkdir(parents=True, exist_ok=True)
        out.write_text(build_daily_report(wl, packet), encoding="utf-8")
        print(f"[optics_report] 日報 → {out}")


if __name__ == "__main__":
    run()
