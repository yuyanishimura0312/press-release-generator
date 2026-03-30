#!/usr/bin/env python3
"""
Notion Page Reader - reads a Notion page via Notion API and saves as JSON.
Used by the Streamlit app to load release content from Notion.

Usage:
    python notion_reader.py <page_url_or_id>
    python notion_reader.py https://www.notion.so/My-Page-abc123def456

Requires NOTION_API_KEY in .env or environment variable.
"""

import json
import os
import re
import sys
from pathlib import Path

import requests

ENV_FILE = Path(__file__).parent / ".env"
OUTPUT_FILE = Path(__file__).parent / "notion_content.json"

# Load .env
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def extract_page_id(url_or_id: str) -> str:
    """Extract Notion page ID from URL or raw ID."""
    # Already a UUID
    clean = url_or_id.strip().replace("-", "")
    if re.match(r'^[0-9a-f]{32}$', clean):
        # Format as UUID
        return f"{clean[:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:]}"

    # Extract from URL: last 32 hex chars before any query string
    match = re.search(r'([0-9a-f]{32})', url_or_id.split("?")[0])
    if match:
        h = match.group(1)
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"

    raise ValueError(f"NotionページIDを抽出できません: {url_or_id}")


def get_page_title(page_data: dict) -> str:
    """Extract title from page properties."""
    props = page_data.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            title_parts = prop.get("title", [])
            return "".join(t.get("plain_text", "") for t in title_parts)
    return ""


def get_block_text(block: dict) -> str:
    """Extract text content from a single block."""
    block_type = block.get("type", "")
    block_data = block.get(block_type, {})

    # Text-based blocks
    if "rich_text" in block_data:
        texts = block_data["rich_text"]
        content = "".join(t.get("plain_text", "") for t in texts)

        if block_type == "heading_1":
            return f"# {content}"
        elif block_type == "heading_2":
            return f"## {content}"
        elif block_type == "heading_3":
            return f"### {content}"
        elif block_type == "bulleted_list_item":
            return f"- {content}"
        elif block_type == "numbered_list_item":
            return f"1. {content}"
        elif block_type == "to_do":
            checked = block_data.get("checked", False)
            mark = "x" if checked else " "
            return f"- [{mark}] {content}"
        elif block_type == "quote":
            return f"> {content}"
        elif block_type == "callout":
            return f"> {content}"
        elif block_type == "toggle":
            return f"* {content}"
        else:
            return content

    # Table rows
    if block_type == "table_row":
        cells = block_data.get("cells", [])
        row = []
        for cell in cells:
            cell_text = "".join(t.get("plain_text", "") for t in cell)
            row.append(cell_text)
        return " | ".join(row)

    # Divider
    if block_type == "divider":
        return "---"

    return ""


def fetch_all_blocks(page_id: str, api_key: str) -> list[dict]:
    """Fetch all blocks from a Notion page, handling pagination."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
    }

    all_blocks = []
    url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"

    while url:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        all_blocks.extend(data.get("results", []))

        if data.get("has_more"):
            cursor = data.get("next_cursor")
            url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100&start_cursor={cursor}"
        else:
            url = None

    # Recursively fetch children for blocks that have them
    for block in all_blocks:
        if block.get("has_children"):
            child_blocks = fetch_all_blocks(block["id"], api_key)
            block["_children"] = child_blocks

    return all_blocks


def blocks_to_text(blocks: list[dict], indent: int = 0) -> str:
    """Convert blocks to readable text."""
    lines = []
    prefix = "  " * indent

    for block in blocks:
        text = get_block_text(block)
        if text:
            lines.append(f"{prefix}{text}")

        # Process children
        children = block.get("_children", [])
        if children:
            child_text = blocks_to_text(children, indent + 1)
            if child_text:
                lines.append(child_text)

    return "\n".join(lines)


def read_notion_page(url_or_id: str, api_key: str) -> dict:
    """Read a Notion page and return structured content."""
    page_id = extract_page_id(url_or_id)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
    }

    # Fetch page metadata
    resp = requests.get(f"https://api.notion.com/v1/pages/{page_id}", headers=headers)
    resp.raise_for_status()
    page_data = resp.json()

    title = get_page_title(page_data)

    # Fetch all blocks
    blocks = fetch_all_blocks(page_id, api_key)
    content_text = blocks_to_text(blocks)

    result = {
        "page_id": page_id,
        "title": title,
        "content": content_text,
        "url": page_data.get("url", ""),
        "last_edited": page_data.get("last_edited_time", ""),
    }

    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python notion_reader.py <page_url_or_id>")
        sys.exit(1)

    api_key = os.environ.get("NOTION_API_KEY")
    if not api_key:
        print("NOTION_API_KEY が設定されていません。")
        print(".env ファイルに NOTION_API_KEY=ntn_... を追加してください。")
        print()
        print("取得方法:")
        print("  1. https://www.notion.so/profile/integrations にアクセス")
        print("  2. 「新しいインテグレーション」を作成")
        print("  3. 対象のNotionページで「コネクト」からこのインテグレーションを追加")
        print("  4. トークンを .env に記載")
        sys.exit(1)

    url_or_id = sys.argv[1]

    try:
        result = read_notion_page(url_or_id, api_key)
        OUTPUT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"タイトル: {result['title']}")
        print(f"文字数: {len(result['content'])}文字")
        print(f"保存先: {OUTPUT_FILE}")
    except Exception as e:
        print(f"エラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
