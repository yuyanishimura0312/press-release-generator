"""
Press Release Generator - Streamlit Web App
AI-powered, PR Times optimized press release generator

Minimal input -> AI auto-generates full press release
Company info auto-extracted from URL
"""

import json
import os
import re
import streamlit as st
import requests
import anthropic
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import markdown as md_lib

# -- Config --
PROFILE_DIR = Path(__file__).parent / "profiles"
PROFILE_DIR.mkdir(exist_ok=True)

# Load secrets: Streamlit Cloud secrets > environment
try:
    for key in ["ANTHROPIC_API_KEY", "NOTION_API_KEY"]:
        if hasattr(st, "secrets") and key in st.secrets:
            os.environ.setdefault(key, st.secrets[key])
except Exception:
    pass

# -- Usage limits per session --
MAX_GENERATIONS_PER_SESSION = 10

RELEASE_TYPES = {
    "service": "サービスリリース",
    "partnership": "提携・協業",
    "funding": "資金調達完了",
    "event": "イベント開催",
    "update": "サービスアップデート",
    "award": "受賞・認定",
}

RELEASE_DESCRIPTIONS = {
    "service": "新規プロダクト・機能のリリース",
    "partnership": "業務提携、共同研究、MOU締結等",
    "funding": "シード、シリーズA等の資金調達完了",
    "event": "カンファレンス、セミナー等の開催",
    "update": "既存プロダクトの大幅改善",
    "award": "表彰、認証取得等",
}


# -- Profile helpers (session-based for multi-user safety) --

def _init_session_profiles():
    """Initialize session-based profile storage."""
    if "user_profiles" not in st.session_state:
        st.session_state["user_profiles"] = {}


def list_profiles() -> list[str]:
    _init_session_profiles()
    return list(st.session_state["user_profiles"].keys())


def load_profile(name: str) -> dict:
    _init_session_profiles()
    return st.session_state["user_profiles"].get(name, {})


def save_profile(data: dict, name: str):
    _init_session_profiles()
    st.session_state["user_profiles"][name] = data


# -- Notion page reader --

def extract_notion_page_id(url_or_id: str) -> str:
    """Extract Notion page ID from URL or raw ID."""
    clean = url_or_id.strip().replace("-", "")
    if re.match(r'^[0-9a-f]{32}$', clean):
        return f"{clean[:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:]}"
    match = re.search(r'([0-9a-f]{32})', url_or_id.split("?")[0])
    if match:
        h = match.group(1)
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
    raise ValueError(f"NotionページIDを抽出できません: {url_or_id}")


def _get_block_text(block: dict) -> str:
    """Extract text content from a single Notion block."""
    block_type = block.get("type", "")
    block_data = block.get(block_type, {})

    if "rich_text" in block_data:
        content = "".join(t.get("plain_text", "") for t in block_data["rich_text"])
        prefixes = {
            "heading_1": "# ", "heading_2": "## ", "heading_3": "### ",
            "bulleted_list_item": "- ", "numbered_list_item": "1. ",
            "quote": "> ", "callout": "> ", "toggle": "* ",
        }
        if block_type == "to_do":
            mark = "x" if block_data.get("checked") else " "
            return f"- [{mark}] {content}"
        return f"{prefixes.get(block_type, '')}{content}"

    if block_type == "table_row":
        cells = block_data.get("cells", [])
        return " | ".join(
            "".join(t.get("plain_text", "") for t in cell) for cell in cells
        )
    if block_type == "divider":
        return "---"
    return ""


def fetch_notion_blocks(page_id: str, api_key: str) -> list[dict]:
    """Fetch all blocks from a Notion page with pagination."""
    headers = {"Authorization": f"Bearer {api_key}", "Notion-Version": "2022-06-28"}
    all_blocks = []
    url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"

    while url:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        all_blocks.extend(data.get("results", []))
        if data.get("has_more"):
            cursor = data["next_cursor"]
            url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100&start_cursor={cursor}"
        else:
            url = None

    for block in all_blocks:
        if block.get("has_children"):
            block["_children"] = fetch_notion_blocks(block["id"], api_key)

    return all_blocks


def blocks_to_text(blocks: list[dict], indent: int = 0) -> str:
    """Convert Notion blocks to readable text."""
    lines = []
    prefix = "  " * indent
    for block in blocks:
        text = _get_block_text(block)
        if text:
            lines.append(f"{prefix}{text}")
        for child in block.get("_children", []):
            child_text = _get_block_text(child)
            if child_text:
                lines.append(f"{'  ' * (indent + 1)}{child_text}")
            for grandchild in child.get("_children", []):
                gc_text = _get_block_text(grandchild)
                if gc_text:
                    lines.append(f"{'  ' * (indent + 2)}{gc_text}")
    return "\n".join(lines)


def read_notion_page(url_or_id: str, api_key: str) -> dict:
    """Read a Notion page and return title + content text."""
    page_id = extract_notion_page_id(url_or_id)
    headers = {"Authorization": f"Bearer {api_key}", "Notion-Version": "2022-06-28"}

    resp = requests.get(f"https://api.notion.com/v1/pages/{page_id}", headers=headers)
    resp.raise_for_status()
    page_data = resp.json()

    # Extract title
    title = ""
    for prop in page_data.get("properties", {}).values():
        if prop.get("type") == "title":
            title = "".join(t.get("plain_text", "") for t in prop.get("title", []))
            break

    blocks = fetch_notion_blocks(page_id, api_key)
    content = blocks_to_text(blocks)

    return {"title": title, "content": content, "page_id": page_id}


def identify_company_from_notion(title: str, content: str) -> dict:
    """Use AI to identify the company from Notion content and find its website."""
    client = get_anthropic_client()

    prompt = f"""以下はNotionページから取得した、プレスリリースの素材情報です。
この内容から、プレスリリースを発行する会社を特定してください。

【ページタイトル】
{title}

【ページ内容】
{content[:4000]}

---

以下のJSON形式で返してください:
{{
  "company_name": "会社名（正式名称。株式会社を含む）",
  "company_name_short": "略称やサービスブランド名",
  "company_url": "会社のウェブサイトURL（推測でもOK）",
  "release_type_suggestion": "service/partnership/funding/event/update/award のいずれか最も適切なもの"
}}

JSONのみを返してください。"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        return json.loads(json_match.group())
    return {}


def analyze_notion_full(title: str, content: str, release_type: str) -> dict:
    """Analyze Notion content: extract release info AND company info in one call."""
    client = get_anthropic_client()

    type_fields = {
        "service": "サービス名、サービスURL、ターゲット、サービス概要、背景・課題、主な特徴（3つ程度）、差別化ポイント、数値データ、価格、代表コメント、今後の展望",
        "partnership": "提携先企業名、提携の種類、提携の目的・背景、提携内容の詳細、期待される成果、代表コメント、提携先コメント",
        "funding": "ラウンド、調達金額、投資家（1行1社）、リードインベスター、資金使途、事業概要、市場背景、今後の戦略、代表コメント",
        "event": "イベント名、開催日時、開催場所、対象者、イベント概要、プログラム・登壇者、定員、参加費、申込URL",
        "update": "サービス名、サービスURL、アップデート概要、主な変更点、アップデートの背景、ユーザーへのメリット",
        "award": "受賞名、授与機関、受賞日、受賞理由、対象サービス概要、受賞の意義",
    }

    prompt = f"""以下はNotionページから取得した、プレスリリースの素材情報です。
この内容を分析して、2つのことを行ってください。

【ページタイトル】
{title}

【ページ内容】
{content[:6000]}

---

■ タスク1: プレスリリースを発行する会社の特定
内容から会社名とウェブサイトURLを特定してください。

■ タスク2: 「{RELEASE_TYPES[release_type]}」のプレスリリースに必要な情報を抽出
以下の項目を抽出してください:
{type_fields.get(release_type, '')}

---

以下のJSON形式で返してください:
{{
  "company": {{
    "company_name": "会社名（正式名称）",
    "company_name_short": "略称やブランド名",
    "company_url": "会社のウェブサイトURL（わかれば）"
  }},
  "release_info": "抽出した情報をテキストで整理（項目名: 値 の形式で改行区切り）",
  "release_type_suggestion": "service/partnership/funding/event/update/award のいずれか最も適切なもの"
}}

見つからない情報は「（情報なし）」としてください。
ページの内容を最大限活用し、プレスリリースに使える情報を漏れなく抽出してください。
JSONのみを返してください。"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        return json.loads(json_match.group())
    return {}


# -- PDF generation --

def generate_pdf(markdown_text: str) -> bytes:
    """Convert markdown press release to styled PDF with proper layout."""
    from fpdf import FPDF
    import urllib.request

    # Download Noto Sans JP font
    font_dir = Path(__file__).parent / "fonts"
    font_dir.mkdir(exist_ok=True)
    font_path = font_dir / "NotoSansJP-Regular.ttf"

    if not font_path.exists():
        urllib.request.urlretrieve(
            "https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf",
            str(font_path),
        )

    class PressReleasePDF(FPDF):
        def header(self):
            pass
        def footer(self):
            self.set_y(-15)
            self.set_font("NotoSansJP", "", 7)
            self.set_text_color(156, 149, 144)
            self.cell(0, 10, f"Page {self.page_no()}", align="C")

    pdf = PressReleasePDF()
    pdf.set_auto_page_break(auto=True, margin=25)
    pdf.set_margins(25, 25, 25)
    pdf.add_page()
    pdf.add_font("NotoSansJP", "", str(font_path), uni=True)
    pdf.add_font("NotoSansJP", "B", str(font_path), uni=True)

    # -- PRESS RELEASE badge --
    pdf.set_fill_color(120, 60, 40)
    pdf.set_text_color(253, 250, 247)
    pdf.set_font("NotoSansJP", "B", 7)
    pdf.cell(36, 5.5, "PRESS RELEASE", fill=True, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    # -- Parse and render --
    lines = markdown_text.split("\n")
    i = 0
    page_w = pdf.w - pdf.l_margin - pdf.r_margin

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            pdf.ln(2)
            i += 1
            continue

        # --- H1: Title ---
        if line.startswith("# "):
            text = line[2:].replace("**", "")
            pdf.set_font("NotoSansJP", "B", 14)
            pdf.set_text_color(26, 26, 26)
            pdf.multi_cell(page_w, 7.5, text)
            # terracotta underline
            pdf.set_draw_color(120, 60, 40)
            pdf.set_line_width(0.6)
            pdf.line(pdf.l_margin, pdf.get_y() + 2, pdf.l_margin + page_w, pdf.get_y() + 2)
            pdf.set_line_width(0.2)
            pdf.ln(6)

        # --- H2: Section header ---
        elif line.startswith("## "):
            text = line[3:].replace("**", "")
            pdf.ln(5)
            pdf.set_draw_color(211, 131, 111)
            pdf.set_line_width(0.8)
            y_top = pdf.get_y()
            pdf.set_font("NotoSansJP", "B", 11)
            pdf.set_text_color(120, 60, 40)
            pdf.set_x(pdf.l_margin + 5)
            pdf.multi_cell(page_w - 5, 6.5, text)
            y_bottom = pdf.get_y()
            pdf.line(pdf.l_margin, y_top, pdf.l_margin, y_bottom)
            pdf.set_line_width(0.2)
            pdf.ln(3)

        # --- HR ---
        elif line == "---":
            pdf.ln(4)
            pdf.set_draw_color(224, 219, 213)
            pdf.set_line_width(0.3)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + page_w, pdf.get_y())
            pdf.set_line_width(0.2)
            pdf.ln(4)

        # --- Table ---
        elif line.startswith("|") and "|" in line[1:]:
            # Collect all table rows
            table_rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = lines[i].strip()
                cells = [c.strip().replace("**", "") for c in row.split("|")[1:-1]]
                # Skip separator rows
                if not all(c.replace("-", "").replace(":", "").strip() == "" for c in cells):
                    table_rows.append(cells)
                i += 1
            i -= 1  # will be incremented at end of loop

            if table_rows:
                num_cols = len(table_rows[0])
                if num_cols == 2:
                    col_widths = [page_w * 0.25, page_w * 0.75]
                else:
                    col_widths = [page_w / num_cols] * num_cols

                for row_idx, cells in enumerate(table_rows):
                    is_header = (row_idx == 0)
                    # Calculate row height based on content
                    max_lines = 1
                    for ci, cell in enumerate(cells):
                        cw = col_widths[ci] - 4 if ci < len(col_widths) else 30
                        pdf.set_font("NotoSansJP", "B" if is_header else "", 9)
                        n = max(1, len(cell) * 4.5 / max(cw, 1))  # rough estimate
                        max_lines = max(max_lines, n)
                    row_h = max(7, int(max_lines) * 5 + 3)

                    for ci, cell in enumerate(cells):
                        cw = col_widths[ci] if ci < len(col_widths) else 30
                        x_before = pdf.get_x()
                        y_before = pdf.get_y()

                        if is_header:
                            pdf.set_fill_color(247, 242, 237)
                            pdf.set_text_color(120, 60, 40)
                            pdf.set_font("NotoSansJP", "B", 9)
                        else:
                            pdf.set_fill_color(255, 255, 255)
                            pdf.set_text_color(26, 26, 26)
                            pdf.set_font("NotoSansJP", "", 9)

                        pdf.set_draw_color(224, 219, 213)
                        pdf.rect(x_before, y_before, cw, row_h)
                        if is_header:
                            pdf.rect(x_before, y_before, cw, row_h, "F")
                            pdf.rect(x_before, y_before, cw, row_h, "D")

                        pdf.set_xy(x_before + 2, y_before + 1.5)
                        pdf.multi_cell(cw - 4, 4.5, cell if ci < len(cells) else "")
                        pdf.set_xy(x_before + cw, y_before)

                    pdf.ln(row_h)
                pdf.ln(3)

        # --- Bullet ---
        elif line.startswith("- ") or line.startswith("* "):
            text = line[2:].replace("**", "")
            pdf.set_font("NotoSansJP", "", 9.5)
            pdf.set_text_color(0, 0, 0)
            pdf.set_x(pdf.l_margin + 4)
            pdf.cell(4, 5, chr(8226), new_x="END")  # bullet char
            pdf.multi_cell(page_w - 10, 5, f" {text}")
            pdf.ln(1)

        # --- Numbered list ---
        elif len(line) > 2 and line[0].isdigit() and line[1] in ".)" and line[2] == " ":
            num = line[0]
            text = line[3:].replace("**", "")
            pdf.set_font("NotoSansJP", "", 9.5)
            pdf.set_text_color(0, 0, 0)
            pdf.set_x(pdf.l_margin + 4)
            pdf.cell(6, 5, f"{num}.", new_x="END")
            pdf.multi_cell(page_w - 12, 5, f" {text}")
            pdf.ln(1)

        # --- Bold-only line ---
        elif line.startswith("**") and line.endswith("**"):
            text = line.strip("* ")
            pdf.set_font("NotoSansJP", "B", 10)
            pdf.set_text_color(26, 26, 26)
            pdf.multi_cell(page_w, 5.5, text)
            pdf.ln(2)

        # --- Regular paragraph ---
        else:
            # Remove inline markdown
            text = line.replace("**", "")
            pdf.set_font("NotoSansJP", "", 9.5)
            pdf.set_text_color(0, 0, 0)
            pdf.multi_cell(page_w, 5.5, text)
            pdf.ln(2)

        i += 1

    return bytes(pdf.output())


# -- Web scraping for company info --

def scrape_company_info(url: str) -> dict:
    """Scrape company info from a given URL using AI extraction."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove script/style tags
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        # Limit to avoid token overflow
        text = text[:8000]

        # Also try to find company page links
        company_links = []
        for a in BeautifulSoup(resp.text, "html.parser").find_all("a", href=True):
            href = a["href"]
            link_text = a.get_text(strip=True)
            if any(kw in href.lower() or kw in link_text for kw in
                   ["company", "about", "corporate", "会社概要", "企業情報"]):
                if href.startswith("/"):
                    from urllib.parse import urljoin
                    href = urljoin(url, href)
                company_links.append(href)

        # Fetch company page if found
        company_page_text = ""
        if company_links:
            try:
                resp2 = requests.get(company_links[0], headers=headers, timeout=10)
                resp2.encoding = resp2.apparent_encoding
                soup2 = BeautifulSoup(resp2.text, "html.parser")
                for tag in soup2(["script", "style", "nav"]):
                    tag.decompose()
                company_page_text = soup2.get_text(separator="\n", strip=True)[:5000]
            except Exception:
                pass

        combined_text = text
        if company_page_text:
            combined_text += "\n\n--- 会社概要ページ ---\n" + company_page_text

        return {"success": True, "text": combined_text, "url": url}

    except Exception as e:
        return {"success": False, "error": str(e), "url": url}


def get_anthropic_client() -> anthropic.Anthropic:
    """Get Anthropic client with API key from server-side secrets."""
    api_key = None
    # Try Streamlit secrets first, then environment variable
    try:
        if hasattr(st, "secrets") and "ANTHROPIC_API_KEY" in st.secrets:
            api_key = st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        pass
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("サービスが一時的に利用できません。管理者にお問い合わせください。")
    return anthropic.Anthropic(api_key=api_key)


def _check_usage_limit() -> bool:
    """Check if user has exceeded session generation limit."""
    if "generation_count" not in st.session_state:
        st.session_state["generation_count"] = 0
    return st.session_state["generation_count"] < MAX_GENERATIONS_PER_SESSION


def _increment_usage():
    """Increment generation counter."""
    if "generation_count" not in st.session_state:
        st.session_state["generation_count"] = 0
    st.session_state["generation_count"] += 1


def extract_company_with_ai(scraped_text: str, url: str) -> dict:
    """Use Claude to extract structured company info from scraped text."""
    client = get_anthropic_client()

    prompt = f"""以下はウェブサイト（{url}）から取得したテキストです。
ここから会社情報を抽出してJSON形式で返してください。

取得テキスト:
{scraped_text}

以下のJSON形式で返してください（見つからない項目は空文字""にする）:
{{
  "company_name": "正式な会社名",
  "company_name_kana": "会社名の読み仮名（カタカナ）",
  "representative": "代表者名",
  "location": "本社所在地",
  "founded": "設立年月",
  "capital": "資本金",
  "url": "会社のURL",
  "company_description": "会社の事業内容を2〜3文で要約",
  "contact_email": "問い合わせメールアドレス",
  "contact_phone": "電話番号"
}}

JSONのみを返してください。説明文は不要です。"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    # Extract JSON from response
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        return json.loads(json_match.group())
    return {}


# -- AI press release generation --

def generate_press_release_ai(
    release_type: str,
    common: dict,
    user_input: str,
) -> str:
    """Use Claude to generate a full press release from minimal input."""
    client = get_anthropic_client()

    # Build the format reference based on PR Times best practices
    format_guide = _get_format_guide(release_type, common)

    prompt = f"""{format_guide}

---

以下の情報をもとに、PR Times向けのプレスリリースを作成してください。

【会社情報】
会社名: {common.get('company_name', '')}
読み仮名: {common.get('company_name_kana', '')}
代表者: {common.get('representative', '')}
所在地: {common.get('location', '')}
設立: {common.get('founded', '')}
資本金: {common.get('capital', '')}
会社URL: {common.get('url', '')}
会社説明: {common.get('company_description', '')}
問い合わせメール: {common.get('contact_email', '')}
担当者: {common.get('contact_person', '')}
電話: {common.get('contact_phone', '')}
リリース日: {common.get('release_date', datetime.now().strftime('%Y年%m月%d日'))}

【リリース種類】
{RELEASE_TYPES[release_type]}（{RELEASE_DESCRIPTIONS[release_type]}）

【ユーザーが入力した情報】
{user_input}

---

上記の情報をもとに、以下のルールに厳密に従ってプレスリリースを生成してください:

■ 全体構成（Markdown形式で出力）
プレスリリースのみを出力。説明や前置きは一切不要。

1. タイトル（# で記述）
2. サブタイトル（**太字**で記述）
3. 区切り線（---）
4. リード文（見出しなし、本文直書き）
5. 本文セクション群（## 見出しで構造化）
6. 代表コメント（## 見出し）
7. 今後の展望（## 見出し）
8. 区切り線（---）
9. 会社概要（## 見出し＋表形式）
10. お問い合わせ先（## 見出し）

■ タイトルのルール
- 結論を30文字以内で伝える1行目を作る。全体は最大80文字まで
- 重要キーワード（サービス名、金額、数値）を前半13文字以内に配置
- 数値を最低1つ含める（金額、人数、件数、パーセント等）
- 感嘆符・絵文字は禁止
- カテゴリに応じたタイトルパターンを使う:
  * 資金調達: 「社名、[ラウンド]で総額[金額]の資金調達を実施」（23〜30文字が理想）
  * サービス: 「[数値実績]の『サービス名』を提供開始」または「社名が、[概要]『サービス名』を提供開始」
  * 提携: 「社名、[提携先]と[提携種別]を締結」
  * イベント: 「【開催決定】『イベント名』[規模感数値][日程]」
  * アップデート: 「社名が、『サービス名』の大規模アップデートを実施」
  * 受賞: 「社名が『受賞名』を受賞」

■ サブタイトルのルール
- タイトルの補足情報を1〜2行で。以下のいずれかを記載:
  * 資金使途やビジョン（「〜を加速」「〜の実現に向け」）
  * 権威性（「〇〇と〇〇が登壇」「Apple子会社〇〇が〜」）
  * 読み仮名入りの会社説明

■ リード文のルール
- 250〜300字、最大400字以内
- 冒頭: 「[会社名]（本社：[所在地]、代表取締役：[代表者名]）は、」で始める
- 5W2Hを網羅: Who（誰が）What（何を）When（いつ）Where（どこで）Why（なぜ）How（どのように）How much（いくらで）
- 最後に「展望」を1文添える
- 専門用語を使わず、一般の読者にも伝わる表現にする

■ 本文のルール
- 結論先行の逆三角形構造（最重要情報→背景→詳細の順）
- 各セクションは ## 見出しで区切る
- 小見出し・箇条書きで視認性を高める。流し読みでも要点が把握できること
- 太字（**）で要点を強調（やりすぎない程度に）
- 特徴や機能は番号付き太字で3つ程度に整理（例: **1. 〇〇**）
- 社会的背景・トレンドとの接続を明示する（「なぜ今これが重要か」）
- 公的データや業界統計を引用して客観性を確保する（「〇〇省のデータによると〜」等）
- 数値は必ずアラビア数字で表記

■ 数値・データの使い方
- タイトルに最低1つの数値
- リード文に累計実績・規模を示す数値
- 本文中に具体的な数値を散りばめる（金額、人数、件数、パーセント、前年比等）
- 入力にある数値は必ず活用する。ない場合でも「〇〇を目指す」等の目標数値は含めない（捏造しない）
- 前年比・成長率で変化を可視化できる場合は積極的に使う

■ 代表コメントのルール
- 2〜3段落で簡潔に
- 個人的な熱意よりも事業の社会的意義を中心に
- 具体的な将来計画を含める
- 入力にコメントがあればそれを元に整える。なければ自然な内容を生成
- 「[会社名] 代表取締役 [氏名]」という肩書きを最初に記載

■ 会社概要のルール
- 表形式（Markdown table）で以下の項目を記載:
  会社名 / 代表者 / 所在地 / 設立 / 資本金 / URL / 事業内容
- 表の下に会社説明文を1〜2文で追加（入力があれば）

■ お問い合わせ先のルール
- 会社名、担当者名、メールアドレス、電話番号を記載

■ 文体
- です・ます調。フォーマルだが堅すぎない
- 広告的な表現は避ける。公式文書としての品位を保つ
- 感嘆符・絵文字・砕けた表現は使わない

■ 画像に関する注記
- 本文の末尾（お問い合わせ先の後）に「※ 本リリースに関する画像素材は[問い合わせ先]までご連絡ください」と1行追加"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text.strip()


def _get_format_guide(release_type: str, common: dict) -> str:
    """Return format guide based on PR Times best practices research (2026)."""
    company = common.get("company_name", "会社名")

    base = f"""あなたはPR Times向けプレスリリースの専門ライターです。
PR TIMESの公式ガイドラインと実際の高反響プレスリリース事例の分析に基づいて執筆してください。

【基本原則】
- メディア記者はプレスリリース1通あたり2〜3秒で記事候補かを判断する。ファーストビュー（タイトル＋冒頭文）が勝負
- タイトルはメディアがそのまま記事見出しにコピーできる簡潔さにする
- 逆三角形構造: タイトル→リード文→本文で情報量を段階的に増やす
- 1リリース1テーマに絞る。A4で1〜3枚が目安
- 公式文書としての品位を保つ。広告表現は避ける
- 公的データや第三者データを引用して客観性を確保する
- 社会的文脈（なぜ今このニュースが重要か）を必ず示す

【タイトル事例】
* 資金調達（23〜24文字が理想）:
  - 「EX-Fusion、シリーズAで総額約26億円の資金調達を実施」
  - 「Space Aviation、シリーズBで17.4億円の資金調達を実施」
* サービスリリース（数値＋サービス名＋動詞）:
  - 「多拠点型施設運営SaaS『knotPLACE』利用者5.5万人突破・サービスサイトのフルリニューアルを実施」
* 提携（両社名＋提携内容）:
  - 「アイレップとの業務提携に関するお知らせ 戦略からマーケティング施策実行まで、企業の課題解決に関する包括的なサービスを提供」
* イベント（【墨カッコ】＋規模感＋日程）:
  - 「【開催決定】THE SNS CONFERENCE 2025｜最前線の実践者たちが語る、"これからのSNSとの向き合い方"」

【サブタイトル事例】
- 資金使途: 「M&Aによる海外展開を推進」
- ビジョン: 「〜テクノロジーとサポートでクラウド時代のSaaS管理体制を構築〜」
- 権威性: 「清水建設、ライオン、デロイトトーマツ、NVIDIAなどが登壇」

【リード文事例】
「[会社名]（本社：[所在地]、代表取締役：[氏名]）は、[引受先]を引受先とする[ラウンド]にて、総額[金額]の資金調達を完了いたしました。調達資金は[使途]に活用し、[展望]を目指してまいります。」"""

    type_guides = {
        "service": f"""

【サービスリリースの本文構成】（実際の高反響事例に基づく）
## 「サービス名」とは（サービスの位置づけと概要を端的に）
## 提供開始の背景（社会課題・市場動向を公的データで裏付け）
## 主な機能・特徴（3つ程度に整理。番号付き太字で列挙、各項目を1〜2文で説明）
## 料金プラン/導入方法（あれば）
## 代表コメント
## 今後の展望
## 会社概要
## お問い合わせ先

【参考: ATOMica社事例の構成】
1. 「knotPLACE」とは？
2. 主な機能の紹介：施設運営に役立つ6つの特徴
3. 導入ステップ
→ 実績数値（121施設、5.5万人利用者）で成長性を訴求""",

        "partnership": f"""

【業務提携の本文構成】（PR TIMES公式テンプレート＋実際の高反響事例に基づく）
## 提携の背景（社会課題・市場動向。公的データを引用して提携の必然性を示す）
## 提携の目的と概要
## 各社の役割
## 期待される成果
## コメント（両社代表のコメント。第三者コメントがあればなお良い）
## 今後の展望
## 各社の会社概要
## お問い合わせ先

【参考: ユナイテッド×アイレップ事例】
- 「2025年以降最大12兆円/年の経済損失」（経済産業省データ引用）で社会課題を示す
- 提携の必然性・緊急性を訴求
- 提携イメージ図を掲載""",

        "funding": f"""

【資金調達の本文構成】（実際の高反響事例に基づく。タイトルは23〜30文字が理想）
## 資金調達の背景/目的
## 資金調達の内容（金額の内訳。エクイティ・融資の区分があれば記載）
## 出資企業一覧（箇条書きで。リードインベスターは明示）
## 投資家からのコメント（2〜3名。所属・役職を明記。第三者からの評価で信頼性を担保）
## 代表コメント
## 今後の事業展開
## 採用情報（あれば。資金調達後の成長フェーズとして自然）
## 会社概要
## お問い合わせ先

【参考: EX-Fusion事例（高評価）】
- タイトル24文字「EX-Fusion、シリーズAで総額約26億円の資金調達を実施」
- リード文136字で端的に事実を伝達
- 投資家3名のコメントで信頼性を担保
- 技術目標を数値化「1秒間に10回の核融合反応」
- 累計調達額56億円で規模感を示す
- 画像は代表者顔写真＋投資家顔写真を掲載（メディアが記事に使いやすい素材を提供）""",

        "event": f"""

【イベント開催の本文構成】（実際の高反響事例に基づく。画像を最も多く使うカテゴリ）
## 開催概要（開催の意義を1〜2段落で。前年実績があれば引用）
## イベント概要（表形式: イベント名/日時/会場/対象者/定員/参加費/申込URL）
## プログラム・セッション一覧
## 登壇者紹介（所属・役職を明記）
## 申込方法
## 主催者コメント
## 主催者情報/会社概要
## お問い合わせ先

【参考: AI Agent Day 2025事例（高評価）】
- タイトルに「国内最大級」「総勢41名」「30セッション」「3日間」と数値を集中投下
- サブタイトルで大手企業名を列挙（清水建設、ライオン、NVIDIA等）→権威性
- 申込数4,000名超を記載→注目度の裏付け
- 画像20枚（登壇者写真、タイムテーブル、メインビジュアル等）

【タイトルパターン】
- 【開催決定】や【参加者募集】の墨カッコで目を引く
- 日程は「7月9日(水)〜11日(金)」のように曜日入りで記載""",

        "update": f"""

【アップデートリリースの本文構成】
## アップデートの背景（ユーザーの声、市場変化、技術進化等）
## 主なアップデート内容（番号付き太字で3〜5項目。各項目を1〜2文で説明）
## ユーザーへのメリット（具体的な数値: 処理速度〇%向上、コスト〇%削減等）
## 「サービス名」について（サービスの全体像。導入企業数・利用者数等の実績）
## 代表コメント
## 今後の展望
## 会社概要
## お問い合わせ先""",

        "award": f"""

【受賞リリースの本文構成】
## 受賞の概要
## 受賞理由（審査基準に沿った記載。授与機関の説明も含む）
## 受賞対象となったサービス/取り組み（概要と実績数値）
## 受賞の意義（業界における位置づけ、社会的意義）
## 代表コメント
## 会社概要
## お問い合わせ先""",
    }

    return base + type_guides.get(release_type, "")


# ============================
# Save/Load history helpers
# ============================

def _init_session_history():
    """Initialize session-based history storage."""
    if "user_history" not in st.session_state:
        st.session_state["user_history"] = []


def save_to_history(release_type: str, result: str, common: dict) -> str:
    """Save generated press release to session history. Returns filename."""
    _init_session_history()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    title_line = ""
    for line in result.split("\n"):
        if line.strip().startswith("# "):
            title_line = line.strip()[2:][:40]
            break
    fname = f"{ts}_{release_type}"

    entry = {
        "timestamp": datetime.now().isoformat(),
        "release_type": release_type,
        "title": title_line,
        "company": common.get("company_name", ""),
        "markdown": result,
        "_filename": fname,
    }
    st.session_state["user_history"].insert(0, entry)
    return fname


def list_history() -> list[dict]:
    """List saved press releases from session, newest first."""
    _init_session_history()
    return st.session_state["user_history"]


def delete_history(filename: str):
    _init_session_history()
    st.session_state["user_history"] = [
        h for h in st.session_state["user_history"] if h.get("_filename") != filename
    ]


# ============================
# Streamlit UI
# ============================

st.set_page_config(
    page_title="プレスリリース自動生成",
    page_icon="PR",
    layout="wide",
)

# -- Inject global CSS at top (renders before content) --
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Noto+Sans+JP:wght@400;500;600;700&display=swap');

    :root {
        --primary: #783C28;
        --primary-hover: #8B4A34;
        --bg: #FAFAFA;
        --bg-card: #FFFFFF;
        --bg-sidebar: #F5F5F5;
        --border: #E5E5E5;
        --border-focus: #783C28;
        --text-primary: #1A1A1A;
        --text-secondary: #737373;
        --text-muted: #A3A3A3;
        --accent-green: #16A34A;
        --accent-red: #DC2626;
        --radius-sm: 6px;
        --radius-md: 8px;
        --radius-lg: 12px;
    }

    .stApp {
        background-color: var(--bg) !important;
        font-family: 'Inter', 'Noto Sans JP', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }

    #MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; }

    /* -- Sidebar -- */
    section[data-testid="stSidebar"] {
        background-color: var(--bg-sidebar) !important;
        border-right: 1px solid var(--border);
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        font-size: 0.8125rem !important;
        font-weight: 600 !important;
        color: var(--text-secondary) !important;
        text-transform: uppercase !important;
        letter-spacing: 0.05em !important;
    }

    /* -- Typography -- */
    h1 {
        color: var(--text-primary) !important;
        font-weight: 700 !important;
        letter-spacing: -0.03em !important;
        font-size: 1.75rem !important;
    }
    h2 {
        color: var(--text-primary) !important;
        font-weight: 600 !important;
        font-size: 1.1rem !important;
        letter-spacing: -0.01em !important;
    }
    h3 {
        color: var(--text-secondary) !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
    }

    /* -- Form Inputs (Linear-style) -- */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea {
        border: 1px solid var(--border) !important;
        border-radius: var(--radius-md) !important;
        padding: 10px 14px !important;
        font-size: 0.875rem !important;
        font-family: 'Inter', 'Noto Sans JP', sans-serif !important;
        color: var(--text-primary) !important;
        background: var(--bg-card) !important;
        transition: all 0.15s ease !important;
    }
    .stTextInput > div > div > input:focus,
    .stTextArea > div > div > textarea:focus {
        border-color: var(--border-focus) !important;
        box-shadow: 0 0 0 3px rgba(120, 60, 40, 0.06) !important;
    }
    .stTextInput label, .stTextArea label, .stSelectbox label {
        font-size: 0.8125rem !important;
        font-weight: 500 !important;
        color: var(--text-secondary) !important;
    }

    /* -- Select boxes -- */
    .stSelectbox > div > div {
        border: 1px solid var(--border) !important;
        border-radius: var(--radius-md) !important;
        background: var(--bg-card) !important;
    }

    /* -- Buttons (Vercel-style) -- */
    div[data-testid="stButton"] button[kind="primary"] {
        background-color: var(--text-primary) !important;
        border: 1px solid var(--text-primary) !important;
        border-radius: var(--radius-md) !important;
        color: white !important;
        font-weight: 500 !important;
        font-size: 0.875rem !important;
        font-family: 'Inter', 'Noto Sans JP', sans-serif !important;
        transition: all 0.15s ease !important;
        padding: 8px 20px !important;
    }
    div[data-testid="stButton"] button[kind="primary"]:hover {
        background-color: #333 !important;
        border-color: #333 !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.1) !important;
    }
    div[data-testid="stButton"] button:not([kind="primary"]) {
        background-color: var(--bg-card) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius-md) !important;
        color: var(--text-primary) !important;
        font-weight: 500 !important;
        font-size: 0.875rem !important;
        transition: all 0.15s ease !important;
    }
    div[data-testid="stButton"] button:not([kind="primary"]):hover {
        border-color: #CCC !important;
        background-color: var(--bg) !important;
    }

    /* -- Tabs (Linear-style minimal) -- */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        border-bottom: 1px solid var(--border);
        background: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 10px 20px;
        font-weight: 500;
        font-size: 0.875rem;
        color: var(--text-muted);
        border-bottom: 2px solid transparent;
        background: transparent !important;
    }
    .stTabs [aria-selected="true"] {
        border-bottom-color: var(--text-primary) !important;
        color: var(--text-primary) !important;
        font-weight: 600;
    }

    /* -- Expander -- */
    .streamlit-expanderHeader {
        font-weight: 500 !important;
        font-size: 0.875rem !important;
        color: var(--text-secondary) !important;
    }

    /* -- Dividers -- */
    hr { border-color: var(--border) !important; opacity: 0.5; }

    /* -- Download buttons -- */
    .stDownloadButton button {
        border-radius: var(--radius-md) !important;
        border: 1px solid var(--border) !important;
        font-weight: 500 !important;
        font-size: 0.8125rem !important;
    }

    /* -- Radio -- */
    .stRadio > div { gap: 2px; }
    .stRadio label { font-size: 0.8125rem !important; }

    /* -- Alerts -- */
    .stAlert { border-radius: var(--radius-md) !important; }

    /* -- Spacing tweaks -- */
    .stTextInput, .stTextArea { margin-bottom: -8px !important; }
    .stTextArea > div > div > textarea { min-height: 72px !important; }

    /* -- Placeholder -- */
    .stTextInput > div > div > input::placeholder,
    .stTextArea > div > div > textarea::placeholder {
        color: #C4C4C4 !important;
        font-size: 0.8125rem !important;
    }

    /* -- Tab panel padding -- */
    .stTabs [data-baseweb="tab-panel"] { padding-top: 24px !important; }

    /* -- Company info 2-col -- */
    [data-testid="stHorizontalBlock"] {
        gap: 16px !important;
    }

    /* -- Better scrollbar -- */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-thumb { background: #D4D4D4; border-radius: 3px; }
    ::-webkit-scrollbar-track { background: transparent; }
</style>
""", unsafe_allow_html=True)

# -- Usage counter --
if "generation_count" not in st.session_state:
    st.session_state["generation_count"] = 0

# -- Sidebar (compact, Linear-style) --
with st.sidebar:
    st.markdown("""
    <div style="padding: 4px 0 12px 0;">
        <span style="font-size: 1rem; font-weight: 700; color: #1A1A1A; letter-spacing: -0.02em;">
            PR Generator
        </span>
        <span style="font-size: 0.7rem; color: #A3A3A3; margin-left: 6px;">PR Times最適化</span>
    </div>
    """, unsafe_allow_html=True)

    st.header("PROFILE")
    profiles = list_profiles()
    profile_choice = st.selectbox(
        "会社プロフィール",
        ["（新規入力）"] + profiles,
        key="profile_select",
        label_visibility="collapsed",
    )
    if profile_choice != "（新規入力）" and profile_choice in profiles:
        loaded = load_profile(profile_choice)
    else:
        loaded = None

    st.header("RELEASE TYPE")
    release_type = st.radio(
        "種類",
        list(RELEASE_TYPES.keys()),
        format_func=lambda x: f"{RELEASE_TYPES[x]}",
        key="release_type",
        label_visibility="collapsed",
    )

    st.divider()

    st.header("COMPANY URL")
    company_url_input = st.text_input(
        "URL",
        placeholder="https://example.com",
        key="scrape_url",
        label_visibility="collapsed",
    )
    if st.button("会社情報を取得", use_container_width=True):
        if company_url_input:
            with st.spinner("取得中..."):
                scraped = scrape_company_info(company_url_input)
            if scraped["success"]:
                with st.spinner("AI解析中..."):
                    try:
                        extracted_data = extract_company_with_ai(scraped["text"], company_url_input)
                    except Exception as e:
                        extracted_data = None
                        st.error(f"{e}")
                if extracted_data:
                    st.session_state["extracted_company"] = extracted_data
                    st.rerun()
            else:
                st.error("取得失敗")

    st.divider()

    # History section
    st.header("HISTORY")
    history = list_history()
    if history:
        for item in history[:8]:
            title_short = (item.get("title", "無題"))[:25]
            date_str = item.get("timestamp", "")[:10]
            if st.button(f"{date_str}  {title_short}", key=f"hist_{item['_filename']}", use_container_width=True):
                st.session_state["press_release_result"] = item["markdown"]
                st.session_state["loaded_from_history"] = True
                st.rerun()
    else:
        st.caption("保存済みのリリースはありません")

    st.divider()
    remaining = MAX_GENERATIONS_PER_SESSION - st.session_state.get("generation_count", 0)
    st.caption(f"残り {remaining}/{MAX_GENERATIONS_PER_SESSION} 回")

# -- Determine initial values (priority: extracted > loaded > empty) --
extracted = st.session_state.get("extracted_company", {})


def val(key: str, default: str = "") -> str:
    """Get value with priority: extracted > loaded > default."""
    if extracted.get(key):
        return extracted[key]
    if loaded and loaded.get(key):
        return loaded[key]
    return default


# -- Main area --
st.markdown("""
<div style="margin: 8px 0 28px 0;">
    <h1 style="margin-bottom: 6px; font-size: 1.5rem;">プレスリリース自動生成</h1>
    <p style="color: #737373; font-size: 0.8125rem; margin: 0; display: flex; gap: 16px; flex-wrap: wrap;">
        <span style="display: inline-flex; align-items: center; gap: 4px;">
            <span style="width: 6px; height: 6px; border-radius: 50%; background: #16A34A; display: inline-block;"></span>
            AI自動生成
        </span>
        <span style="display: inline-flex; align-items: center; gap: 4px;">
            <span style="width: 6px; height: 6px; border-radius: 50%; background: #783C28; display: inline-block;"></span>
            PR Times最適化
        </span>
        <span style="display: inline-flex; align-items: center; gap: 4px;">
            <span style="width: 6px; height: 6px; border-radius: 50%; background: #2563EB; display: inline-block;"></span>
            PDF / Markdown出力
        </span>
    </p>
</div>
""", unsafe_allow_html=True)

tab_input, tab_company, tab_history = st.tabs(["作成", "会社情報", "保存履歴"])

with tab_company:
    st.header("会社情報")
    st.caption("URLから自動取得するか、手動で入力してください。プロフィールとして保存すると次回以降は入力不要です。")

    col1, col2 = st.columns(2)
    with col1:
        company_name = st.text_input("会社名（正式名称） *", value=val("company_name"))
        representative = st.text_input("代表者名 *", value=val("representative"))
        founded = st.text_input("設立年月", value=val("founded"))
        company_url = st.text_input("会社URL *", value=val("url"))
        contact_email = st.text_input("お問い合わせメール *", value=val("contact_email"))

    with col2:
        company_name_kana = st.text_input("会社名（読み仮名）", value=val("company_name_kana"))
        location = st.text_input("本社所在地 *", value=val("location"))
        capital = st.text_input("資本金", value=val("capital"))
        contact_person = st.text_input("担当者名 *", value=val("contact_person"))
        contact_phone = st.text_input("電話番号", value=val("contact_phone"))

    company_description = st.text_area(
        "会社説明文",
        value=val("company_description"),
        height=80,
        help="空欄の場合、AIが会社URLの情報から自動生成します",
    )

    release_date = st.text_input(
        "リリース日",
        value=val("release_date", datetime.now().strftime("%Y年%m月%d日")),
    )

    # Save profile
    col_s1, col_s2, col_s3 = st.columns([2, 1, 1])
    with col_s1:
        profile_save_name = st.text_input(
            "プロフィール保存名",
            value=profile_choice if loaded else "",
        )
    with col_s2:
        st.write("")
        st.write("")
        if st.button("プロフィール保存", use_container_width=True):
            if profile_save_name and company_name:
                save_profile(
                    {
                        "company_name": company_name,
                        "company_name_kana": company_name_kana,
                        "representative": representative,
                        "location": location,
                        "founded": founded,
                        "capital": capital,
                        "url": company_url,
                        "company_description": company_description,
                        "contact_email": contact_email,
                        "contact_person": contact_person,
                        "contact_phone": contact_phone,
                        "release_date": release_date,
                    },
                    profile_save_name,
                )
                st.success(f"「{profile_save_name}」を保存しました")
                st.rerun()
    with col_s3:
        st.write("")
        st.write("")
        if extracted:
            if st.button("取得データをクリア", use_container_width=True):
                del st.session_state["extracted_company"]
                st.rerun()


with tab_input:
    st.header(f"{RELEASE_TYPES[release_type]}の情報")

    # -- Notion import section (only if server has API key) --
    notion_key = os.environ.get("NOTION_API_KEY", "")
    if notion_key:
        with st.expander("Notionページから読み込む", expanded=False):
            st.caption("NotionページURLを貼り付けると、内容を自動で解析してフォームに反映します。")

            notion_url = st.text_input(
                "NotionページURL",
                placeholder="https://www.notion.so/Your-Page-abc123...",
                key="notion_url",
            )

            def _run_notion_analysis(page_data: dict):
                """Notionデータを解析し、会社情報も自動取得する。"""
                title = page_data["title"]
                content = page_data["content"]
                st.success(f"{title} を読み取りました（{len(content)}文字）")

                with st.spinner("AIで内容を解析中..."):
                    try:
                        result = analyze_notion_full(title, content, release_type)
                    except Exception as e:
                        st.error(f"AI解析エラー: {e}")
                        return

                if not result:
                    st.error("解析結果を取得できませんでした")
                    return

                st.session_state["notion_analyzed"] = {
                    "analyzed_text": result.get("release_info", ""),
                    "raw_content": content,
                    "title": title,
                }
                st.session_state["_notion_fresh"] = True

                company_info = result.get("company", {})
                company_url_detected = company_info.get("company_url", "")

                # Only fetch company info if not already set
                existing_company = st.session_state.get("extracted_company", {})
                has_company = existing_company.get("company_name") and existing_company.get("representative")
                if company_url_detected and not has_company:
                    with st.spinner("会社情報を自動取得中..."):
                        try:
                            scraped = scrape_company_info(company_url_detected)
                            if scraped["success"]:
                                extracted = extract_company_with_ai(scraped["text"], company_url_detected)
                                if extracted:
                                    st.session_state["extracted_company"] = extracted
                            else:
                                st.session_state["extracted_company"] = {
                                    "company_name": company_info.get("company_name", ""),
                                    "url": company_url_detected,
                                }
                        except Exception:
                            st.session_state["extracted_company"] = {
                                "company_name": company_info.get("company_name", ""),
                                "url": company_url_detected,
                            }

                suggested = result.get("release_type_suggestion", "")
                if suggested and suggested != release_type:
                    st.info(f"AIの提案: 「{RELEASE_TYPES.get(suggested, suggested)}」が最適です。サイドバーで変更できます。")

                st.rerun()

            if st.button("Notionから読み込む", type="primary", use_container_width=True):
                if notion_url:
                    with st.spinner("Notionページを読み取り中..."):
                        try:
                            page_data = read_notion_page(notion_url, notion_key)
                        except Exception as e:
                            page_data = None
                            st.error(f"Notion読み取りエラー: {e}")
                    if page_data and page_data.get("content"):
                        _run_notion_analysis(page_data)
                    elif page_data:
                        st.warning("ページの内容が空です。")

    # Show Notion analysis result
    notion_data = st.session_state.get("notion_analyzed")
    notion_prefill = ""
    if notion_data:
        st.success(f"Notionページ「{notion_data.get('title', '')}」の内容を解析済み。会社情報も自動取得しました。")
        notion_prefill = notion_data.get("analyzed_text", "")
        with st.expander("元データを確認（AI解析結果）", expanded=False):
            st.text(notion_prefill)
        if st.button("Notion解析データをクリア", key="clear_notion"):
            del st.session_state["notion_analyzed"]
            if "extracted_company" in st.session_state:
                del st.session_state["extracted_company"]
            # Clear all possible form field keys
            for prefix in ["svc_", "ptr_", "fund_", "evt_", "upd_", "awd_"]:
                for k in list(st.session_state.keys()):
                    if k.startswith(prefix):
                        del st.session_state[k]
            st.rerun()

    st.divider()

    # -- Parse notion_prefill into field values --
    def _parse_all_fields(text: str) -> dict:
        """Parse 'key: value' formatted text into a dict. Handles multiline values."""
        result = {}
        if not text:
            return result
        lines = text.split("\n")
        current_key = None
        current_val = []
        for line in lines:
            # Check if this line starts a new "key: value" pair
            if ":" in line and not line.startswith(" ") and not line.startswith("-") and not line.startswith("　"):
                # Save previous key
                if current_key:
                    val = "\n".join(current_val).strip()
                    if val and val != "（情報なし）":
                        result[current_key] = val
                parts = line.split(":", 1)
                current_key = parts[0].strip()
                current_val = [parts[1].strip()] if len(parts) > 1 else []
            elif current_key:
                current_val.append(line)
        # Save last key
        if current_key:
            val = "\n".join(current_val).strip()
            if val and val != "（情報なし）":
                result[current_key] = val
        return result

    _notion_fields = _parse_all_fields(notion_prefill)

    def _nv(key: str) -> str:
        """Get Notion-parsed value. Tries exact match first, then partial match."""
        if not _notion_fields:
            return ""
        if key in _notion_fields:
            return _notion_fields[key]
        for k, v in _notion_fields.items():
            if key in k or k in key:
                return v
        return ""

    # -- Structured input fields per release type --
    FIELD_DEFS = {
        "service": [
            ("サービス名", "svc_name", "text", "例: SaaSプロダクト名"),
            ("サービスURL", "svc_url", "text", "例: https://example.com/service"),
            ("ターゲット", "svc_target", "text", "例: 大企業の研究開発部門"),
            ("価格", "svc_price", "text", "例: 月額10,000円〜"),
            ("数値データ", "svc_numbers", "text", "例: 23.5万人のDB、99.7%のコスト削減"),
            ("提供開始日", "svc_launch", "text", "例: 2026年4月1日"),
            ("サービス概要", "svc_summary", "area", "何ができるサービスか、1〜2文で"),
            ("背景・課題", "svc_bg", "area", "なぜ今これが必要か。箇条書きでもOK"),
            ("主な特徴", "svc_features", "area", "3つ程度、箇条書きで"),
            ("差別化ポイント", "svc_diff", "area", "競合との違い、数値があれば"),
            ("代表コメント", "svc_comment", "area", ""),
            ("今後の展望", "svc_future", "area", ""),
        ],
        "partnership": [
            ("提携先企業名", "ptr_name", "text", ""),
            ("提携の種類", "ptr_type", "text", "例: 業務提携、共同研究"),
            ("提携の目的・背景", "ptr_purpose", "area", ""),
            ("提携内容の詳細", "ptr_detail", "area", ""),
            ("期待される成果", "ptr_outcome", "area", ""),
            ("代表コメント", "ptr_comment", "area", ""),
            ("提携先コメント", "ptr_partner_comment", "area", ""),
            ("今後の展望", "ptr_future", "area", ""),
        ],
        "funding": [
            ("ラウンド", "fund_round", "text", "例: シード、シリーズA"),
            ("調達金額", "fund_amount", "text", "例: 1億円"),
            ("リードインベスター", "fund_lead", "text", ""),
            ("調達日", "fund_date", "text", "例: 2026年4月"),
            ("投資家", "fund_investors", "area", "1行1社で"),
            ("資金使途", "fund_purpose", "area", ""),
            ("事業概要", "fund_biz", "area", "現在の事業内容・実績"),
            ("市場背景", "fund_market", "area", ""),
            ("代表コメント", "fund_comment", "area", ""),
            ("今後の戦略", "fund_future", "area", ""),
        ],
        "event": [
            ("イベント名", "evt_name", "text", ""),
            ("開催日時", "evt_date", "text", ""),
            ("開催場所", "evt_venue", "text", ""),
            ("対象者", "evt_target", "text", ""),
            ("定員", "evt_capacity", "text", ""),
            ("参加費", "evt_price", "text", ""),
            ("申込URL", "evt_url", "text", ""),
            ("主催者", "evt_organizer", "text", ""),
            ("イベント概要", "evt_summary", "area", ""),
            ("プログラム・登壇者", "evt_program", "area", ""),
        ],
        "update": [
            ("サービス名", "upd_name", "text", ""),
            ("サービスURL", "upd_url", "text", ""),
            ("アップデート概要", "upd_summary", "text", ""),
            ("主な変更点", "upd_details", "area", "箇条書きで"),
            ("背景", "upd_bg", "area", ""),
            ("ユーザーへのメリット", "upd_impact", "area", ""),
            ("代表コメント", "upd_comment", "area", ""),
            ("今後の展望", "upd_future", "area", ""),
        ],
        "award": [
            ("受賞名", "awd_name", "text", ""),
            ("授与機関", "awd_body", "text", ""),
            ("受賞日", "awd_date", "text", ""),
            ("受賞理由", "awd_reason", "area", ""),
            ("対象サービス概要", "awd_service", "area", ""),
            ("受賞の意義", "awd_significance", "area", ""),
            ("代表コメント", "awd_comment", "area", ""),
        ],
    }

    fields = FIELD_DEFS.get(release_type, [])
    field_values = {}

    # Pre-populate session state from Notion data BEFORE widgets render
    # Streamlit ignores `value=` if the key already exists in session_state
    # So we write directly to session_state when fresh Notion data arrives
    if _notion_fields and st.session_state.pop("_notion_fresh", False):
        for label, key, field_type, placeholder in fields:
            notion_val = _nv(label)
            st.session_state[key] = notion_val  # overwrite even if empty

    # Render fields in 2-column layout for text inputs, full-width for text areas
    text_fields = [(l, k, t, p) for l, k, t, p in fields if t == "text"]
    area_fields = [(l, k, t, p) for l, k, t, p in fields if t == "area"]

    # Text inputs in 2 columns
    if text_fields:
        for i in range(0, len(text_fields), 2):
            cols = st.columns(2)
            for j, col in enumerate(cols):
                idx = i + j
                if idx < len(text_fields):
                    label, key, _, placeholder = text_fields[idx]
                    with col:
                        field_values[label] = st.text_input(label, key=key, placeholder=placeholder)

    # Text areas full-width
    if area_fields:
        for label, key, _, placeholder in area_fields:
            field_values[label] = st.text_area(label, key=key, height=80, placeholder=placeholder)

    # Build user_input from field values
    user_input_parts = []
    for label, val in field_values.items():
        if val.strip():
            user_input_parts.append(f"{label}: {val}")
    user_input = "\n".join(user_input_parts)

    can_generate = bool(user_input.strip())

    # Also check if Notion analyzed data is available as fallback input
    if not can_generate and st.session_state.get("notion_analyzed"):
        can_generate = True

    # -- Generate button --
    st.divider()

    common = {
        "company_name": company_name,
        "company_name_kana": company_name_kana,
        "representative": representative,
        "location": location,
        "founded": founded,
        "capital": capital,
        "url": company_url,
        "company_description": company_description,
        "contact_email": contact_email,
        "contact_person": contact_person,
        "contact_phone": contact_phone,
        "release_date": release_date,
    }

    missing_company = not all([company_name, representative, location])
    # Also check session state for extracted company data
    if missing_company and st.session_state.get("extracted_company"):
        ec = st.session_state["extracted_company"]
        if ec.get("company_name") and ec.get("representative") and ec.get("location"):
            missing_company = False
    if missing_company:
        st.warning("会社情報タブで会社名・代表者名・所在地を入力するか、URLから自動取得してください。")

    # Load past press release references if available
    REFERENCES_FILE = Path(__file__).parent / "past_releases.json"
    past_releases_context = ""
    if REFERENCES_FILE.exists():
        try:
            past = json.loads(REFERENCES_FILE.read_text())
            # Find matching release type examples
            matching = [r for r in past if r.get("type") == release_type]
            if not matching:
                matching = past[:2]  # fallback to first 2
            for ref in matching[:2]:
                past_releases_context += f"\n\n【参考: 過去のプレスリリース「{ref.get('title', '')}」】\n{ref.get('body', '')[:2000]}"
        except Exception:
            pass

    usage_ok = _check_usage_limit()
    if not usage_ok:
        st.error(f"セッションあたりの生成回数上限（{MAX_GENERATIONS_PER_SESSION}回）に達しました。ページを再読み込みするとリセットされます。")

    col_gen1, col_gen2 = st.columns([1, 1])
    with col_gen1:
        generate_clicked = st.button(
            "プレスリリースを生成",
            type="primary",
            use_container_width=True,
            disabled=(not can_generate or missing_company or not usage_ok),
        )
    with col_gen2:
        if "press_release_result" in st.session_state:
            regenerate_clicked = st.button(
                "再生成",
                use_container_width=True,
                disabled=(not can_generate or missing_company or not usage_ok),
            )
        else:
            regenerate_clicked = False

    if generate_clicked or regenerate_clicked:
        _increment_usage()
        full_input = user_input
        if past_releases_context:
            full_input += past_releases_context
        with st.spinner("AIがプレスリリースを生成中..."):
            result = generate_press_release_ai(release_type, common, full_input)
            st.session_state["press_release_result"] = result

    # -- Display result --
    if "press_release_result" in st.session_state:
        result = st.session_state["press_release_result"]

        st.divider()

        # Action bar
        col_dl1, col_dl2, col_dl3, col_dl4 = st.columns(4)
        with col_dl1:
            try:
                pdf_data = generate_pdf(result)
                st.download_button("PDF", data=pdf_data,
                    file_name=f"press_release_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf", use_container_width=True, type="primary")
            except Exception:
                st.button("PDF (error)", disabled=True, use_container_width=True)
        with col_dl2:
            st.download_button("Markdown", data=result,
                file_name=f"press_release_{datetime.now().strftime('%Y%m%d')}.md",
                mime="text/markdown", use_container_width=True)
        with col_dl3:
            plain = result.replace("# ", "").replace("## ", "").replace("**", "").replace("---", "").replace("|", " ")
            st.download_button("Text", data=plain,
                file_name=f"press_release_{datetime.now().strftime('%Y%m%d')}.txt",
                mime="text/plain", use_container_width=True)
        with col_dl4:
            if st.button("Save", use_container_width=True, key="save_btn"):
                save_to_history(release_type, result, common)
                st.success("保存しました")
                st.rerun()

        view_mode = st.radio(
            "表示モード",
            ["プレビュー", "Markdown", "プレーンテキスト"],
            horizontal=True,
            key="view_mode",
        )


        if view_mode == "プレビュー":
            st.markdown("""
            <style>
            .pr-preview {
                font-family: 'Noto Sans JP', 'Inter', -apple-system, sans-serif;
                max-width: 760px;
                margin: 24px auto;
                padding: 48px 52px;
                background: #FFFFFF;
                border: 1px solid #E5E5E5;
                border-radius: 12px;
                line-height: 1.85;
                color: #1A1A1A;
                box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 16px rgba(0,0,0,0.04);
            }
            .pr-preview h1 {
                font-size: 1.4rem; font-weight: 700; color: #1A1A1A;
                border-bottom: 2px solid #1A1A1A;
                padding-bottom: 14px; margin-bottom: 8px;
                line-height: 1.5; letter-spacing: -0.02em;
            }
            .pr-preview h2 {
                font-size: 1rem; font-weight: 600; color: #1A1A1A;
                margin-top: 36px; margin-bottom: 12px;
                padding-bottom: 6px; border-bottom: 1px solid #E5E5E5;
            }
            .pr-preview p { margin-bottom: 16px; font-size: 0.9rem; line-height: 1.85; }
            .pr-preview strong { font-weight: 600; }
            .pr-preview hr { border: none; border-top: 1px solid #E5E5E5; margin: 32px 0; }
            .pr-preview table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 0.85rem; }
            .pr-preview th, .pr-preview td { border: 1px solid #E5E5E5; padding: 10px 14px; text-align: left; }
            .pr-preview th { background: #F5F5F5; font-weight: 600; width: 100px; font-size: 0.8rem; }
            .pr-preview ul, .pr-preview ol { padding-left: 20px; margin-bottom: 16px; }
            .pr-preview li { margin-bottom: 4px; font-size: 0.9rem; }
            .pr-preview blockquote {
                border-left: 3px solid #E5E5E5; padding: 14px 24px; margin: 20px 0;
                background: #FAFAFA; color: #404040; border-radius: 0 6px 6px 0; font-size: 0.9rem;
            }
            .pr-badge {
                display: inline-block; background: #1A1A1A; color: #FFF;
                font-size: 0.625rem; padding: 3px 12px; border-radius: 3px;
                margin-bottom: 20px; letter-spacing: 0.2em; font-weight: 600; text-transform: uppercase;
            }
            </style>
            """, unsafe_allow_html=True)

            html_body = md_lib.markdown(result, extensions=["tables", "fenced_code"])
            st.markdown(
                f'<div class="pr-preview">'
                f'<span class="pr-badge">PRESS RELEASE</span>'
                f'{html_body}'
                f'</div>',
                unsafe_allow_html=True,
            )
        elif view_mode == "Markdown":
            st.code(result, language="markdown")
        else:
            plain = result.replace("# ", "").replace("## ", "").replace("**", "").replace("---", "").replace("|", " ")
            st.code(plain, language=None)

        st.caption("PR Timesへの入稿時: 画像を3〜5枚以上準備してください")

# -- History tab --
with tab_history:
    st.markdown("#### 保存済みプレスリリース")
    history_items = list_history()
    if not history_items:
        st.info("保存済みのプレスリリースはありません。生成後に「Save」ボタンで保存できます。")
    else:
        for item in history_items:
            with st.container(border=True):
                col_h1, col_h2, col_h3 = st.columns([4, 1, 1])
                with col_h1:
                    st.markdown(f"**{item.get('title', '無題')[:50]}**")
                    st.caption(f"{item.get('timestamp', '')[:16]}  |  {RELEASE_TYPES.get(item.get('release_type', ''), '')}  |  {item.get('company', '')}")
                with col_h2:
                    if st.button("開く", key=f"open_{item['_filename']}", use_container_width=True):
                        st.session_state["press_release_result"] = item["markdown"]
                        st.rerun()
                with col_h3:
                    if st.button("削除", key=f"del_{item['_filename']}", use_container_width=True):
                        delete_history(item["_filename"])
                        st.rerun()

# -- Footer --
st.markdown("""
<div style="text-align: center; padding: 32px 0 16px 0; border-top: 1px solid #E5E5E5; margin-top: 40px;">
    <p style="color: #A3A3A3; font-size: 0.75rem; margin: 0;">
        PR Times Press Release Generator  |  Powered by Claude AI
    </p>
    <p style="color: #C4C4C4; font-size: 0.65rem; margin: 6px 0 0 0;">
        AIによる自動生成です。内容は必ず確認・修正のうえご利用ください。
    </p>
</div>
""", unsafe_allow_html=True)
