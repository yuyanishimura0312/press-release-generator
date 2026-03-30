#!/bin/bash
# Fetch Notion page content via Claude Code CLI (uses existing MCP connection)
# Usage: ./fetch_notion.sh <notion_page_url_or_id>
#
# Outputs JSON to notion_content.json

if [ -z "$1" ]; then
    echo "Usage: ./fetch_notion.sh <notion_page_url_or_id>"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT="$SCRIPT_DIR/notion_content.json"

echo "Notionページを読み取り中: $1"

claude -p "以下のNotionページの内容を読み取って、JSON形式で $OUTPUT に保存してください。

ページURL/ID: $1

手順:
1. mcp__notion__API-retrieve-a-page でページのタイトルを取得
2. mcp__notion__API-get-block-children でページの全ブロックを取得（has_childrenがtrueの場合は子ブロックも再帰的に取得）
3. 全テキストを結合
4. 以下のJSON形式で $OUTPUT にWriteツールで保存:
{
  \"title\": \"ページタイトル\",
  \"content\": \"ページの全テキスト内容（見出しは # ## ### で、箇条書きは - で、改行で区切る）\",
  \"page_id\": \"ページID\"
}

JSONファイルの保存のみ行い、それ以外の出力は不要です。"

if [ -f "$OUTPUT" ]; then
    echo "保存完了: $OUTPUT"
    python3 -c "import json; d=json.load(open('$OUTPUT')); print(f'タイトル: {d.get(\"title\",\"\")}'); print(f'文字数: {len(d.get(\"content\",\"\"))}文字')"
else
    echo "エラー: ファイルが生成されませんでした"
    exit 1
fi
