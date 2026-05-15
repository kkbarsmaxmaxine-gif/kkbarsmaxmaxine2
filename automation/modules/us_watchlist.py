"""
us_watchlist.py — 美股核心個股每日掃描
Layer 1 模組：追蹤 AI 半導體 + 科技龍頭，偵測異常漲跌 / 爆量 / 強弱排序

監控清單：NVDA AMD AVGO MRVL MU ASML AMAT LRCX KLAC MSFT META GOOGL AMZN AAPL TSM QCOM INTC ARM SMCI PLTR
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
import os
import warnings
warnings.filterwarnings("ignore")

# ─── 參數區 ───────────────────────────────────────────────────────────────────
OUTPUT_DIR = "./automation/output"

# 監控清單（代號 → 中文名 / 說明）
US_WATCHLIST: dict[str, str] = {
    # AI 半導體核心
    "NVDA":  "輝達",
    "AMD":   "超微",
    "AVGO":  "博通",
    "MRVL":  "邁威爾",
    "MU":    "美光",
    "ASML":  "ASML",
    "AMAT":  "應用材料",
    "LRCX":  "科林研發",
    "KLAC":  "科磊",
    "QCOM":  "高通",
    "INTC":  "英特爾",
    "ARM":   "ARM",
    "SMCI":  "超微電腦",
    # 科技龍頭（AI 需求端）
    "MSFT":  "微軟",
    "META":  "Meta",
    "GOOGL": "Alphabet",
    "AMZN":  "亞馬遜",
    "AAPL":  "蘋果",
    # ADR
    "TSM":   "台積電ADR",
    # 事件交易
    "LITE":  "Lumentum",
    # CPO 光學製造
    "FN":    "Fabrinet",
    # 電力基建
    "ETN":   "伊頓",
    "PWR":   "Quanta Services",
    "STRL":  "Sterling Infra",
    "MYRG":  "MYR Group",
    "POWL":  "Powell Ind",
    # 其他
    "PLTR":  "Palantir",
    "NET":   "Cloudflare",
    "CSCO":  "Cisco",
    "DDOG":  "Datadog",
}

BENCHMARK       = "QQQ"
BIG_MOVE_PCT    = 4.0    # 單日漲跌 > 4% = 大波動
VOLUME_SPIKE    = 2.0    # 成交量 > 20日均量 2 倍 = 爆量
HIGH52W_PCT     = 1.02   # 距 52 週高點 2% 以內 = 新高


# ─── 資料抓取 ──────────────────────────────────────────────────────────────────
def fetch_data(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """下載個股近 3 個月日線資料"""
    end   = datetime.today()
    start = end - timedelta(days=90)
    results = {}
    all_tickers = tickers + [BENCHMARK]

    try:
        raw = yf.download(
            all_tickers,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        for ticker in all_tickers:
            try:
                if len(all_tickers) == 1:
                    df = raw.copy()
                else:
                    df = raw.xs(ticker, axis=1, level=1).dropna(how="all")
                if len(df) >= 5:
                    results[ticker] = df
            except Exception:
                pass
    except Exception as e:
        print(f"[us_watchlist] yfinance 下載失敗: {e}")
    return results


# ─── 個股分析 ──────────────────────────────────────────────────────────────────
def calc_stock_metrics(ticker: str, df: pd.DataFrame, bench_df: Optional[pd.DataFrame]) -> dict:
    """計算單股關鍵指標"""
    close  = df["Close"]
    volume = df["Volume"] if "Volume" in df.columns else pd.Series(dtype=float)

    price_now  = float(close.iloc[-1])
    price_1d   = float(close.iloc[-2]) if len(close) >= 2 else price_now
    price_5d   = float(close.iloc[-6]) if len(close) >= 6 else price_now
    price_1m   = float(close.iloc[-22]) if len(close) >= 22 else price_now
    price_3m   = float(close.iloc[0])

    ret_1d = (price_now / price_1d - 1) * 100
    ret_5d = (price_now / price_5d - 1) * 100
    ret_1m = (price_now / price_1m - 1) * 100
    ret_3m = (price_now / price_3m - 1) * 100

    high_52w = float(close.rolling(252, min_periods=len(close)).max().iloc[-1])
    low_52w  = float(close.rolling(252, min_periods=len(close)).min().iloc[-1])
    pct_from_high = (price_now / high_52w - 1) * 100

    # 成交量爆量
    vol_spike = False
    vol_ratio = None
    if len(volume) >= 21:
        avg20 = float(volume.iloc[-21:-1].mean())
        today_vol = float(volume.iloc[-1])
        if avg20 > 0:
            vol_ratio = today_vol / avg20
            vol_spike = vol_ratio >= VOLUME_SPIKE

    # 相對 QQQ 強弱（1M）
    rel_qqq_1m = None
    if bench_df is not None and len(bench_df) >= 22:
        b_now = float(bench_df["Close"].iloc[-1])
        b_1m  = float(bench_df["Close"].iloc[-22])
        qqq_1m = (b_now / b_1m - 1) * 100
        rel_qqq_1m = round(ret_1m - qqq_1m, 2)

    return {
        "ticker":        ticker,
        "name":          US_WATCHLIST.get(ticker, ticker),
        "price":         round(price_now, 2),
        "ret_1d":        round(ret_1d, 2),
        "ret_5d":        round(ret_5d, 2),
        "ret_1m":        round(ret_1m, 2),
        "ret_3m":        round(ret_3m, 2),
        "high_52w":      round(high_52w, 2),
        "low_52w":       round(low_52w, 2),
        "pct_from_high": round(pct_from_high, 2),
        "vol_spike":     vol_spike,
        "vol_ratio":     round(vol_ratio, 2) if vol_ratio else None,
        "rel_qqq_1m":    rel_qqq_1m,
    }


def analyze_all(data: dict[str, pd.DataFrame]) -> list[dict]:
    """分析所有個股"""
    bench_df = data.get(BENCHMARK)
    metrics = []
    for ticker in US_WATCHLIST:
        df = data.get(ticker)
        if df is None or len(df) < 2:
            continue
        m = calc_stock_metrics(ticker, df, bench_df)
        metrics.append(m)
    return metrics


# ─── 訊號偵測 ──────────────────────────────────────────────────────────────────
def detect_signals(metrics: list[dict]) -> list[dict]:
    """偵測異常訊號"""
    alerts = []

    # 排序：1D 漲幅
    sorted_1d = sorted(metrics, key=lambda x: -x["ret_1d"])

    # 大漲訊號
    for m in metrics:
        if m["ret_1d"] >= BIG_MOVE_PCT:
            vol_tag = f" 🔥爆量 {m['vol_ratio']:.1f}x" if m["vol_spike"] else ""
            alerts.append({
                "type":   f"單日大漲 — {m['name']}({m['ticker']})",
                "level":  "✅ 正向",
                "detail": f"單日 +{m['ret_1d']:.1f}%  現價 ${m['price']}{vol_tag}",
                "action": "確認是否有催化劑（財報、法說、分析師升評、產業訊號）",
            })

    # 大跌訊號
    for m in metrics:
        if m["ret_1d"] <= -BIG_MOVE_PCT:
            vol_tag = f" 🔥爆量 {m['vol_ratio']:.1f}x" if m["vol_spike"] else ""
            alerts.append({
                "type":   f"單日大跌 — {m['name']}({m['ticker']})",
                "level":  "⚠️ 警示",
                "detail": f"單日 {m['ret_1d']:.1f}%  現價 ${m['price']}{vol_tag}",
                "action": "確認下跌原因：財報不及預期 / 系統性拋售 / 個股利空",
            })

    # 爆量但漲跌幅不大（異常吸籌 / 出貨）
    for m in metrics:
        if m["vol_spike"] and abs(m["ret_1d"]) < BIG_MOVE_PCT:
            direction = "吸籌" if m["ret_1d"] > 0 else "出貨"
            alerts.append({
                "type":   f"爆量{direction} — {m['name']}({m['ticker']})",
                "level":  "📌 觀察",
                "detail": f"成交量 {m['vol_ratio']:.1f}x 均量，漲跌 {m['ret_1d']:+.1f}%",
                "action": "爆量但價格未大動，可能是籌碼易手，追蹤後續走勢",
            })

    # 52 週新高突破
    for m in metrics:
        if m["pct_from_high"] >= -2.0 and m["ret_1d"] > 0:
            alerts.append({
                "type":   f"逼近 52 週新高 — {m['name']}({m['ticker']})",
                "level":  "✅ 正向",
                "detail": f"距高點 {m['pct_from_high']:.1f}%，現價 ${m['price']}，52W高 ${m['high_52w']}",
                "action": "突破前高為強勢訊號，確認量能配合度",
            })

    # 強弱排序：相對 QQQ 1M 最強 / 最弱各 3 檔
    rel_sorted = sorted([m for m in metrics if m["rel_qqq_1m"] is not None],
                        key=lambda x: -x["rel_qqq_1m"])
    if len(rel_sorted) >= 3:
        leaders = "、".join([f"{m['name']}({m['ticker']}) {m['rel_qqq_1m']:+.1f}%" for m in rel_sorted[:3]])
        laggards = "、".join([f"{m['name']}({m['ticker']}) {m['rel_qqq_1m']:+.1f}%" for m in rel_sorted[-3:]])
        alerts.append({
            "type":   "本月相對 QQQ 領漲股",
            "level":  "📌 觀察",
            "detail": leaders,
            "action": "領漲股通常反映資金偏好，確認是否為系統性布局",
        })
        alerts.append({
            "type":   "本月相對 QQQ 落後股",
            "level":  "📌 觀察",
            "detail": laggards,
            "action": "落後股確認是個股問題還是板塊輪動壓力",
        })

    return alerts


# ─── 報告生成 ──────────────────────────────────────────────────────────────────
def build_report(metrics: list[dict], alerts: list[dict]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"╔══ 美股核心個股掃描 ══ {now} ══╗",
        f"  監控 {len(metrics)} 檔 | 基準：{BENCHMARK}",
        "",
        f"  {'代號':<6} {'名稱':<8} {'現價':>8} {'1D':>7} {'5D':>7} {'1M':>7} {'3M':>7} {'vsQQQ(1M)':>10}",
        f"  {'─'*65}",
    ]

    sorted_m = sorted(metrics, key=lambda x: -x["ret_1d"])
    for m in sorted_m:
        rel = f"{m['rel_qqq_1m']:+.1f}%" if m["rel_qqq_1m"] is not None else "   —"
        vol = "🔥" if m["vol_spike"] else "  "
        lines.append(
            f"  {vol}{m['ticker']:<5} {m['name']:<8} "
            f"{m['price']:>8.2f} "
            f"{m['ret_1d']:>+6.1f}% "
            f"{m['ret_5d']:>+6.1f}% "
            f"{m['ret_1m']:>+6.1f}% "
            f"{m['ret_3m']:>+6.1f}% "
            f"{rel:>10}"
        )

    lines.append("")
    if alerts:
        lines.append("  ── 訊號 ──────────────────────────────────")
        for a in alerts:
            lines.append(f"  {a['level']} {a['type']}")
            lines.append(f"     {a['detail']}")
            lines.append(f"     → {a['action'][:70]}")
            lines.append("")
    else:
        lines.append("  ✅ 無異常個股訊號")

    lines.append("  （🔥 = 成交量 ≥ 2x 20日均量）")
    lines.append("╚══════════════════════════════════════╝")
    return "\n".join(lines)


# ─── 主函式 ────────────────────────────────────────────────────────────────────
def run() -> dict:
    """執行美股個股掃描"""
    print("[us_watchlist] 下載美股個股資料...")
    data    = fetch_data(list(US_WATCHLIST.keys()))
    metrics = analyze_all(data)
    alerts  = detect_signals(metrics)
    report  = build_report(metrics, alerts)

    print(report)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    with open(f"{OUTPUT_DIR}/us_watchlist_{date_str}.txt", "w", encoding="utf-8") as f:
        f.write(report)

    return {
        "status":  "ok",
        "metrics": metrics,
        "alerts":  alerts,
        "report":  report,
    }


if __name__ == "__main__":
    run()
