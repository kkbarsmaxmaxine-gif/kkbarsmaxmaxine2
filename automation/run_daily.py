"""
run_daily.py — 完整每日掃描執行器（七模組）
Layer 1: sentiment + sector_rotation + smart_money + insider + taiwan_chain + kol_monitor + us_watchlist
Layer 3: claude_report
Layer 4: notify (Telegram)

每日執行：python3 automation/run_daily.py
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from modules import (
    sentiment, sector_rotation, smart_money, insider,
    taiwan_chain, kol_monitor, us_watchlist,
    claude_report, notify,
)


def run_daily_scan() -> None:
    start    = datetime.now()
    date_str = start.strftime("%Y-%m-%d %H:%M")

    print(f"\n{'='*60}")
    print(f"  每日市場掃描 FINAL  {date_str}")
    print(f"{'='*60}\n")

    scan_results = {}

    layer1 = [
        ("sentiment",    "CNN Fear & Greed",    sentiment),
        ("sector",       "板塊輪動",             sector_rotation),
        ("smart_money",  "聰明錢籌碼",           smart_money),
        ("insider",      "SEC 內部人申報",       insider),
        ("us_watchlist", "美股個股掃描",          us_watchlist),
        ("taiwan",       "台股三大法人",          taiwan_chain),
        ("kol",          "財經新聞 RSS",         kol_monitor),
    ]

    for key, label, mod in layer1:
        print(f"▶ {label}...")
        try:
            scan_results[key] = mod.run()
        except Exception as e:
            print(f"  ⚠️ 失敗: {e}")
            scan_results[key] = {"status": "error", "alerts": [], "report": ""}
        print()

    # Layer 3: AI 報告
    print("▶ AI 報告生成...")
    try:
        report_result = claude_report.run(scan_results)
        ai_report     = report_result.get("report", "")
        engine        = report_result.get("engine", "rules")
    except Exception as e:
        print(f"  ⚠️ 報告生成失敗: {e}")
        ai_report, engine = "", "error"
    print()

    # Layer 4: Telegram 推播
    print("▶ Telegram 推播...")
    try:
        notify.run(scan_results, ai_report)
    except Exception as e:
        print(f"  ⚠️ 推播失敗: {e}")
    print()

    # 彙總
    all_alerts = []
    for key in scan_results:
        all_alerts += scan_results[key].get("alerts", [])

    warn  = sum(1 for a in all_alerts if "警示" in a.get("level", ""))
    pos   = sum(1 for a in all_alerts if "正向" in a.get("level", ""))
    watch = sum(1 for a in all_alerts if "觀察" in a.get("level", ""))

    elapsed = (datetime.now() - start).seconds
    print(f"{'='*60}")
    print(f"  完成 | 耗時 {elapsed}s | 引擎：{engine}")
    print(f"  訊號：總 {len(all_alerts)} | ⚠️ 警示 {warn} | ✅ 正向 {pos} | 📌 觀察 {watch}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    run_daily_scan()
