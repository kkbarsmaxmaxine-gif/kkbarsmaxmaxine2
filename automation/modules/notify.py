"""
notify.py — Telegram 推播模組
Layer 4 模組：把每日報告推送到 Telegram

推播順序：
  1. 警示摘要（有警示才推）
  2. ETN 每日技術卡片（每日例行）
  3. LITE 事件交易卡片（有效日前每日）
  4. FN 技術監測卡片（EMA8/22 死叉/金叉警示）
  5. NET Workers AI 監測卡片（每日例行）
  6. DDOG AI 消費放大監測卡片（每日例行）
  7. CSCO Splunk 轉型監測卡片（每日例行）
  8. AI 完整報告（每日例行）
"""

import os
import requests
import yfinance as yf
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
TG_API    = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ETN 追蹤閾值（法說會後設定）
ETN_TARGETS = {
    "gross_margin_target": 37.0,
    "ma50_support":        381.80,
    "ma200_support":       361.25,
    "ma20_resistance":     410.59,
    "high_52w":            431.82,
}

# FN 技術監測參數
FN_LEVELS = {
    "ema50_support":   614.87,   # EMA50 關鍵支撐
    "ema_resistance":  651.91,   # EMA8/22 匯集壓力
    "target_barclays": 702.00,   # Barclays 目標價
    "entry_ideal":     500.00,   # 基本面理想進場區上緣
    "entry_aggressive":625.00,   # EMA50 止穩積極進場區上緣
}

# NET Workers AI 監控參數
NET_MONITOR = {
    "support_key":           180.00,  # 前突破關鍵支撐
    "support_ema50":         175.00,  # EMA50 參考支撐（動態，僅作初始值）
    "resistance_key":        210.00,  # 短期壓力
    "target_base":           220.00,  # 基礎設施倍數目標（無 AI 重新定價）
    "target_ai":             280.00,  # Workers AI 重新定價目標
    # Workers AI 收入閾值（佔總收入比例）
    "workers_ai_bull_pct":    10.0,   # >10% 且 YoY +200% → 牛市觸發
    "workers_ai_bear_pct":     5.0,   # <5% → 基礎設施倍數壓力
    # DBNR 監控
    "dbnr_warning":          115.0,   # 跌破 → 擴展動能惡化警示
    "dbnr_recovery":         120.0,   # 回升 → 正向訊號
    # 季度收入成長指引
    "revenue_growth_guide":   30.0,   # FY2026 指引成長率 ~30%
}

# CSCO Splunk 轉型監控參數
CSCO_MONITOR = {
    # 更新：2026-05-15 Q3 FY26 財報後（+13.4%，3x 爆量，現價 $115）
    # 本季主角是 AI 訂單（$1.9B，3x YoY），Splunk/安全轉型尚未驗證
    "support_key":           100.00, # 財報後 EMA8 回歸支撐
    "support_pre_earnings":   82.00, # 財報前均線區（跌回 = 財報效果消化完）
    "resistance_key":         120.00, # 近期壓力（52W 高點）
    "target_hardware":         94.00, # 純 AI 硬體情境（22x P/E，無 Splunk 確立）
    "target_mid":             117.00, # 目前定價情境（AI + 轉型初步）
    "target_transform":       140.00, # Splunk 全面確立目標（28x P/E）
    "dividend_annual":          1.68, # 年配息 $0.42 × 4（Q3 已確認）
    # ── KPI 1：ARR 成長率（目前 +2%，極低）──────────────────────
    "arr_stabilize":            5.0,  # 先追蹤是否止穩 >5%（前提）
    "arr_growth_bull":         15.0,  # >15% → 軟體轉型確立（長期目標）
    # ── KPI 2：Splunk 新客戶（管理層 FY26 目標：1,000 個新客戶）──
    "splunk_new_logo_target": 1000,   # FY26 全年目標（每季追蹤進度）
    "splunk_xsell_bull":       30.0,  # >30% Cisco 客戶採用 Splunk → 平台確立
    # ── KPI 3：安全部門收入成長（目前持平）──────────────────────
    "security_growth_first":    5.0,  # 先看能否轉正 >5%（最低門檻）
    "security_growth_bull":    20.0,  # >20% → 倍數重新定價
    # ── KPI 4：非 GAAP 毛利率（Q3 66%，YoY -260bps）────────────
    "gross_margin_floor":      64.5,  # 跌破 → AI 硬體低毛利持續侵蝕 FCF 警示
    "gross_margin_positive":   66.5,  # 回升至此 → 產品組合改善正向訊號
}

# DDOG AI 消費放大監控參數
DDOG_MONITOR = {
    "support_key":         180.00,   # 前突破關鍵支撐
    "resistance_key":      215.00,   # 短期壓力
    "target_base":         240.00,   # 基礎估值目標（25x P/S，成長 25%）
    "target_ai":           300.00,   # AI 消費放大重新定價目標（30x P/S）
    # AI 原生客戶 ARR 占比閾值
    "ai_arr_bull":          15.0,    # >15% → 消費放大論文確立
    "ai_arr_stagnant":      10.0,    # 停滯 <10% → 論文動搖
    # DBNR 監控
    "dbnr_warning":        112.0,    # 跌破 → 擴展動能惡化警示
    "dbnr_recovery":       120.0,    # 回升 → 正向訊號
    # 營收成長率
    "revenue_rerating":     30.0,    # 重新加速至此 → 倍數重新定價
    "revenue_warning":      20.0,    # 降速至此 → 成長溢價壓縮
    # 毛利率警戒線
    "gross_margin_floor":   75.0,    # 跌破 → 平台擴張侵蝕獲利警示
}

# LITE 事件交易參數
LITE_TRADE = {
    "stop_loss":      945.0,
    "target":        1040.0,    # +3~5% 獲利目標
    "exit_date":     "2026-05-14",   # 有效日前 2 天強制出場
    "effective_date":"2026-05-18",   # NDX 有效日
    "position_pct":  2.0,            # 倉位 %
}


# ─── LITE 事件交易卡片 ────────────────────────────────────────────────────────
def format_lite_card() -> str:
    """格式化 LITE NDX 納入事件交易每日卡片"""
    today    = datetime.now().date()
    date_str = datetime.now().strftime("%Y-%m-%d")
    from datetime import date
    exit_d    = date(2026, 5, 14)
    eff_d     = date(2026, 5, 18)
    days_exit = (exit_d - today).days
    days_eff  = (eff_d  - today).days

    # 抓即時價格
    try:
        df    = yf.download("LITE", period="5d", auto_adjust=True, progress=False)
        close = df["Close"].squeeze()
        vol   = df["Volume"].squeeze()
        price = float(close.iloc[-1])
        prev  = float(close.iloc[-2])
        ret_1d = (price / prev - 1) * 100
        vol20  = float(vol.rolling(5).mean().iloc[-1])
        vol_r  = float(vol.iloc[-1]) / vol20 if vol20 > 0 else 1.0

        # 用 1 個月數據算 RSI
        df1m  = yf.download("LITE", period="1mo", auto_adjust=True, progress=False)
        c1m   = df1m["Close"].squeeze()
        delta = c1m.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi   = float((100 - 100 / (1 + gain / loss)).iloc[-1])
    except Exception as e:
        return f"📊 *LITE 事件交易* {date_str}\n\n⚠️ 資料抓取失敗: {e}"

    stop   = LITE_TRADE["stop_loss"]
    target = LITE_TRADE["target"]
    pos    = LITE_TRADE["position_pct"]

    stop_dist   = (price / stop   - 1) * 100
    target_dist = (target / price - 1) * 100
    stop_loss_pct = pos * abs(price - stop) / price   # 對總資金的實際虧損%

    # 狀態判斷
    if price <= stop:
        status = "🔴 *停損已觸發* — 執行出場"
    elif days_exit <= 0:
        status = "⏰ *出場日到期* — 今日收盤前出場"
    elif price >= target:
        status = "🎯 *獲利目標到達* — 考慮出場"
    elif stop_dist < 2.0:
        status = f"⚠️ 接近停損（距 {stop_dist:.1f}%）— 注意"
    else:
        status = "✅ 持倉中，事件仍在窗口期"

    # 事件倒數進度條
    total_days = (eff_d - date(2026, 5, 11)).days   # 宣告後總天數 = 7
    elapsed    = total_days - days_eff
    bar_filled = min(elapsed, total_days)
    bar = "█" * bar_filled + "░" * (total_days - bar_filled)

    lines = [
        f"🎯 *LITE Lumentum — 事件交易* {date_str}",
        "",
        f"{status}",
        "",
        f"💰 現價 `${price:.2f}`   今日 `{ret_1d:+.1f}%`",
        f"成交量  `{vol_r:.1f}x` 均量{'  🔥' if vol_r > 1.5 else ''}",
        f"RSI(14) `{rsi:.1f}`{'  ⚠️ 超買' if rsi > 70 else ''}",
        "",
        "*事件進度*",
        f"`[{bar}]`",
        f"宣告日 05/11 → 出場日 05/14 → 有效日 05/18",
        f"距建議出場：`{days_exit}` 天  |  距有效日：`{days_eff}` 天",
        "",
        "*持倉參數*",
        f"停損  `${stop:.0f}`   距離 `{stop_dist:+.1f}%`   {'🔴' if stop_dist < 2 else '🟢'}",
        f"目標  `${target:.0f}`  距離 `{target_dist:+.1f}%`",
        f"倉位  `{pos:.0f}%`   最大虧損 `{stop_loss_pct:.2f}%` 總資金",
        "",
        "*出場規則（擇一先到先執行）*",
        f"① 價格觸 `${target:.0f}` → 獲利出場",
        f"② `05/14` 收盤前 → 時間停損出場",
        f"③ 價格跌破 `${stop:.0f}` → 停損出場",
    ]
    return "\n".join(lines)


def send_lite_card() -> bool:
    """推播 LITE 事件交易卡片（有效日前每日）"""
    from datetime import date
    today = datetime.now().date()
    eff_d = date(2026, 5, 18)
    if today > eff_d:
        print("[notify] LITE 事件已結束，跳過卡片")
        return True
    msg = format_lite_card()
    ok  = send_message(msg)
    if ok:
        print("[notify] ✅ LITE 卡片推播成功")
    return ok


# ─── ETN 技術卡片 ─────────────────────────────────────────────────────────────
def fetch_etn_technicals() -> Optional[dict]:
    """即時抓取 ETN 技術指標"""
    try:
        df = yf.download("ETN", period="1y", auto_adjust=True, progress=False)
        if len(df) < 30:
            return None

        close = df["Close"].squeeze()
        vol   = df["Volume"].squeeze()

        price  = float(close.iloc[-1])
        price0 = float(close.iloc[-2])
        ret_1d = (price / price0 - 1) * 100
        ret_1m = (price / float(close.iloc[-22]) - 1) * 100 if len(close) >= 22 else 0
        ret_3m = (price / float(close.iloc[-66]) - 1) * 100 if len(close) >= 66 else 0
        ret_1y = (price / float(close.iloc[0])   - 1) * 100

        ma20  = float(close.rolling(20).mean().iloc[-1])
        ma50  = float(close.rolling(50).mean().iloc[-1])
        ma200 = float(close.rolling(200).mean().iloc[-1])

        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi   = float(100 - (100 / (1 + gain / loss)).iloc[-1])

        ema12  = close.ewm(span=12).mean()
        ema26  = close.ewm(span=26).mean()
        macd   = float((ema12 - ema26).iloc[-1])
        signal = float((ema12 - ema26).ewm(span=9).mean().iloc[-1])
        hist   = macd - signal

        vol20    = float(vol.rolling(20).mean().iloc[-1])
        vol_r    = float(vol.iloc[-1]) / vol20 if vol20 > 0 else 1.0
        w52h     = float(close.max())
        pct_high = (price / w52h - 1) * 100

        return {
            "price":    price,
            "ret_1d":   ret_1d,
            "ret_1m":   ret_1m,
            "ret_3m":   ret_3m,
            "ret_1y":   ret_1y,
            "ma20":     ma20,
            "ma50":     ma50,
            "ma200":    ma200,
            "rsi":      rsi,
            "macd":     macd,
            "signal":   signal,
            "hist":     hist,
            "vol_r":    vol_r,
            "w52h":     w52h,
            "pct_high": pct_high,
        }
    except Exception as e:
        print(f"[notify] ETN 技術資料抓取失敗: {e}")
        return None


def format_etn_card(scan_results: dict) -> str:
    """格式化 ETN 每日技術卡片"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    t = fetch_etn_technicals()

    if t is None:
        return f"📡 *ETN 伊頓 — 每日監控* {date_str}\n\n⚠️ 技術資料暫時無法取得"

    p     = t["price"]
    ma20  = t["ma20"]
    ma50  = t["ma50"]
    ma200 = t["ma200"]
    rsi   = t["rsi"]
    macd  = t["macd"]
    sig   = t["signal"]
    hist  = t["hist"]

    # 均線位置標籤
    def ma_tag(price: float, ma: float) -> str:
        pct = (price / ma - 1) * 100
        arrow = "↑" if price > ma else "↓"
        return f"{arrow} {pct:+.1f}%"

    # RSI 標籤
    rsi_tag = "🔴 超買" if rsi > 70 else ("🟢 超賣" if rsi < 30 else "⚪ 中性")

    # MACD 標籤
    macd_tag = "金叉↑" if macd > sig else "死叉↓"
    hist_dir = "擴大" if abs(hist) > abs(t["hist"]) else "收斂"

    # 趨勢判斷
    if p > ma20 > ma50 > ma200:
        trend = "📈 多頭排列"
    elif p < ma20 < ma50 < ma200:
        trend = "📉 空頭排列"
    elif p > ma50 and p > ma200:
        trend = "📊 整理（站穩中長線）"
    else:
        trend = "📊 均線交叉整理"

    # MA50 守住提示
    ma50_gap = (p / ma50 - 1) * 100
    if ma50_gap < 3:
        support_alert = f"\n⚠️ 距 MA50 支撐僅 {ma50_gap:.1f}%，注意守穩"
    else:
        support_alert = ""

    # 從 us_watchlist 抓 ETN 的當日警示
    etn_alerts = []
    for m in scan_results.get("us_watchlist", {}).get("alerts", []):
        if "ETN" in m.get("type", "") or "伊頓" in m.get("type", ""):
            etn_alerts.append(f"• {m['level']} {m['type']}")

    alert_block = ""
    if etn_alerts:
        alert_block = "\n\n🚨 *今日訊號*\n" + "\n".join(etn_alerts)

    lines = [
        f"📡 *ETN 伊頓 — 每日監控* {date_str}",
        "",
        f"💰 現價 `${p:.2f}`   今日 `{t['ret_1d']:+.1f}%`",
        f"📅 1M `{t['ret_1m']:+.1f}%`  3M `{t['ret_3m']:+.1f}%`  1Y `{t['ret_1y']:+.1f}%`",
        f"趨勢：{trend}",
        "",
        "*均線結構*",
        f"MA20   `${ma20:.2f}`  {ma_tag(p, ma20)}  {'〔短線壓力〕' if p < ma20 else '〔短線支撐〕'}",
        f"MA50   `${ma50:.2f}`  {ma_tag(p, ma50)}  〔中線{'支撐✅' if p > ma50 else '壓力⚠️'}〕",
        f"MA200  `${ma200:.2f}`  {ma_tag(p, ma200)}  〔長線{'支撐✅' if p > ma200 else '壓力⚠️'}〕",
        "",
        "*動能指標*",
        f"RSI(14)  `{rsi:.1f}`  {rsi_tag}",
        f"MACD     `{macd:.2f}` vs Signal `{sig:.2f}`  {macd_tag}  柱狀 `{hist:+.2f}`",
        f"成交量   `{t['vol_r']:.1f}x` 均量{'  🔥' if t['vol_r'] > 1.5 else ''}",
        "",
        "*關鍵價位*",
        f"🔴 壓力  `${t['w52h']:.2f}` 52W高",
        f"🔴 壓力  `${ma20:.2f}` MA20",
        f"⭐ 現價  `${p:.2f}`",
        f"🟢 支撐  `${ma50:.2f}` MA50 ← 守住看多",
        f"🟢 支撐  `${ma200:.2f}` MA200",
        f"{support_alert}",
        "",
        "*法說會追蹤指標*",
        f"• Q2 毛利率目標 ≥37%（Q1實際 35.6%）",
        f"• 228GW backlog 轉換速度",
        f"• GRID ETF 資金流入持續性",
        f"{alert_block}",
    ]

    return "\n".join(l for l in lines if l != "None")


# ─── FN 技術監測卡片 ──────────────────────────────────────────────────────────
def fetch_fn_technicals() -> Optional[dict]:
    """抓取 FN EMA8/22/50/200、RSI、成交量"""
    try:
        df = yf.download("FN", period="6mo", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        if len(df) < 30:
            return None

        close = df["Close"]
        vol   = df["Volume"]

        price  = float(close.iloc[-1])
        prev   = float(close.iloc[-2])
        ret_1d = (price / prev - 1) * 100
        ret_1m = (price / float(close.iloc[-22]) - 1) * 100 if len(close) >= 22 else 0.0
        ret_3m = (price / float(close.iloc[-65]) - 1) * 100 if len(close) >= 65 else 0.0

        ema8   = float(close.ewm(span=8,   adjust=False).mean().iloc[-1])
        ema22  = float(close.ewm(span=22,  adjust=False).mean().iloc[-1])
        ema50  = float(close.ewm(span=50,  adjust=False).mean().iloc[-1])
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])

        ema8_prev  = float(close.ewm(span=8,  adjust=False).mean().iloc[-2])
        ema22_prev = float(close.ewm(span=22, adjust=False).mean().iloc[-2])

        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi   = float((100 - 100 / (1 + gain / loss)).iloc[-1])

        vol20  = float(vol.rolling(20).mean().iloc[-1])
        vol_r  = float(vol.iloc[-1]) / vol20 if vol20 > 0 else 1.0

        # 交叉偵測
        cross_now  = ema8 > ema22
        cross_prev = ema8_prev > ema22_prev
        if cross_now and not cross_prev:
            cross_signal = "🟢 金叉！EMA8 剛穿越 EMA22 之上"
        elif not cross_now and cross_prev:
            cross_signal = "🔴 死叉！EMA8 剛跌破 EMA22 之下"
        elif cross_now:
            cross_signal = "✅ EMA8 持續在 EMA22 之上"
        else:
            cross_signal = "⚠️ EMA8 持續在 EMA22 之下"

        high_3m = float(df["High"].iloc[-65:].max())

        return {
            "price": price, "ret_1d": ret_1d, "ret_1m": ret_1m, "ret_3m": ret_3m,
            "ema8": ema8, "ema22": ema22, "ema50": ema50, "ema200": ema200,
            "rsi": rsi, "vol_r": vol_r,
            "cross_now": cross_now, "cross_prev": cross_prev,
            "cross_signal": cross_signal, "high_3m": high_3m,
        }
    except Exception as e:
        print(f"[notify] FN 技術資料抓取失敗: {e}")
        return None


def format_fn_card() -> str:
    """格式化 FN 每日技術監測卡片"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    t = fetch_fn_technicals()

    if t is None:
        return f"📡 *FN Fabrinet — 技術監測* {date_str}\n\n⚠️ 資料暫時無法取得"

    p      = t["price"]
    ema8   = t["ema8"]
    ema22  = t["ema22"]
    ema50  = t["ema50"]
    ema200 = t["ema200"]
    rsi    = t["rsi"]

    # 趨勢
    if p > ema8 > ema22 > ema50:
        trend = "📈 短線多頭排列"
    elif p < ema8 < ema22:
        trend = "📉 短線空頭"
    elif ema8 > ema22 and p < ema8:
        trend = "📊 多頭但價格回測均線"
    else:
        trend = "📊 整理中"

    rsi_tag = "🔴 超買" if rsi > 70 else ("🟢 超賣機會" if rsi < 35 else "⚪ 中性")

    # EMA50 支撐距離
    ema50_dist = (p / ema50 - 1) * 100
    ema50_alert = f"\n⚡ 距 EMA50 支撐 {ema50_dist:+.1f}%  {'← 已近支撐，注意止穩' if ema50_dist < 3 else ''}"

    # 進場狀態判斷
    if p <= FN_LEVELS["entry_ideal"]:
        entry_status = "🎯 已達理想進場區（基本面合理價）"
    elif p <= FN_LEVELS["entry_aggressive"]:
        entry_status = "📌 積極進場區（EMA50 止穩確認中）"
    elif not t["cross_now"]:
        entry_status = "⏳ 等待：EMA8 需重新站上 EMA22"
    else:
        entry_status = "🔒 均線多頭，持倉觀察"

    lines = [
        f"📡 *FN Fabrinet — 技術監測* {date_str}",
        "",
        f"💰 現價 `${p:.2f}`   今日 `{t['ret_1d']:+.1f}%`",
        f"📅 1M `{t['ret_1m']:+.1f}%`  3M `{t['ret_3m']:+.1f}%`  3M高 `${t['high_3m']:.0f}`",
        f"趨勢：{trend}",
        "",
        f"*EMA 交叉訊號*",
        f"{t['cross_signal']}",
        f"`EMA8  ${ema8:.2f}`  `EMA22 ${ema22:.2f}`",
        f"差距：`{(ema8/ema22-1)*100:+.2f}%`",
        "",
        "*均線結構*",
        f"EMA8   `${ema8:.2f}`   現價 `{(p/ema8-1)*100:+.1f}%`",
        f"EMA22  `${ema22:.2f}`   {'🔴 壓力' if p < ema22 else '✅ 支撐'}",
        f"EMA50  `${ema50:.2f}`   {'🔴 壓力' if p < ema50 else '✅ 支撐'}{ema50_alert}",
        f"EMA200 `${ema200:.2f}`  {'✅ 長線支撐' if p > ema200 else '⚠️ 跌破長線'}",
        "",
        "*動能*",
        f"RSI(14) `{rsi:.1f}`  {rsi_tag}",
        f"成交量  `{t['vol_r']:.1f}x` 均量{'  🔥' if t['vol_r'] > 1.5 else ''}",
        "",
        "*關鍵價位*",
        f"🔴 壓力  `${FN_LEVELS['ema_resistance']:.0f}` EMA8/22 匯集",
        f"🔴 目標  `${FN_LEVELS['target_barclays']:.0f}` Barclays 目標價",
        f"⭐ 現價  `${p:.2f}`",
        f"🟢 支撐  `${FN_LEVELS['entry_aggressive']:.0f}` EMA50 積極進場區",
        f"🟢 支撐  `${FN_LEVELS['entry_ideal']:.0f}` 基本面理想買入區",
        "",
        f"*進場判斷*",
        f"{entry_status}",
        "",
        "*成長故事追蹤*",
        f"• CPO 客戶數（目前 3 家 → 等待增加）",
        f"• NVIDIA 佔收入比（目前 27.6%，過高是風險）",
        f"• Raytec 晶圓封裝首批認證公告",
    ]
    return "\n".join(lines)


def send_fn_card() -> bool:
    """推播 FN 每日技術監測卡片"""
    msg = format_fn_card()
    ok  = send_message(msg)
    if ok:
        print("[notify] ✅ FN 卡片推播成功")
    return ok


# ─── NET Workers AI 監測卡片 ──────────────────────────────────────────────────
def fetch_net_technicals() -> Optional[dict]:
    """抓取 NET EMA8/22/50/200、RSI、成交量"""
    try:
        df = yf.download("NET", period="6mo", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        if len(df) < 30:
            return None

        close = df["Close"]
        vol   = df["Volume"]

        price  = float(close.iloc[-1])
        prev   = float(close.iloc[-2])
        ret_1d = (price / prev - 1) * 100
        ret_1m = (price / float(close.iloc[-22]) - 1) * 100 if len(close) >= 22 else 0.0
        ret_3m = (price / float(close.iloc[-65]) - 1) * 100 if len(close) >= 65 else 0.0

        ema8   = float(close.ewm(span=8,   adjust=False).mean().iloc[-1])
        ema22  = float(close.ewm(span=22,  adjust=False).mean().iloc[-1])
        ema50  = float(close.ewm(span=50,  adjust=False).mean().iloc[-1])
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])

        ema8_prev  = float(close.ewm(span=8,  adjust=False).mean().iloc[-2])
        ema22_prev = float(close.ewm(span=22, adjust=False).mean().iloc[-2])

        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi   = float((100 - 100 / (1 + gain / loss)).iloc[-1])

        vol20 = float(vol.rolling(20).mean().iloc[-1])
        vol_r = float(vol.iloc[-1]) / vol20 if vol20 > 0 else 1.0

        cross_now  = ema8 > ema22
        cross_prev = ema8_prev > ema22_prev
        if cross_now and not cross_prev:
            cross_signal = "🟢 金叉！EMA8 剛穿越 EMA22 之上"
        elif not cross_now and cross_prev:
            cross_signal = "🔴 死叉！EMA8 剛跌破 EMA22 之下"
        elif cross_now:
            cross_signal = "✅ EMA8 持續在 EMA22 之上"
        else:
            cross_signal = "⚠️ EMA8 持續在 EMA22 之下"

        w52h     = float(close.max())
        pct_high = (price / w52h - 1) * 100

        return {
            "price": price, "ret_1d": ret_1d, "ret_1m": ret_1m, "ret_3m": ret_3m,
            "ema8": ema8, "ema22": ema22, "ema50": ema50, "ema200": ema200,
            "rsi": rsi, "vol_r": vol_r,
            "cross_now": cross_now, "cross_signal": cross_signal,
            "w52h": w52h, "pct_high": pct_high,
        }
    except Exception as e:
        print(f"[notify] NET 技術資料抓取失敗: {e}")
        return None


def format_net_card() -> str:
    """格式化 NET 每日 Workers AI 監測卡片"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    t = fetch_net_technicals()

    if t is None:
        return f"☁️ *NET Cloudflare — Workers AI 監測* {date_str}\n\n⚠️ 資料暫時無法取得"

    p      = t["price"]
    ema8   = t["ema8"]
    ema22  = t["ema22"]
    ema50  = t["ema50"]
    ema200 = t["ema200"]
    rsi    = t["rsi"]

    # 趨勢判斷
    if p > ema8 > ema22 > ema50:
        trend = "📈 短線多頭排列"
    elif p < ema8 < ema22:
        trend = "📉 短線空頭"
    elif ema8 > ema22 and p < ema8:
        trend = "📊 多頭但價格回測均線"
    else:
        trend = "📊 整理中"

    rsi_tag = "🔴 超買" if rsi > 70 else ("🟢 超賣機會" if rsi < 35 else "⚪ 中性")

    # 距關鍵支撐
    support  = NET_MONITOR["support_key"]
    supp_dist = (p / support - 1) * 100
    supp_alert = "  ⚠️ 接近關鍵支撐！" if supp_dist < 5.0 else ""

    # 目標距離
    dist_base = (NET_MONITOR["target_base"] / p - 1) * 100
    dist_ai   = (NET_MONITOR["target_ai"]   / p - 1) * 100

    # Workers AI 觸發狀態說明
    bull_pct = NET_MONITOR["workers_ai_bull_pct"]
    bear_pct = NET_MONITOR["workers_ai_bear_pct"]

    lines = [
        f"☁️ *NET Cloudflare — Workers AI 監測* {date_str}",
        "",
        f"💰 現價 `${p:.2f}`   今日 `{t['ret_1d']:+.1f}%`",
        f"📅 1M `{t['ret_1m']:+.1f}%`  3M `{t['ret_3m']:+.1f}%`  距52W高 `{t['pct_high']:.1f}%`",
        f"趨勢：{trend}",
        "",
        "*EMA 交叉訊號*",
        f"{t['cross_signal']}",
        f"`EMA8  ${ema8:.2f}`  `EMA22 ${ema22:.2f}`",
        f"差距：`{(ema8/ema22-1)*100:+.2f}%`",
        "",
        "*均線結構*",
        f"EMA8   `${ema8:.2f}`   現價 `{(p/ema8-1)*100:+.1f}%`",
        f"EMA22  `${ema22:.2f}`   {'🔴 壓力' if p < ema22 else '✅ 支撐'}",
        f"EMA50  `${ema50:.2f}`   {'🔴 壓力' if p < ema50 else '✅ 支撐'}",
        f"EMA200 `${ema200:.2f}`  {'✅ 長線支撐' if p > ema200 else '⚠️ 跌破長線'}",
        "",
        "*動能*",
        f"RSI(14) `{rsi:.1f}`  {rsi_tag}",
        f"成交量  `{t['vol_r']:.1f}x` 均量{'  🔥' if t['vol_r'] > 1.5 else ''}",
        "",
        "*關鍵價位*",
        f"🎯 AI 重定價目標  `${NET_MONITOR['target_ai']:.0f}`  ({dist_ai:+.0f}%)",
        f"🔴 短期壓力       `${NET_MONITOR['resistance_key']:.0f}`",
        f"⭐ 現價           `${p:.2f}`",
        f"🟢 關鍵支撐       `${support:.0f}`  (距 {supp_dist:+.1f}%){supp_alert}",
        f"📊 基礎設施目標   `${NET_MONITOR['target_base']:.0f}`  ({dist_base:+.0f}%)",
        "",
        "*Workers AI 重定價條件（財報季追蹤）*",
        f"🚀 牛市觸發：AI 收入 >{bull_pct:.0f}% 總收入 且 YoY >200%",
        f"   → 成立 → 目標 `${NET_MONITOR['target_ai']:.0f}`",
        f"⚠️ 熊市壓力：AI 收入 <{bear_pct:.0f}% 總收入",
        f"   → 基礎設施倍數 → 目標 `${NET_MONITOR['target_base']:.0f}`",
        "",
        "*未來四季五大驗證點*",
        f"① Workers AI 量化",
        f"   法說是否出現具體收入數字（非只發布新功能）",
        f"   觸發：AI 收入 >{bull_pct:.0f}% → $280  |  <{bear_pct:.0f}% → $220 壓力",
        f"② Mesh enterprise 採用",
        f"   解決 agents 存取私有 API/DB/內網安全問題",
        f"   驗證：大客戶案例公告 / enterprise 合約成長",
        f"③ 大單動能",
        f"   Q1 >$1M deal YoY +73%，是否延續",
        f"   驗證：每季 >$1M deal 成長率 vs +73% 基期",
        f"④ 裁員後執行力",
        f"   AI-first 重組是否衝擊 go-to-market",
        f"   驗證：新客戶成長率 / sales cycle 長度變化",
        f"⑤ 毛利 & FCF 健康度",
        f"   平台擴張下毛利率是否守住 / FCF margin 趨勢",
        f"   警戒：毛利率 <75% 或 FCF margin 轉負",
        f"",
        f"DBNR 警戒：跌破 {NET_MONITOR['dbnr_warning']:.0f}% ⚠️  / 回升 {NET_MONITOR['dbnr_recovery']:.0f}% ✅",
    ]
    return "\n".join(lines)


def send_net_card() -> bool:
    """推播 NET Workers AI 監測卡片"""
    msg = format_net_card()
    ok  = send_message(msg)
    if ok:
        print("[notify] ✅ NET 卡片推播成功")
    return ok


# ─── DDOG AI 消費放大監測卡片 ─────────────────────────────────────────────────
def fetch_ddog_technicals() -> Optional[dict]:
    """抓取 DDOG EMA8/22/50/200、RSI、成交量"""
    try:
        df = yf.download("DDOG", period="6mo", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        if len(df) < 30:
            return None

        close = df["Close"]
        vol   = df["Volume"]

        price  = float(close.iloc[-1])
        prev   = float(close.iloc[-2])
        ret_1d = (price / prev - 1) * 100
        ret_1m = (price / float(close.iloc[-22]) - 1) * 100 if len(close) >= 22 else 0.0
        ret_3m = (price / float(close.iloc[-65]) - 1) * 100 if len(close) >= 65 else 0.0

        ema8   = float(close.ewm(span=8,   adjust=False).mean().iloc[-1])
        ema22  = float(close.ewm(span=22,  adjust=False).mean().iloc[-1])
        ema50  = float(close.ewm(span=50,  adjust=False).mean().iloc[-1])
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])

        ema8_prev  = float(close.ewm(span=8,  adjust=False).mean().iloc[-2])
        ema22_prev = float(close.ewm(span=22, adjust=False).mean().iloc[-2])

        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi   = float((100 - 100 / (1 + gain / loss)).iloc[-1])

        vol20 = float(vol.rolling(20).mean().iloc[-1])
        vol_r = float(vol.iloc[-1]) / vol20 if vol20 > 0 else 1.0

        cross_now  = ema8 > ema22
        cross_prev = ema8_prev > ema22_prev
        if cross_now and not cross_prev:
            cross_signal = "🟢 金叉！EMA8 剛穿越 EMA22 之上"
        elif not cross_now and cross_prev:
            cross_signal = "🔴 死叉！EMA8 剛跌破 EMA22 之下"
        elif cross_now:
            cross_signal = "✅ EMA8 持續在 EMA22 之上"
        else:
            cross_signal = "⚠️ EMA8 持續在 EMA22 之下"

        w52h     = float(close.max())
        pct_high = (price / w52h - 1) * 100

        return {
            "price": price, "ret_1d": ret_1d, "ret_1m": ret_1m, "ret_3m": ret_3m,
            "ema8": ema8, "ema22": ema22, "ema50": ema50, "ema200": ema200,
            "rsi": rsi, "vol_r": vol_r,
            "cross_now": cross_now, "cross_signal": cross_signal,
            "w52h": w52h, "pct_high": pct_high,
        }
    except Exception as e:
        print(f"[notify] DDOG 技術資料抓取失敗: {e}")
        return None


def format_ddog_card() -> str:
    """格式化 DDOG 每日 AI 消費放大監測卡片"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    t = fetch_ddog_technicals()

    if t is None:
        return f"🐕 *DDOG Datadog — AI 消費放大監測* {date_str}\n\n⚠️ 資料暫時無法取得"

    p      = t["price"]
    ema8   = t["ema8"]
    ema22  = t["ema22"]
    ema50  = t["ema50"]
    ema200 = t["ema200"]
    rsi    = t["rsi"]

    # 趨勢判斷
    if p > ema8 > ema22 > ema50:
        trend = "📈 短線多頭排列"
    elif p < ema8 < ema22:
        trend = "📉 短線空頭"
    elif ema8 > ema22 and p < ema8:
        trend = "📊 多頭但價格回測均線"
    else:
        trend = "📊 整理中"

    # RSI 標籤（DDOG 常見超買，加強警示）
    if rsi >= 80:
        rsi_tag = "🔴 極度超買 — 注意回調風險"
    elif rsi >= 70:
        rsi_tag = "🔴 超買"
    elif rsi <= 35:
        rsi_tag = "🟢 超賣機會"
    else:
        rsi_tag = "⚪ 中性"

    support    = DDOG_MONITOR["support_key"]
    supp_dist  = (p / support - 1) * 100
    supp_alert = "  ⚠️ 接近關鍵支撐！" if supp_dist < 5.0 else ""

    dist_base = (DDOG_MONITOR["target_base"] / p - 1) * 100
    dist_ai   = (DDOG_MONITOR["target_ai"]   / p - 1) * 100

    ai_bull  = DDOG_MONITOR["ai_arr_bull"]
    ai_stag  = DDOG_MONITOR["ai_arr_stagnant"]
    rev_rr   = DDOG_MONITOR["revenue_rerating"]
    rev_warn = DDOG_MONITOR["revenue_warning"]

    lines = [
        f"🐕 *DDOG Datadog — AI 消費放大監測* {date_str}",
        "",
        f"💰 現價 `${p:.2f}`   今日 `{t['ret_1d']:+.1f}%`",
        f"📅 1M `{t['ret_1m']:+.1f}%`  3M `{t['ret_3m']:+.1f}%`  距52W高 `{t['pct_high']:.1f}%`",
        f"趨勢：{trend}",
        "",
        "*EMA 交叉訊號*",
        f"{t['cross_signal']}",
        f"`EMA8  ${ema8:.2f}`  `EMA22 ${ema22:.2f}`",
        f"差距：`{(ema8/ema22-1)*100:+.2f}%`",
        "",
        "*均線結構*",
        f"EMA8   `${ema8:.2f}`   現價 `{(p/ema8-1)*100:+.1f}%`",
        f"EMA22  `${ema22:.2f}`   {'🔴 壓力' if p < ema22 else '✅ 支撐'}",
        f"EMA50  `${ema50:.2f}`   {'🔴 壓力' if p < ema50 else '✅ 支撐'}",
        f"EMA200 `${ema200:.2f}`  {'✅ 長線支撐' if p > ema200 else '⚠️ 跌破長線'}",
        "",
        "*動能*",
        f"RSI(14) `{rsi:.1f}`  {rsi_tag}",
        f"成交量  `{t['vol_r']:.1f}x` 均量{'  🔥' if t['vol_r'] > 1.5 else ''}",
        "",
        "*關鍵價位*",
        f"🎯 AI 重定價目標  `${DDOG_MONITOR['target_ai']:.0f}`  ({dist_ai:+.0f}%)",
        f"🔴 短期壓力       `${DDOG_MONITOR['resistance_key']:.0f}`",
        f"⭐ 現價           `${p:.2f}`",
        f"🟢 關鍵支撐       `${support:.0f}`  (距 {supp_dist:+.1f}%){supp_alert}",
        f"📊 基礎估值目標   `${DDOG_MONITOR['target_base']:.0f}`  ({dist_base:+.0f}%)",
        "",
        "*AI 消費放大論文驗證條件（財報季追蹤）*",
        f"🚀 牛市確立：AI 原生客戶 ARR >{ai_bull:.0f}% + 營收重新加速 >{rev_rr:.0f}%",
        f"   → 成立 → 目標 `${DDOG_MONITOR['target_ai']:.0f}`",
        f"⚠️ 論文動搖：AI 客戶 ARR 停滯 <{ai_stag:.0f}% 或成長降速 <{rev_warn:.0f}%",
        f"   → 成長溢價壓縮 → 目標 `${DDOG_MONITOR['target_base']:.0f}`",
        "",
        "*五大驗證點（每季財報後對照）*",
        f"① AI 原生客戶 ARR 占比",
        f"   目前 ~6-8%｜牛市 >{ai_bull:.0f}%｜停滯 <{ai_stag:.0f}%",
        f"② DBNR 趨勢",
        f"   警戒 <{DDOG_MONITOR['dbnr_warning']:.0f}% ⚠️｜正向 >{DDOG_MONITOR['dbnr_recovery']:.0f}% ✅",
        f"③ 營收成長率",
        f"   重新定價 >{rev_rr:.0f}%｜溢價壓縮 <{rev_warn:.0f}%",
        f"④ AI 產品收入被量化",
        f"   法說出現具體數字（非只發布新功能）→ 論文前進",
        f"⑤ 毛利率 & FCF",
        f"   毛利率跌破 {DDOG_MONITOR['gross_margin_floor']:.0f}% 或 FCF margin 轉負 → 警戒",
    ]
    return "\n".join(lines)


def send_ddog_card() -> bool:
    """推播 DDOG AI 消費放大監測卡片"""
    msg = format_ddog_card()
    ok  = send_message(msg)
    if ok:
        print("[notify] ✅ DDOG 卡片推播成功")
    return ok


# ─── CSCO Splunk 轉型監測卡片 ─────────────────────────────────────────────────
def fetch_csco_technicals() -> Optional[dict]:
    """抓取 CSCO EMA/RSI/成交量"""
    try:
        df = yf.download("CSCO", period="6mo", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        if len(df) < 30:
            return None

        close = df["Close"]
        vol   = df["Volume"]

        price  = float(close.iloc[-1])
        ret_1d = (price / float(close.iloc[-2]) - 1) * 100
        ret_1m = (price / float(close.iloc[-22]) - 1) * 100 if len(close) >= 22 else 0.0
        ret_3m = (price / float(close.iloc[-65]) - 1) * 100 if len(close) >= 65 else 0.0

        ema8   = float(close.ewm(span=8,   adjust=False).mean().iloc[-1])
        ema22  = float(close.ewm(span=22,  adjust=False).mean().iloc[-1])
        ema50  = float(close.ewm(span=50,  adjust=False).mean().iloc[-1])
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])

        ema8_prev  = float(close.ewm(span=8,  adjust=False).mean().iloc[-2])
        ema22_prev = float(close.ewm(span=22, adjust=False).mean().iloc[-2])

        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi   = float((100 - 100 / (1 + gain / loss)).iloc[-1])

        vol20 = float(vol.rolling(20).mean().iloc[-1])
        vol_r = float(vol.iloc[-1]) / vol20 if vol20 > 0 else 1.0

        cross_now  = ema8 > ema22
        cross_prev = ema8_prev > ema22_prev
        if cross_now and not cross_prev:
            cross_signal = "🟢 金叉！EMA8 剛穿越 EMA22 之上"
        elif not cross_now and cross_prev:
            cross_signal = "🔴 死叉！EMA8 剛跌破 EMA22 之下"
        elif cross_now:
            cross_signal = "✅ EMA8 持續在 EMA22 之上"
        else:
            cross_signal = "⚠️ EMA8 持續在 EMA22 之下"

        w52h     = float(close.max())
        w52l     = float(close.min())
        pct_high = (price / w52h - 1) * 100

        # 動態股息殖利率
        div_yield = (CSCO_MONITOR["dividend_annual"] / price) * 100

        return {
            "price": price, "ret_1d": ret_1d, "ret_1m": ret_1m, "ret_3m": ret_3m,
            "ema8": ema8, "ema22": ema22, "ema50": ema50, "ema200": ema200,
            "rsi": rsi, "vol_r": vol_r,
            "cross_now": cross_now, "cross_signal": cross_signal,
            "w52h": w52h, "w52l": w52l, "pct_high": pct_high,
            "div_yield": div_yield,
        }
    except Exception as e:
        print(f"[notify] CSCO 技術資料抓取失敗: {e}")
        return None


def format_csco_card() -> str:
    """格式化 CSCO 每日 Splunk 轉型監測卡片"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    t = fetch_csco_technicals()

    if t is None:
        return f"🌐 *CSCO Cisco — Splunk 轉型監測* {date_str}\n\n⚠️ 資料暫時無法取得"

    p      = t["price"]
    ema8   = t["ema8"]
    ema22  = t["ema22"]
    ema50  = t["ema50"]
    ema200 = t["ema200"]
    rsi    = t["rsi"]

    if p > ema8 > ema22 > ema50:
        trend = "📈 短線多頭排列"
    elif p < ema8 < ema22:
        trend = "📉 短線空頭"
    elif ema8 > ema22 and p < ema8:
        trend = "📊 多頭但價格回測均線"
    else:
        trend = "📊 整理中"

    rsi_tag = "🔴 超買" if rsi > 70 else ("🟢 超賣機會" if rsi < 35 else "⚪ 中性")

    support   = CSCO_MONITOR["support_key"]
    supp_dist = (p / support - 1) * 100
    supp_alert = "  ⚠️ 接近支撐！" if supp_dist < 5.0 else ""

    dist_transform = (CSCO_MONITOR["target_transform"] / p - 1) * 100
    dist_hardware  = (CSCO_MONITOR["target_hardware"]  / p - 1) * 100
    dist_mid       = (CSCO_MONITOR["target_mid"]       / p - 1) * 100

    lines = [
        f"🌐 *CSCO Cisco — AI訂單 & Splunk 轉型監測* {date_str}",
        "",
        f"💰 現價 `${p:.2f}`   今日 `{t['ret_1d']:+.1f}%`",
        f"📅 1M `{t['ret_1m']:+.1f}%`  3M `{t['ret_3m']:+.1f}%`  距52W高 `{t['pct_high']:.1f}%`",
        f"💵 股息殖利率 `{t['div_yield']:.2f}%`  （年配 ${CSCO_MONITOR['dividend_annual']:.2f}）",
        f"趨勢：{trend}",
        "",
        "*EMA 交叉訊號*",
        f"{t['cross_signal']}",
        f"`EMA8  ${ema8:.2f}`  `EMA22 ${ema22:.2f}`",
        f"差距：`{(ema8/ema22-1)*100:+.2f}%`",
        "",
        "*均線結構*",
        f"EMA8   `${ema8:.2f}`   現價 `{(p/ema8-1)*100:+.1f}%`",
        f"EMA22  `${ema22:.2f}`   {'🔴 壓力' if p < ema22 else '✅ 支撐'}",
        f"EMA50  `${ema50:.2f}`   {'🔴 壓力' if p < ema50 else '✅ 支撐'}",
        f"EMA200 `${ema200:.2f}`  {'✅ 長線支撐' if p > ema200 else '⚠️ 跌破長線'}",
        "",
        "*動能*",
        f"RSI(14) `{rsi:.1f}`  {rsi_tag}",
        f"成交量  `{t['vol_r']:.1f}x` 均量{'  🔥' if t['vol_r'] > 1.5 else ''}",
        "",
        "*情境價位（Q3財報後更新）*",
        f"🎯 Splunk 全面確立  `${CSCO_MONITOR['target_transform']:.0f}`  ({dist_transform:+.0f}%)",
        f"📊 目前定價情境    `${CSCO_MONITOR['target_mid']:.0f}`  ({dist_mid:+.0f}%)",
        f"⭐ 現價            `${p:.2f}`",
        f"🟢 財報後支撐      `${support:.0f}`  (距 {supp_dist:+.1f}%){supp_alert}",
        f"📉 純 AI 硬體情境  `${CSCO_MONITOR['target_hardware']:.0f}`  ({dist_hardware:+.0f}%)",
        "",
        "*本季核心矛盾*",
        f"✅ AI 訂單爆發：Q3 $1.9B（YoY 3x），FY26 指引升至 $9B",
        f"⚠️ Splunk/安全未驗證：安全持平，ARR 僅 +2%",
        f"⚠️ 毛利 -260bps：AI 硬體驅動 = 低毛利成長",
        f"→ 市場定價 AI 硬體成功，Splunk 論文尚未計入",
        "",
        "*四大 KPI（每季財報後對照）*",
        f"① ARR 成長率  目前 +2%",
        f"   先止穩 >{CSCO_MONITOR['arr_stabilize']:.0f}%  →  長期確立 >{CSCO_MONITOR['arr_growth_bull']:.0f}%",
        f"② Splunk 新客戶  FY26 目標 {CSCO_MONITOR['splunk_new_logo_target']} 個",
        f"   每季追蹤進度  |  >30% Cisco 客戶採用 → 平台確立",
        f"③ 安全收入 YoY  目前持平",
        f"   先轉正 >{CSCO_MONITOR['security_growth_first']:.0f}%  →  重新定價 >{CSCO_MONITOR['security_growth_bull']:.0f}%",
        f"④ 非 GAAP 毛利率  目前 66%，YoY -260bps",
        f"   警戒 <{CSCO_MONITOR['gross_margin_floor']:.1f}% ⚠️  |  正向 >{CSCO_MONITOR['gross_margin_positive']:.1f}% ✅",
    ]
    return "\n".join(lines)


def send_csco_card() -> bool:
    """推播 CSCO Splunk 轉型監測卡片"""
    msg = format_csco_card()
    ok  = send_message(msg)
    if ok:
        print("[notify] ✅ CSCO 卡片推播成功")
    return ok


# ─── 訊息格式化 ───────────────────────────────────────────────────────────────
def format_alert_message(all_alerts: list[dict], date_str: str) -> str:
    """格式化警示推播訊息（精簡版）"""
    warn  = [a for a in all_alerts if "警示" in a.get("level", "")]
    pos   = [a for a in all_alerts if "正向" in a.get("level", "")]
    watch = [a for a in all_alerts if "觀察" in a.get("level", "")]

    lines = [f"📊 *每日市場掃描* — {date_str}", ""]

    if warn:
        lines.append("⚠️ *警示訊號*")
        for a in warn[:4]:
            lines.append(f"• {a.get('type', '')}")
            lines.append(f"  _{a.get('detail', '')[:60]}_")
        lines.append("")

    if pos:
        lines.append("✅ *正向訊號*")
        for a in pos[:3]:
            lines.append(f"• {a.get('type', '')}")
        lines.append("")

    if watch:
        lines.append(f"📌 觀察中：{len(watch)} 個訊號")
        lines.append("")

    lines.append(f"共 {len(all_alerts)} 個訊號 | ⚠️{len(warn)} ✅{len(pos)} 📌{len(watch)}")
    return "\n".join(lines)


def format_daily_report(report: str, date_str: str) -> str:
    """格式化完整每日報告（分段發送）"""
    header = f"📈 *每日市場簡報* — {date_str}\n\n"
    body = report[:3800] if len(report) > 3800 else report
    return header + f"```\n{body}\n```"


# ─── 推播函式 ─────────────────────────────────────────────────────────────────
def send_message(text: str, parse_mode: str = "Markdown") -> bool:
    """發送 Telegram 訊息"""
    if not BOT_TOKEN or not CHAT_ID:
        print("[notify] 未設定 BOT_TOKEN 或 CHAT_ID，跳過推播")
        return False
    try:
        resp = requests.post(
            f"{TG_API}/sendMessage",
            json={
                "chat_id":    CHAT_ID,
                "text":       text,
                "parse_mode": parse_mode,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[notify] Telegram 推播失敗: {e}")
        return False


def send_alerts(all_alerts: list[dict]) -> bool:
    """推播警示摘要（有警示才推）"""
    warn_count = sum(1 for a in all_alerts if "警示" in a.get("level", ""))
    if warn_count == 0:
        print("[notify] 無警示訊號，跳過推播")
        return True

    date_str = datetime.now().strftime("%Y-%m-%d")
    msg = format_alert_message(all_alerts, date_str)
    ok = send_message(msg)
    if ok:
        print(f"[notify] ✅ 警示推播成功（{warn_count} 個警示）")
    return ok


def send_etn_card(scan_results: dict) -> bool:
    """推播 ETN 每日技術卡片"""
    msg = format_etn_card(scan_results)
    ok = send_message(msg)
    if ok:
        print("[notify] ✅ ETN 卡片推播成功")
    return ok


def send_daily_report(report: str) -> bool:
    """推播完整每日報告"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    msg = format_daily_report(report, date_str)
    ok = send_message(msg)
    if ok:
        print("[notify] ✅ 每日報告推播成功")
    return ok


# ─── 主函式 ────────────────────────────────────────────────────────────────────
def run(scan_results: dict, ai_report: str = "") -> dict:
    """執行推播流程（三則訊息）"""
    # 彙整所有模組的警示
    all_alerts = []
    for key in ["sentiment", "smart_money", "sector", "insider",
                "us_watchlist", "taiwan", "kol"]:
        all_alerts += scan_results.get(key, {}).get("alerts", [])

    results = {}

    # 1. 有警示 → 立即推警示摘要
    results["alert_sent"] = send_alerts(all_alerts)

    # 2. ETN 每日卡片（例行推播）
    results["etn_sent"] = send_etn_card(scan_results)

    # 3. LITE 事件交易卡片（有效日前每日）
    results["lite_sent"] = send_lite_card()

    # 4. FN 技術監測卡片（每日例行）
    results["fn_sent"] = send_fn_card()

    # 5. NET Workers AI 監測卡片（每日例行）
    results["net_sent"] = send_net_card()

    # 6. DDOG AI 消費放大監測卡片（每日例行）
    results["ddog_sent"] = send_ddog_card()

    # 7. CSCO Splunk 轉型監測卡片（每日例行）
    results["csco_sent"] = send_csco_card()

    # 8. 完整 AI 報告（有才推）
    if ai_report:
        results["report_sent"] = send_daily_report(ai_report)

    return {"status": "ok", **results}


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "lite"

    if target == "etn":
        print("[notify] 測試推播 ETN 卡片...")
        card = format_etn_card({})
    elif target == "fn":
        print("[notify] 測試推播 FN 卡片...")
        card = format_fn_card()
    elif target == "net":
        print("[notify] 測試推播 NET 卡片...")
        card = format_net_card()
    elif target == "ddog":
        print("[notify] 測試推播 DDOG 卡片...")
        card = format_ddog_card()
    elif target == "csco":
        print("[notify] 測試推播 CSCO 卡片...")
        card = format_csco_card()
    else:
        print("[notify] 測試推播 LITE 卡片...")
        card = format_lite_card()

    print("\n── 卡片預覽 ──────────────────────────")
    print(card)
    print("────────────────────────────────────\n")
    ok = send_message(card)
    print("推播結果:", "成功" if ok else "失敗")
