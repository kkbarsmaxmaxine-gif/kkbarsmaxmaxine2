"""
collector.py — 市場資料收集器
抓取收盤後市場數據，輸出 data/YYYYMMDD_raw.json
"""

import yfinance as yf
import pandas as pd
import json
import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../automation/.env"))

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

WATCHLIST: dict[str, str] = {
    # 核心半導體
    "NVDA": "輝達",   "AMD": "超微",    "AVGO": "博通",   "MU": "美光",
    "MRVL": "邁威爾", "ASML": "ASML",  "AMAT": "應用材料", "KLAC": "科磊",
    "TSM": "台積電ADR", "SMCI": "超微電腦",
    # 科技龍頭
    "MSFT": "微軟",   "META": "Meta",   "GOOGL": "Alphabet", "AAPL": "蘋果",
    "AMZN": "亞馬遜",
    # 用戶重點追蹤
    "DDOG": "Datadog",     "NET": "Cloudflare",  "FN": "Fabrinet",
    "ETN": "伊頓",          "PLTR": "Palantir",   "CSCO": "Cisco",
    # 光通訊族群
    "AAOI": "Applied Optoelectronics", "LITE": "Lumentum",
    "COHR": "Coherent",                "NOK":  "Nokia",
    "AXTI": "AXT",
    # NAND 控制 IC（記憶體三條線—NAND 線代表）
    "8299.TWO": "群聯",
    # 電力基建
    "PWR": "Quanta",       "STRL": "Sterling",
    # 基準 & 板塊
    "QQQ": "QQQ",  "SPY": "SPY",  "SOXX": "費半ETF",
    "XLK": "科技",  "XLC": "通訊", "XLE": "能源",  "XLF": "金融",
}


def _calc_ema(series: pd.Series, span: int) -> tuple[float, float]:
    """回傳 (今日EMA, 昨日EMA)"""
    ema = series.ewm(span=span, adjust=False).mean()
    return float(ema.iloc[-1]), float(ema.iloc[-2])


def fetch_all() -> dict:
    tickers = list(WATCHLIST.keys())
    end   = datetime.today()
    start = end - timedelta(days=120)

    try:
        raw = yf.download(
            tickers,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        print(f"[collector] yfinance 下載失敗: {e}")
        sys.exit(1)

    results = {}
    for ticker in tickers:
        try:
            df = raw.xs(ticker, axis=1, level=1).dropna(how="all")
            if len(df) < 10:
                continue

            close = df["Close"]
            vol   = df["Volume"] if "Volume" in df.columns else pd.Series(dtype=float)

            price    = float(close.iloc[-1])
            price_1d = float(close.iloc[-2])

            ret_1d = (price / price_1d - 1) * 100
            ret_5d = (price / float(close.iloc[-6])  - 1) * 100 if len(close) >= 6  else 0.0
            ret_1m = (price / float(close.iloc[-22]) - 1) * 100 if len(close) >= 22 else 0.0
            ret_3m = (price / float(close.iloc[-65]) - 1) * 100 if len(close) >= 65 else 0.0

            ema8,  ema8_prev  = _calc_ema(close, 8)
            ema22, ema22_prev = _calc_ema(close, 22)
            ema50, _          = _calc_ema(close, 50)
            ema200, _         = _calc_ema(close, 200)

            # EMA8/22 交叉偵測
            cross_now  = ema8 > ema22
            cross_prev = ema8_prev > ema22_prev
            if cross_now and not cross_prev:
                crossover = "golden_cross"
            elif not cross_now and cross_prev:
                crossover = "death_cross"
            else:
                crossover = "above" if cross_now else "below"

            # RSI(14)
            delta = close.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rsi   = float((100 - 100 / (1 + gain / loss)).iloc[-1])

            # 成交量比率
            vol_ratio = None
            if len(vol) >= 21:
                avg20     = float(vol.iloc[-21:-1].mean())
                today_vol = float(vol.iloc[-1])
                if avg20 > 0:
                    vol_ratio = round(today_vol / avg20, 2)

            high_3m = float(df["High"].iloc[-65:].max()) if len(df) >= 65 else float(df["High"].max())
            low_3m  = float(df["Low"].iloc[-65:].min())  if len(df) >= 65 else float(df["Low"].min())

            results[ticker] = {
                "name":       WATCHLIST[ticker],
                "price":      round(price, 2),
                "ret_1d":     round(ret_1d, 2),
                "ret_5d":     round(ret_5d, 2),
                "ret_1m":     round(ret_1m, 2),
                "ret_3m":     round(ret_3m, 2),
                "ema8":       round(ema8, 2),
                "ema22":      round(ema22, 2),
                "ema50":      round(ema50, 2),
                "ema200":     round(ema200, 2),
                "crossover":  crossover,
                "rsi":        round(rsi, 1),
                "vol_ratio":  vol_ratio,
                "high_3m":    round(high_3m, 2),
                "low_3m":     round(low_3m, 2),
                "pct_from_high_3m": round((price / high_3m - 1) * 100, 2),
            }
        except Exception as e:
            print(f"[collector] {ticker} 略過: {e}")

    return results


def run() -> dict:
    print("[collector] 開始收集市場資料...")
    data     = fetch_all()
    date_str = datetime.now().strftime("%Y%m%d")

    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, f"{date_str}_raw.json")

    output = {
        "date":    datetime.now().strftime("%Y-%m-%d"),
        "tickers": data,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[collector] ✅ {len(data)} 檔資料存入 {out_path}")
    return output


if __name__ == "__main__":
    run()
