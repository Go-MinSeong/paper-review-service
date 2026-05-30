#!/bin/bash
# paper-reader 의 named subagents 를 Claude Code 의 글로벌 agents 디렉토리에
# 등록한다. 현재 등록되는 agent:
#   - paper-translator  : 논문 한 섹션 번역
#   - github-investigator: ambiguity ↔ 코드 대조 + GitHub 큐레이션
#
# Claude Code 는 세션 시작 시점에 ~/.claude/agents/*.md 를 한 번 로드한다.
# 따라서 이 스크립트는 paper-reader 스킬을 처음 받았을 때 한 번만 돌리면 됨.
#
# Usage:
#     bash install.sh           # 기본 위치에 설치
#     bash install.sh --project # 현재 프로젝트의 .claude/agents/ 에 설치
#
# 설치 안 해도 paper-reader 는 작동한다 — Task 의 general-purpose subagent 로
# 동적 prompt 를 던지는 fallback 경로가 SKILL.md / subagent-prompt.md 에 있음.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_DIR="$SCRIPT_DIR/assets/agents"

if [[ ! -d "$AGENTS_DIR" ]]; then
    echo "ERROR: agents dir not found at $AGENTS_DIR" >&2
    exit 1
fi

if [[ "${1:-}" == "--project" ]]; then
    DEST_DIR=".claude/agents"
    SCOPE="project"
else
    DEST_DIR="$HOME/.claude/agents"
    SCOPE="global"
fi

mkdir -p "$DEST_DIR"
INSTALLED=()
for f in "$AGENTS_DIR"/*.md; do
    [[ -f "$f" ]] || continue
    cp "$f" "$DEST_DIR/$(basename "$f")"
    INSTALLED+=("$(basename "$f" .md)")
done

echo "✓ installed agents to $DEST_DIR ($SCOPE):"
for name in "${INSTALLED[@]}"; do
    echo "   - $name"
done
echo ""
echo "Restart your Claude Code session for the agents to be picked up."
echo "After restart, paper-reader can dispatch via:"
echo "    Task(subagent_type=\"paper-translator\", prompt=\"...\")"
echo "    Task(subagent_type=\"github-investigator\", prompt=\"...\")"
echo ""
echo "Or skip this install entirely — paper-reader will fall back to"
echo "Task with general-purpose subagent + the templates in references/subagent-prompt.md."
