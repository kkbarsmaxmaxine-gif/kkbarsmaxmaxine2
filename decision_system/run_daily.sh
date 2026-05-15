#!/bin/bash
# run_daily.sh — 每日收盤後完整執行流程
# 用法：bash run_daily.sh  或  bash run_daily.sh 20260515（指定日期）

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DATE_ARG="${1:-}"
LOG_FILE="./journal/$(date '+%Y%m%d')_run.log"
mkdir -p ./journal

echo "============================================" | tee -a "$LOG_FILE"
echo "  每日市場掃描  $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "============================================" | tee -a "$LOG_FILE"

run_step() {
    local step="$1"
    local script="$2"
    echo "" | tee -a "$LOG_FILE"
    echo "▶ ${step}..." | tee -a "$LOG_FILE"
    if [ -n "$DATE_ARG" ]; then
        python3 "$script" "$DATE_ARG" 2>&1 | tee -a "$LOG_FILE"
    else
        python3 "$script" 2>&1 | tee -a "$LOG_FILE"
    fi
    if [ $? -ne 0 ]; then
        echo "  ❌ ${step} 失敗，中止" | tee -a "$LOG_FILE"
        exit 1
    fi
    echo "  ✅ ${step} 完成" | tee -a "$LOG_FILE"
}

run_step "資料收集 collector"      collector.py
run_step "規則引擎 rules"          rules.py
run_step "日誌生成 journal_writer" journal_writer.py
run_step "AI 分析 call_minimax"   call_minimax.py

echo "" | tee -a "$LOG_FILE"
echo "============================================" | tee -a "$LOG_FILE"
echo "  完成  $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "  日誌：./journal/$(date '+%Y%m%d')_journal.md" | tee -a "$LOG_FILE"
echo "  分析：./journal/$(date '+%Y%m%d')_analysis.md" | tee -a "$LOG_FILE"
echo "============================================" | tee -a "$LOG_FILE"
