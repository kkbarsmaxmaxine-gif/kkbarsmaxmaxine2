"""
journal_writer.py — 交易日誌生成器
讀取 decision_packet，輸出 journal/YYYYMMDD_journal.md
資料區塊自動填入；用戶判斷區塊留空供人工填寫
"""

import json
import os
import sys
from datetime import datetime
from typing import Optional

PACKET_DIR  = os.path.join(os.path.dirname(__file__), "packets")
JOURNAL_DIR = os.path.join(os.path.dirname(__file__), "journal")


def load_packet(date_str: Optional[str] = None) -> dict:
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    path = os.path.join(PACKET_DIR, f"decision_packet_{date_str}.json")
    if not os.path.exists(path):
        print(f"[journal] 找不到 {path}，請先執行 rules.py")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fmt_signal_line(s: dict) -> str:
    icon = {"警示": "⚠️", "正向": "✅", "觀察": "📌"}.get(s["level"], "·")
    vol  = f" [{s['vol_tag']}]" if s.get("vol_tag") else ""
    return f"- {icon} **{s['type']}** {s['name']}({s['ticker']}){vol}  \n  {s['detail']}"


def fmt_stock_row(sym: str, d: dict, qqq_1m: float) -> str:
    rel = round(d["ret_1m"] - qqq_1m, 1)
    trend_icon = {"多頭排列": "📈", "空頭排列": "📉", "整理": "📊"}.get(d.get("trend", ""), "·")
    cross = {
        "golden_cross": " 🟢金叉",
        "death_cross":  " 🔴死叉",
    }.get(d.get("crossover", ""), "")
    rsi_warn = " ⚠️超買" if d["rsi"] >= 72 else (" 🟢超賣" if d["rsi"] <= 32 else "")
    return (
        f"| {sym} | {d['name']} | ${d['price']:.2f} | "
        f"{d['ret_1d']:+.1f}% | {d['ret_1m']:+.1f}% | {rel:+.1f}% | "
        f"{trend_icon}{cross} | RSI {d['rsi']:.0f}{rsi_warn} |"
    )


def build_journal(packet: dict) -> str:
    date       = packet["date"]
    ms         = packet["market_summary"]
    signals    = packet["signals"]
    rankings   = packet["rankings"]
    focus      = packet["focus_stocks"]
    sc         = packet["signal_counts"]
    qqq_1m     = ms["qqq_1m"]

    warn_signals  = [s for s in signals if s["level"] == "警示"]
    pos_signals   = [s for s in signals if s["level"] == "正向"]
    watch_signals = [s for s in signals if s["level"] == "觀察"]

    lines = [
        f"# 交易日誌  {date}",
        "",
        "---",
        "",
        "## 一、市場快照（事實）",
        "",
        f"| 指數 | 今日 |",
        f"|------|------|",
        f"| QQQ  | {ms['qqq_1d']:+.2f}% |",
        f"| SPY  | {ms['spy_1d']:+.2f}% |",
        f"| SOXX | {ms['soxx_1d']:+.2f}% |",
        f"| QQQ 1M | {ms['qqq_1m']:+.2f}% |",
        "",
        f"訊號總數：{sc['total']}  ⚠️ {sc['warning']}  ✅ {sc['positive']}  📌 {sc['watch']}",
        "",
        "---",
        "",
        "## 二、今日訊號",
        "",
    ]

    if warn_signals:
        lines.append("### ⚠️ 警示訊號")
        lines += [fmt_signal_line(s) for s in warn_signals]
        lines.append("")
    if pos_signals:
        lines.append("### ✅ 正向訊號")
        lines += [fmt_signal_line(s) for s in pos_signals]
        lines.append("")
    if watch_signals:
        lines.append("### 📌 觀察訊號")
        lines += [fmt_signal_line(s) for s in watch_signals]
        lines.append("")

    # Rankings
    lines += [
        "---",
        "",
        "## 三、強弱排名",
        "",
        "**今日領漲**",
    ]
    for r in rankings.get("top5_1d", []):
        lines.append(f"- {r['name']}({r['ticker']}) {r['ret_1d']:+.1f}%")
    lines.append("")
    lines.append("**今日領跌**")
    for r in rankings.get("bottom5_1d", []):
        lines.append(f"- {r['name']}({r['ticker']}) {r['ret_1d']:+.1f}%")
    lines.append("")
    lines.append("**本月相對 QQQ 領漲**")
    for r in rankings.get("leaders_vs_qqq", []):
        rel = round(r["ret_1m"] - qqq_1m, 1)
        lines.append(f"- {r['name']}({r['ticker']}) 1M {r['ret_1m']:+.1f}%  vs QQQ {rel:+.1f}%")
    lines.append("")
    lines.append("**本月相對 QQQ 落後**")
    for r in rankings.get("laggards_vs_qqq", []):
        rel = round(r["ret_1m"] - qqq_1m, 1)
        lines.append(f"- {r['name']}({r['ticker']}) 1M {r['ret_1m']:+.1f}%  vs QQQ {rel:+.1f}%")
    lines.append("")

    # Focus stocks table
    lines += [
        "---",
        "",
        "## 四、重點個股狀態",
        "",
        "| 代號 | 名稱 | 現價 | 今日 | 1M | vs QQQ | 趨勢/訊號 | RSI |",
        "|------|------|------|------|----|--------|-----------|-----|",
    ]
    for sym, d in focus.items():
        lines.append(fmt_stock_row(sym, d, qqq_1m))
    lines.append("")

    # === 用戶判斷區塊（留空）===
    lines += [
        "---",
        "",
        "## 五、我的判斷（人工填寫）",
        "",
        "### 今日市場結構解讀",
        "> （一句話：今天市場在告訴我什麼？）",
        "",
        "_填入_",
        "",
        "### 今日決策點",
        "- [ ] ",
        "- [ ] ",
        "",
        "### 持倉相關",
        "| 個股 | 目前狀態 | 今日動作 | 理由 |",
        "|------|----------|----------|------|",
        "| DDOG | | | |",
        "| NET  | | | |",
        "| FN   | | | |",
        "| ETN  | | | |",
        "",
        "---",
        "",
        "## 六、七維分析（MiniMax 填入）",
        "",
        "<!-- call_minimax.py 執行後自動填入以下區塊 -->",
        "",
        "### 1. 事實",
        "_待 AI 分析_",
        "",
        "### 2. 推論",
        "_待 AI 分析_",
        "",
        "### 3. 反方論點",
        "_待 AI 分析_",
        "",
        "### 4. 驗證指標",
        "_待 AI 分析_",
        "",
        "### 5. 失效條件",
        "_待 AI 分析_",
        "",
        "### 6. 交易計畫",
        "_待 AI 分析_",
        "",
        "### 7. 今天我哪裡可能被敘事帶著走",
        "_待 AI 分析_",
        "",
        "---",
        "",
        "## 七、三十天後回顧",
        "",
        "> 填寫日期：___",
        "",
        "- 今日判斷哪裡對了？",
        "- 今日判斷哪裡錯了？",
        "- 被敘事帶走的部分，後來怎麼了？",
        "",
    ]

    return "\n".join(lines)


def run(date_str: Optional[str] = None) -> str:
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    packet = load_packet(date_str)
    journal = build_journal(packet)

    os.makedirs(JOURNAL_DIR, exist_ok=True)
    out_path = os.path.join(JOURNAL_DIR, f"{date_str}_journal.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(journal)

    print(f"[journal] ✅ 日誌已生成 {out_path}")
    return out_path


if __name__ == "__main__":
    run()
