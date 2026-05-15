"""
optics_report.py — Optical communications daily report generator (zh-TW)
Reads data/watchlist.yaml + latest decision_packet, calls MiniMax for analysis,
outputs reports/daily/REPORT_FILENAME (default: YYYYMMDD.md)
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

OPTICS_TICKERS = ["AAOI", "LITE", "COHR", "MRVL", "NOK", "AXTI"]


def load_watchlist() -> dict:
    with open(WATCHLIST, encoding="utf-8") as f:
        return yaml.safe_load(f)


def tickers_by_symbol(wl: dict) -> dict:
    return {t["ticker"]: t for t in wl.get("tickers", [])}


def load_packet(date_str: str) -> dict:
    path = PACKET_DIR / f"decision_packet_{date_str}.json"
    if not path.exists():
        print(f"[optics_report] no packet for {date_str}, using empty market data")
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _fmt_ret(val) -> str:
    return f"{val:+.1f}%" if val is not None else "—"


def _fmt_vol(val) -> str:
    return f"{val:.1f}x 均量" if val is not None else "—"


def build_market_snapshot(wl: dict, packet: dict) -> str:
    """Build structured text snapshot to feed to MiniMax."""
    date_str   = datetime.now().strftime("%Y-%m-%d")
    raw        = packet.get("raw_tickers", {})
    mkt        = packet.get("market_summary", {})
    ticker_map = tickers_by_symbol(wl)
    global_th  = wl.get("global_thesis", [])
    signals    = packet.get("signals", [])

    lines = [
        f"# 光通訊族群市場快照 — {date_str}",
        "",
        f"市場基準：QQQ {mkt.get('qqq_1d', '—')}%  SOXX {mkt.get('soxx_1d', '—')}%",
        "",
        "## 全局假設",
        *[f"- {t}" for t in global_th],
        "",
        "## 個股數據",
    ]

    for sym in OPTICS_TICKERS:
        d    = raw.get(sym, {})
        info = ticker_map.get(sym, {})
        lines += [
            f"",
            f"### {sym} — {info.get('company', sym)}",
            f"層位: {', '.join(info.get('layer', []))}",
            f"現價: ${d.get('price','—')}  單日: {_fmt_ret(d.get('ret_1d'))}  "
            f"量比: {_fmt_vol(d.get('vol_ratio'))}  RSI: {d.get('rsi','—')}",
            f"EMA8/22交叉: {d.get('crossover','—')}  距3M高點: {d.get('pct_from_high_3m','—')}%",
            f"",
            f"論點: {info.get('thesis','').strip()}",
            f"多頭觸發: {'; '.join(info.get('bull_triggers', []))}",
            f"空頭觸發: {'; '.join(info.get('bear_triggers', []))}",
            f"下個檢查點: {'; '.join(info.get('next_checkpoints', []))}",
        ]

    # Add any signals from rules engine
    optics_signals = [s for s in signals if s.get("ticker") in OPTICS_TICKERS]
    if optics_signals:
        lines += ["", "## 規則引擎訊號"]
        for s in optics_signals:
            lines.append(f"- [{s.get('level','')}] {s.get('ticker')} {s.get('type','')}: {s.get('detail','')}")

    return "\n".join(lines)


def call_minimax(snapshot: str, wl: dict) -> str:
    """Call MiniMax via Anthropic-compatible SDK and return analysis text."""
    try:
        import anthropic
    except ImportError:
        return "_MiniMax 分析不可用（anthropic SDK 未安裝）_"

    base_url = os.getenv("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
    api_key  = os.getenv("MINIMAX_API_KEY", "")
    model    = os.getenv("LLM_MODEL", "MiniMax-M2.5")

    if not api_key:
        return "_MiniMax 分析不可用（MINIMAX_API_KEY 未設定）_"

    priority_signals = wl.get("monitoring_rules", {}).get("priority_signals", [])

    system_prompt = """你是光通訊產業研究專員。根據提供的市場快照，產生結構化繁體中文分析報告。

輸出格式嚴格遵守以下結構：

## 摘要
（2-3句整體市場狀況）

## 個股分析
對每一檔（AAOI / LITE / COHR / MRVL / NOK / AXTI）輸出：
### [TICKER]
**論點評估**: 強化 / 弱化 / 不變 — 一句話說明（必須對應具體多頭或空頭觸發條件）
**技術訊號**: 根據 RSI / EMA 交叉 / 量比 說明
**下個檢查點**: 最重要的一個

## 跨股訊號
依序掃描以下訊號，有觸發則說明，無則標「—」：
""" + "\n".join(f"- {s}" for s in priority_signals) + """

## 今日族群脈動
- CPO 動能: 加速 / 穩定 / 降溫
- 單日強弱排序: 由強到弱
- 供應鏈訊號: AXTI→LITE/AAOI→COHR 鏈有無異動
- 論點壓力測試: 今日最挑戰 CPO 多頭假設的事實

## 優先觀察清單
列出未來 2 週最值得追蹤的 3 個事件或數據點

## 下個檢查點
整體族群最重要的一個里程碑

規則：不捏造數據。若數據不足，明確說明「數據不足，無法判斷」。"""

    client = anthropic.Anthropic(base_url=base_url, api_key=api_key)
    try:
        message = client.messages.create(
            model=model,
            max_tokens=3500,
            system=system_prompt,
            messages=[{"role": "user", "content": snapshot}],
        )
        return next((b.text for b in message.content if hasattr(b, "text")), "（無輸出）")
    except Exception as e:
        return f"_MiniMax 呼叫失敗: {e}_"


def build_report(wl: dict, packet: dict, analysis: str) -> str:
    date_str   = datetime.now().strftime("%Y-%m-%d")
    mkt        = packet.get("market_summary", {})
    raw        = packet.get("raw_tickers", {})

    qqq_str  = f"{mkt['qqq_1d']:+.2f}%"  if isinstance(mkt.get("qqq_1d"),  float) else "—"
    soxx_str = f"{mkt['soxx_1d']:+.2f}%" if isinstance(mkt.get("soxx_1d"), float) else "—"

    sorted_ret = sorted(
        OPTICS_TICKERS,
        key=lambda s: -(raw.get(s, {}).get("ret_1d") or 0)
    )
    ranking = "  ".join(
        f"{s}（{_fmt_ret(raw.get(s, {}).get('ret_1d'))}）" for s in sorted_ret
    )

    return f"""# 光通訊族群監控日報 — {date_str}

**市場基準**：QQQ {qqq_str}  SOXX {soxx_str}
**單日強弱**：{ranking}

---

{analysis}

---
_報告由 MiniMax M2.5 生成 | {date_str}_
"""


def run():
    date_str      = datetime.now().strftime("%Y%m%d")
    report_type   = os.getenv("REPORT_TYPE", "daily")
    filename      = os.getenv("REPORT_FILENAME", f"{date_str}.md")
    wl            = load_watchlist()
    packet        = load_packet(date_str)

    print(f"[optics_report] 產生 {report_type} 報告...")
    snapshot = build_market_snapshot(wl, packet)
    analysis = call_minimax(snapshot, wl)
    report   = build_report(wl, packet, analysis)

    if report_type == "weekly":
        out = WEEKLY_DIR / filename
        WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    else:
        out = DAILY_DIR / filename
        DAILY_DIR.mkdir(parents=True, exist_ok=True)

    out.write_text(report, encoding="utf-8")
    print(f"[optics_report] ✅ 報告存入 {out}")


if __name__ == "__main__":
    run()
