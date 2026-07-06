#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# prep-release.sh — 發布準備輔助腳本
# 用法: bash scripts/prep-release.sh <版本號>
# 範例: bash scripts/prep-release.sh 0.5.1
#
# 在建立 GitHub Release 前執行：
#   1. 驗證所有測試通過
#   2. 用 towncrier 構建 CHANGELOG.md
#   3. 更新 pyproject.toml 版本號
#   4. 提交並打 tag
# ─────────────────────────────────────────────────────────────────

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "用法: $0 <版本號>"
    echo "範例: $0 0.5.1"
    exit 1
fi

VERSION="$1"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "🔍 1/4 — 驗證測試套件..."
if command -v .venv/bin/python &>/dev/null; then
    PYTHON=".venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    PYTHON="python"
fi

$PYTHON -m pytest tests/ -m "unit" --tb=short -q --timeout=30 2>&1 | tail -5
echo ""

echo "📝 2/4 — 更新 pyproject.toml 版本號..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s/^version = \".*\"/version = \"$VERSION\"/" pyproject.toml
else
    sed -i "s/^version = \".*\"/version = \"$VERSION\"/" pyproject.toml
fi

echo "📖 3/4 — 用 towncrier 構建 CHANGELOG..."
$PYTHON -m towncrier build --yes --version "$VERSION" 2>/dev/null || {
    echo "⚠️  towncrier 構建失敗，可能沒有 changelog fragment。"
    echo "   手動更新 CHANGELOG.md 後繼續。"
}

echo "✅ 4/4 — 準備完成！"
echo ""
echo "下一步："
echo "  git add -A"
echo "  git commit -m \"release: v$VERSION\""
echo "  git tag -a \"v$VERSION\" -m \"v$VERSION\""
echo "  git push && git push --tags"
echo "  然後在 GitHub 上建立 Release："
echo "    gh release create v$VERSION --generate-notes"
