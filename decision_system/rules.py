"""
rules.py — 訊號規則引擎
讀取 data/YYYYMMDD_raw.json，輸出 packets/decision_packet_YYYYMMDD.json
"""

import json
import os
import sys
from datetime import datetime
from typing import Optional

DATA_DIR    = os.path.join(os.path.dirname(__file__), "data")
PACKET_DIR  = os.path.join(os.path.dirname(__file__), "packets")

BIG_MOVE_PCT    = 4.0
VOLUME_SPIKE    = 2.0
NEAR_HIGH_PCT   = 3.0    # 距3M高點 3% 以內
RSI_OVERBOUGHT  = 72.0
RSI_OVERSOLD    = 32.0

FOCUS_STOCKS = ["DDOG", "NET", "FN", "ETN", "PLTR", "CSCO", "NVDA", "AMD", "AVGO", "MU", "TSM", "8299.TWO"]
BENCHMARKS   = ["QQQ", "SPY", "SOXX", "XLK"]


def load_raw(date_str: Optional[str] = None) -> dict:
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    path = os.path.join(DATA_DIR, f"{date_str}_raw.json")
    if not os.path.exists(path):
        print(f"[rules] 找不到 {path}，請先執行 collector.py")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def detect_signals(tickers: dict, qqq_1m: float) -> list[dict]:
    signals = []

    for sym, d in tickers.items():
        if sym in BENCHMARKS:
            continue

        ret  = d["ret_1d"]
        vol  = d.get("vol_ratio") or 0.0
        rsi  = d["rsi"]
        name = d["name"]

        # 大漲
        if ret >= BIG_MOVE_PCT:
            signals.append({
                "type": "大漲", "ticker": sym, "name": name, "level": "正向",
                "detail": f"單日 +{ret:.1f}%  現價 ${d['price']}",
                "vol_tag": f"爆量 {vol:.1f}x" if vol >= VOLUME_SPIKE else "",
            })

        # 大跌
        if ret <= -BIG_MOVE_PCT:
            signals.append({
                "type": "大跌", "ticker": sym, "name": name, "level": "警示",
                "detail": f"單日 {ret:.1f}%  現價 ${d['price']}",
                "vol_tag": f"爆量 {vol:.1f}x" if vol >= VOLUME_SPIKE else "",
            })

        # 爆量但幅度小（異常籌碼）
        if vol >= VOLUME_SPIKE and abs(ret) < BIG_MOVE_PCT:
            direction = "疑似吸籌" if ret > 0 else "疑似出貨"
            signals.append({
                "type": f"爆量{direction}", "ticker": sym, "name": name, "level": "觀察",
                "detail": f"量 {vol:.1f}x 均量  漲跌 {ret:+.1f}%",
                "vol_tag": "",
            })

        # EMA 金叉 / 死叉
        if d["crossover"] in ("golden_cross", "death_cross"):
            is_bull = d["crossover"] == "golden_cross"
            signals.append({
                "type": "金叉" if is_bull else "死叉",
                "ticker": sym, "name": name,
                "level": "正向" if is_bull else "警示",
                "detail": f"EMA8 {'穿越' if is_bull else '跌破'} EMA22  現價 ${d['price']}",
                "vol_tag": "",
            })

        # 逼近3M新高
        if d["pct_from_high_3m"] >= -NEAR_HIGH_PCT and ret > 0:
            signals.append({
                "type": "逼近3M高點", "ticker": sym, "name": name, "level": "正向",
                "detail": f"距高點 {d['pct_from_high_3m']:.1f}%  現價 ${d['price']}  3M高 ${d['high_3m']}",
                "vol_tag": "",
            })

        # RSI 超買/超賣
        if rsi >= RSI_OVERBOUGHT:
            signals.append({
                "type": "RSI超買", "ticker": sym, "name": name, "level": "警示",
                "detail": f"RSI {rsi:.1f}  現價 ${d['price']}",
                "vol_tag": "",
            })
        elif rsi <= RSI_OVERSOLD:
            signals.append({
                "type": "RSI超賣", "ticker": sym, "name": name, "level": "觀察",
                "detail": f"RSI {rsi:.1f}  現價 ${d['price']}",
                "vol_tag": "",
            })

        # 相對 QQQ 1M 強弱（個別訊號不在這裡，排名另外做）

    return signals


def build_rankings(tickers: dict, qqq_1m: float) -> dict:
    stocks = {k: v for k, v in tickers.items() if k not in BENCHMARKS}

    sorted_1d = sorted(stocks.items(), key=lambda x: -x[1]["ret_1d"])
    sorted_1m = sorted(stocks.items(), key=lambda x: -x[1]["ret_1m"])
    rel_1m    = sorted(stocks.items(), key=lambda x: -(x[1]["ret_1m"] - qqq_1m))

    def fmt(items):
        return [{"ticker": k, "name": v["name"], "ret_1d": v["ret_1d"],
                 "ret_1m": v["ret_1m"], "price": v["price"]} for k, v in items]

    return {
        "top5_1d":    fmt(sorted_1d[:5]),
        "bottom5_1d": fmt(sorted_1d[-5:]),
        "top5_1m":    fmt(sorted_1m[:5]),
        "bottom5_1m": fmt(sorted_1m[-5:]),
        "leaders_vs_qqq":  fmt(rel_1m[:3]),
        "laggards_vs_qqq": fmt(rel_1m[-3:]),
    }


def build_focus_snapshot(tickers: dict) -> dict:
    result = {}
    for sym in FOCUS_STOCKS:
        if sym not in tickers:
            continue
        d = tickers[sym]
        ema_spread = round((d["ema8"] / d["ema22"] - 1) * 100, 2)
        above_ema50  = d["price"] > d["ema50"]
        above_ema200 = d["price"] > d["ema200"]

        if d["price"] > d["ema8"] > d["ema22"] > d["ema50"]:
            trend = "多頭排列"
        elif d["price"] < d["ema8"] < d["ema22"]:
            trend = "空頭排列"
        else:
            trend = "整理"

        result[sym] = {
            **d,
            "ema_spread_8_22": ema_spread,
            "above_ema50":     above_ema50,
            "above_ema200":    above_ema200,
            "trend":           trend,
        }
    return result


def run(date_str: Optional[str] = None) -> dict:
    raw = load_raw(date_str)
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    tickers = raw["tickers"]
    qqq_1m  = tickers.get("QQQ", {}).get("ret_1m", 0.0)
    qqq_1d  = tickers.get("QQQ", {}).get("ret_1d", 0.0)
    spy_1d  = tickers.get("SPY", {}).get("ret_1d", 0.0)
    soxx_1d = tickers.get("SOXX", {}).get("ret_1d", 0.0)

    signals  = detect_signals(tickers, qqq_1m)
    rankings = build_rankings(tickers, qqq_1m)
    focus    = build_focus_snapshot(tickers)

    warn  = [s for s in signals if s["level"] == "警示"]
    pos   = [s for s in signals if s["level"] == "正向"]
    watch = [s for s in signals if s["level"] == "觀察"]

    packet = {
        "date":    raw["date"],
        "market_summary": {
            "qqq_1d":  round(qqq_1d, 2),
            "spy_1d":  round(spy_1d, 2),
            "soxx_1d": round(soxx_1d, 2),
            "qqq_1m":  round(qqq_1m, 2),
        },
        "signal_counts": {
            "total": len(signals),
            "warning": len(warn),
            "positive": len(pos),
            "watch": len(watch),
        },
        "signals":        signals,
        "rankings":       rankings,
        "focus_stocks":   focus,
        "raw_tickers":    tickers,
    }

    os.makedirs(PACKET_DIR, exist_ok=True)
    out_path = os.path.join(PACKET_DIR, f"decision_packet_{date_str}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(packet, f, ensure_ascii=False, indent=2)

    print(f"[rules] ✅ decision_packet 存入 {out_path}")
    print(f"[rules]    訊號：總 {len(signals)}  ⚠️{len(warn)}  ✅{len(pos)}  📌{len(watch)}")
    return packet


if __name__ == "__main__":
    run()
