"""
earnings_call.py — 法說會深度分析模組
整合 Anthropic financial-services 框架 + CLAUDE.md 黎氏評等 12 項

用法：
    python3 decision_system/earnings_call.py CSCO          # 自動抓今日 packet
    python3 decision_system/earnings_call.py CSCO 20260515 # 指定日期
    python3 decision_system/earnings_call.py CSCO --transcript  # 貼入逐字稿模式
"""

import json
import os
import re
import sys
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../automation/.env"))

ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
ANTHROPIC_API_KEY  = os.getenv("MINIMAX_API_KEY", "")
LLM_MODEL          = os.getenv("LLM_MODEL", "MiniMax-M2.5")

PACKET_DIR  = os.path.join(os.path.dirname(__file__), "packets")
JOURNAL_DIR = os.path.join(os.path.dirname(__file__), "journal")

# ─── System Prompt（整合 Anthropic 框架 + 黎氏評等）─────────────────────────

EARNINGS_SYSTEM_PROMPT = """你是一位資深股票研究員，專長是法說會逐字稿分析與財報解讀。
你的分析框架整合了以下兩個系統：

A) Anthropic 財務服務框架（Beat/Miss 量化分析、指引評估、引用義務）
B) 黎氏評等 12 項（CEO 溝通誠信評量，Benjamin Graham 安全邊際）

─── 分析原則 ───────────────────────────────────────────────────────

1. 只分析新資訊，不重述公司背景或老生常談
2. 每個數字必須量化（具體金額、百分比、與預估的差異）
3. 區分「事實」「推論」「敘事包裝」三種層次
4. 管理層說法永遠需要對照數字驗證
5. 不接受模糊詞：「大幅」「顯著」「強勁」必須換成具體數字

─── 輸出結構（依序輸出，不可省略）────────────────────────────────

## 一、執行摘要（3 句話）
- 這季最重要的一個事實
- 市場預期 vs 實際落差最大的一點
- 一句話定性：多頭論點本季是強化/弱化/不變

## 二、Beat/Miss 量化表

| 指標 | 預估 | 實際 | 差異 | 重要性 |
|------|------|------|------|--------|
| 營收 | | | | ⭐⭐⭐ |
| EPS | | | | ⭐⭐⭐ |
| 毛利率 | | | | ⭐⭐ |
| [關鍵業務指標] | | | | ⭐⭐⭐ |

重要性：⭐⭐⭐ = 定價關鍵 / ⭐⭐ = 重要但非核心 / ⭐ = 參考

## 三、指引分析（最重要區塊）
- 下季指引：[具體數字] vs 街頭預估 [具體數字] → beat/miss X%
- 全年指引：上修/下修/維持，幅度 X%
- 管理層對指引的語氣：保守/中性/樂觀（附原文支撐）

## 四、黎氏評等（-2 到 +2，12 項）

| # | 項目 | 評分 | 依據（原文或數字） |
|---|------|------|-------------------|
| 1 | CEO 溝通與表現 | | |
| 2 | 公司文化 | | |
| 3 | 誠信 | | |
| 4 | 可持續商業模式 | | |
| 5 | 資本管理 | | |
| 6 | 坦承溝通 | | |
| 7 | 策略清晰度 | | |
| 8 | 領導力 | | |
| 9 | 願景 | | |
| 10 | 股東關係 | | |
| 11 | 問責文化 | | |
| 12 | 真實性 | | |
| **合計** | | **/24** | |

含糊其辭自動標記（若出現請列出）：
□ 「賦能」「生態系」「全方位」「顛覆性」「史無前例」
□ 被動語態掩蓋責任
□ 只報喜不報憂

## 五、Q&A 關鍵句
- 最重要問題：[問題] → [管理層回答，近似逐字]
- 迴避或模糊的問題（若有）：[問題] → [為何認定迴避]

## 六、本季 vs 上季變化
- 語氣：更樂觀 / 更保守 / 相似
- 新出現的風險（本季首次提及）
- 新出現的機會（本季首次提及）
- 上季承諾本季是否兌現

## 七、第二層思考（Howard Marks）
- 股價如何反應？
- 市場現在定價的假設是什麼？
- 「好的程度」是否超出市場預期？
- 什麼情況下這個論點是完全錯的？（Munger 逆向）

## 八、後續追蹤三指標
1.
2.
3.

語言：繁體中文。數字保留英文。"""


# ─── 分析模板 ───────────────────────────────────────────────────────────────

EARNINGS_TEMPLATE = """請對以下個股進行法說會深度分析：

=== 標的 ===
{ticker} — {name}

=== 市場數據（來自 decision packet）===
現價：${price}  今日漲跌：{ret_1d:+.1f}%  量比：{vol_ratio}x
RSI：{rsi}  均線趨勢：{trend}  EMA 交叉：{crossover}
1M 表現：{ret_1m:+.1f}%  3M 表現：{ret_3m:+.1f}%

=== 今日相關訊號 ===
{signals_text}

=== 法說會資料 ===
{transcript_or_news}

請嚴格按照輸出結構完成分析。若缺乏逐字稿，在能回答的區塊盡量量化，
無法回答的欄位填「需逐字稿」並說明從哪裡可以找到該資料。"""


# ─── 工具函式 ───────────────────────────────────────────────────────────────

def load_packet(date_str: str) -> dict:
    path = os.path.join(PACKET_DIR, f"decision_packet_{date_str}.json")
    if not os.path.exists(path):
        print(f"[earnings_call] 找不到 {path}，請先執行 collector.py")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_ticker_data(packet: dict, ticker: str) -> dict:
    return packet.get("raw_tickers", {}).get(ticker, {})


def get_ticker_signals(packet: dict, ticker: str) -> list[dict]:
    return [s for s in packet.get("signals", []) if s.get("ticker") == ticker]


def call_minimax(system: str, prompt: str, max_tokens: int = 4000) -> str:
    if not ANTHROPIC_API_KEY:
        print("[earnings_call] 未設定 MINIMAX_API_KEY")
        sys.exit(1)
    try:
        import anthropic
        client  = anthropic.Anthropic(base_url=ANTHROPIC_BASE_URL, api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=LLM_MODEL, max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        content = next((b.text for b in message.content if hasattr(b, "text")), "")
        return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    except Exception as e:
        return f"[MiniMax 呼叫失敗] {e}"


def build_prompt(ticker: str, packet: dict, transcript: str = "") -> str:
    d       = get_ticker_data(packet, ticker)
    signals = get_ticker_signals(packet, ticker)

    if not d:
        print(f"[earnings_call] ⚠️  packet 中無 {ticker} 資料，繼續但數據欄位為空")

    signals_text = "\n".join(
        f"[{s['level']}] {s['type']}: {s['detail']}" for s in signals
    ) or "今日無觸發訊號"

    transcript_or_news = transcript.strip() if transcript.strip() else (
        "（未提供逐字稿）請根據已知市場資訊與技術數據進行分析，"
        "並在每個缺乏資料的欄位標注「需逐字稿」。"
    )

    return EARNINGS_TEMPLATE.format(
        ticker             = ticker,
        name               = d.get("name", ticker),
        price              = d.get("price", "—"),
        ret_1d             = d.get("ret_1d", 0.0),
        vol_ratio          = d.get("vol_ratio") or "—",
        rsi                = d.get("rsi", "—"),
        trend              = d.get("trend", "—"),
        crossover          = d.get("crossover", "—"),
        ret_1m             = d.get("ret_1m", 0.0),
        ret_3m             = d.get("ret_3m", 0.0),
        signals_text       = signals_text,
        transcript_or_news = transcript_or_news,
    )


def save_report(ticker: str, date_str: str, analysis: str) -> str:
    os.makedirs(JOURNAL_DIR, exist_ok=True)
    path = os.path.join(JOURNAL_DIR, f"{date_str}_{ticker}_earnings.md")
    header = (
        f"# {ticker} 法說會分析  {date_str}\n\n"
        f"> 模型：{LLM_MODEL}  框架：Anthropic financial-services + 黎氏評等\n\n---\n\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + analysis)
    return path


# ─── 主流程 ─────────────────────────────────────────────────────────────────

def run(
    ticker:     str,
    date_str:   Optional[str] = None,
    transcript: str = "",
) -> str:
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    print(f"[earnings_call] 分析 {ticker}  日期 {date_str}  模型 {LLM_MODEL}")

    packet   = load_packet(date_str)
    prompt   = build_prompt(ticker, packet, transcript)
    analysis = call_minimax(EARNINGS_SYSTEM_PROMPT, prompt)

    print("\n" + "="*60)
    print(analysis)
    print("="*60 + "\n")

    path = save_report(ticker, date_str, analysis)
    print(f"[earnings_call] ✅ 報告存入 {path}")
    return analysis


# ─── CLI 入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("用法：python3 earnings_call.py TICKER [YYYYMMDD] [--transcript]")
        sys.exit(1)

    ticker_arg   = args[0].upper()
    date_arg     = next((a for a in args[1:] if re.match(r"\d{8}", a)), None)
    use_transcript = "--transcript" in args

    transcript_text = ""
    if use_transcript:
        print("請貼入法說會逐字稿（完成後輸入 END 單獨一行）：")
        lines = []
        while True:
            line = input()
            if line.strip() == "END":
                break
            lines.append(line)
        transcript_text = "\n".join(lines)

    run(ticker_arg, date_arg, transcript_text)
