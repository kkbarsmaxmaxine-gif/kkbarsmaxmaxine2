"""
call_minimax.py — MiniMax AI 分析引擎
讀取 decision_packet + journal，透過 Anthropic SDK 接 MiniMax endpoint，
輸出七維分析並回寫至 journal 的第六節
"""

import json
import os
import re
import sys
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../automation/.env"))

# MiniMax Anthropic-compatible endpoint
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
ANTHROPIC_API_KEY  = os.getenv("MINIMAX_API_KEY", "")
LLM_MODEL          = os.getenv("LLM_MODEL", "MiniMax-M2.5")

PACKET_DIR  = os.path.join(os.path.dirname(__file__), "packets")
JOURNAL_DIR = os.path.join(os.path.dirname(__file__), "journal")

SYSTEM_PROMPT = """你是一位嚴格的投資判斷訓練教練，同時是量化分析師與行為金融學家。

你的任務：根據當日市場數據與決策包，產出七維結構化分析，幫助投資人分辨事實與敘事，提升判斷質量。

─── 核心框架：七維分析 ───────────────────────────────────────────

【1. 事實】     只列可驗證的數字、價格、訊號，不加任何解讀
【2. 推論】     從事實出發的合理推論，標注信心程度（高/中/低）
【3. 反方論點】 主流論點最容易錯的地方，強制列出至少兩點
【4. 驗證指標】 未來 5-10 個交易日需要觀察的具體數字或事件
【5. 失效條件】 什麼情況下今日主要判斷失效
【6. 交易計畫】 具體的進場/出場/加倉/減碼條件（無則說明原因）
【7. 敘事警示】 今日最可能出現的確認偏誤，強制指出至少一點

─── 財報觸發模式（有法說會訊號時自動啟用）───────────────────────

若今日訊號中有任何個股公布財報，在七維分析之後額外輸出【財報快評】區塊：

**原則：只分析新資訊，不重述公司背景。**

Beat/Miss 分析（量化優先）
  - 每個指標列出：預估值 → 實際值 → 差異 % → 是否重要
  - 格式：營收 $X.Xb vs 預估 $X.Xb（+X.X%，beat/miss）

指引評估
  - 下季指引 vs 街頭預估（這是法說會最關鍵的數字）
  - 全年指引上修/下修/維持：量化幅度

三層態度解讀（參考黎氏評等）
  - 表層正向：只報喜的訊號（⚠️ 警示）
  - 真實正向：主動揭露挑戰並說明應對（✅ 有效訊號）
  - 深層正向：對長期有清晰邏輯（✅✅ 最強訊號）

Q&A 關鍵句
  - 最重要的一個問題及管理層回答（逐字或近似逐字）
  - 管理層迴避或模糊的問題（若有）

本次法說會 vs 上季變化
  - 語氣變化：更樂觀/更保守/相似
  - 新出現的風險或機會

股價反應解讀（第二層思考）
  - 股價如何反應？這個反應合理嗎？
  - 市場現在定價的假設是什麼？

─── 格式規定 ──────────────────────────────────────────────────────

- 每個區塊用【標題】開頭
- 列點說明，不要長段落
- 信心程度一律標注（高/中/低）
- 反方論點至少兩點，敘事警示至少一點
- 數字必須具體，不接受「大幅」「明顯」等模糊詞
- 語言：繁體中文"""

ANALYSIS_TEMPLATE = """請分析以下市場數據，產出七維結構化分析：

=== 日期 ===
{date}

=== 市場快照 ===
QQQ 今日: {qqq_1d:+.2f}%  SPY: {spy_1d:+.2f}%  SOXX: {soxx_1d:+.2f}%
QQQ 1M: {qqq_1m:+.2f}%

=== 今日訊號（{signal_count} 個）===
{signals_text}

=== 強弱排名 ===
今日領漲：{top5}
今日領跌：{bottom5}
本月相對 QQQ 領漲：{leaders}
本月相對 QQQ 落後：{laggards}

=== 重點個股狀態 ===
{focus_text}

請嚴格按七維框架輸出分析。"""


def format_signals(signals: list[dict]) -> str:
    if not signals:
        return "無訊號"
    lines = []
    for s in signals:
        vol = f" [{s['vol_tag']}]" if s.get("vol_tag") else ""
        lines.append(f"[{s['level']}] {s['type']} - {s['name']}({s['ticker']}){vol}: {s['detail']}")
    return "\n".join(lines)


def format_focus(focus: dict) -> str:
    lines = []
    for sym, d in focus.items():
        cross = {"golden_cross": "金叉", "death_cross": "死叉",
                 "above": "EMA8>22", "below": "EMA8<22"}.get(d.get("crossover", ""), "")
        lines.append(
            f"{sym}({d['name']}): ${d['price']:.2f}  今日{d['ret_1d']:+.1f}%  1M{d['ret_1m']:+.1f}%"
            f"  RSI{d['rsi']:.0f}  {d.get('trend','?')}  {cross}"
        )
    return "\n".join(lines)


def format_rank_list(items: list[dict]) -> str:
    return "  ".join([f"{r['name']}({r['ticker']}) {r['ret_1d']:+.1f}%" for r in items])


def build_prompt(packet: dict) -> str:
    ms      = packet["market_summary"]
    signals = packet["signals"]
    rank    = packet["rankings"]
    focus   = packet["focus_stocks"]

    return ANALYSIS_TEMPLATE.format(
        date         = packet["date"],
        qqq_1d       = ms["qqq_1d"],
        spy_1d       = ms["spy_1d"],
        soxx_1d      = ms["soxx_1d"],
        qqq_1m       = ms["qqq_1m"],
        signal_count = len(signals),
        signals_text = format_signals(signals),
        top5         = format_rank_list(rank.get("top5_1d", [])),
        bottom5      = format_rank_list(rank.get("bottom5_1d", [])),
        leaders      = "  ".join([f"{r['name']}({r['ticker']}) 1M{r['ret_1m']:+.1f}%" for r in rank.get("leaders_vs_qqq", [])]),
        laggards     = "  ".join([f"{r['name']}({r['ticker']}) 1M{r['ret_1m']:+.1f}%" for r in rank.get("laggards_vs_qqq", [])]),
        focus_text   = format_focus(focus),
    )


def call_minimax(prompt: str) -> str:
    if not ANTHROPIC_API_KEY:
        print("[call_minimax] 未設定 MINIMAX_API_KEY，無法呼叫 API")
        sys.exit(1)

    try:
        import anthropic
        client = anthropic.Anthropic(
            base_url=ANTHROPIC_BASE_URL,
            api_key=ANTHROPIC_API_KEY,
        )
        message = client.messages.create(
            model      = LLM_MODEL,
            max_tokens = 3500,
            system     = SYSTEM_PROMPT,
            messages   = [{"role": "user", "content": prompt}],
        )
        # M2 推理模型返回 [ThinkingBlock, TextBlock]，取第一個有 text 的 block
        content = next(
            (block.text for block in message.content if hasattr(block, "text")),
            "",
        )
        # 兼容舊格式：剝除 <think> tags
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        return content

    except Exception as e:
        return f"MiniMax API 呼叫失敗: {e}"


def write_analysis_to_journal(journal_path: str, analysis: str) -> None:
    """將七維分析回寫至 journal 的第六節"""
    with open(journal_path, encoding="utf-8") as f:
        content = f.read()

    # 將 _待 AI 分析_ 整塊替換為實際分析
    replacement = f"\n{analysis}\n"
    # 找到第六節範圍並替換
    pattern = r"(## 六、七維分析（MiniMax 填入）.*?<!-- call_minimax\.py 執行後自動填入以下區塊 -->)(.*?)(---\n\n## 七)"
    new_content = re.sub(
        pattern,
        r"\1\n" + replacement.replace("\\", "\\\\") + r"\3",
        content,
        flags=re.DOTALL,
    )
    if new_content == content:
        # fallback: 直接 append
        new_content = content + f"\n\n---\n\n**MiniMax 分析**\n\n{analysis}\n"

    with open(journal_path, "w", encoding="utf-8") as f:
        f.write(new_content)


def run(date_str: Optional[str] = None) -> str:
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    packet_path  = os.path.join(PACKET_DIR,  f"decision_packet_{date_str}.json")
    journal_path = os.path.join(JOURNAL_DIR, f"{date_str}_journal.md")

    if not os.path.exists(packet_path):
        print(f"[call_minimax] 找不到 {packet_path}")
        sys.exit(1)

    with open(packet_path, encoding="utf-8") as f:
        packet = json.load(f)

    print(f"[call_minimax] 使用 {LLM_MODEL} via {ANTHROPIC_BASE_URL}")
    prompt   = build_prompt(packet)
    analysis = call_minimax(prompt)

    print("\n" + "="*60)
    print(analysis)
    print("="*60 + "\n")

    # 存獨立分析檔
    analysis_path = os.path.join(JOURNAL_DIR, f"{date_str}_analysis.md")
    with open(analysis_path, "w", encoding="utf-8") as f:
        f.write(f"# AI 七維分析  {packet['date']}\n\n")
        f.write(f"> 模型：{LLM_MODEL}  endpoint：{ANTHROPIC_BASE_URL}\n\n---\n\n")
        f.write(analysis)
    print(f"[call_minimax] ✅ 分析存入 {analysis_path}")

    # 回寫至 journal
    if os.path.exists(journal_path):
        write_analysis_to_journal(journal_path, analysis)
        print(f"[call_minimax] ✅ 分析已回寫至 {journal_path}")

    return analysis


if __name__ == "__main__":
    run()
