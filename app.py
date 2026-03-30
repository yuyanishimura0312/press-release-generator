"""
Press Release Generator - Streamlit Web App
AI-powered, PR Times optimized, esse-sense format based

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

# -- Config --
PROFILE_DIR = Path(__file__).parent / "profiles"
PROFILE_DIR.mkdir(exist_ok=True)
ENV_FILE = Path(__file__).parent / ".env"

# Load .env file if exists
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

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


# -- Profile helpers --

def list_profiles() -> list[str]:
    return [p.stem for p in PROFILE_DIR.glob("*.json")]


def load_profile(name: str) -> dict:
    path = PROFILE_DIR / f"{name}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_profile(data: dict, name: str):
    path = PROFILE_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
    """Get Anthropic client with API key from env, .env file, or session state."""
    api_key = os.environ.get("ANTHROPIC_API_KEY") or st.session_state.get("api_key")
    if not api_key:
        raise ValueError("APIキーが設定されていません")
    return anthropic.Anthropic(api_key=api_key)


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

    # Build the esse-sense format reference
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
PR TIMESの公式ガイドラインと実際の高反響プレスリリース事例を分析した結果に基づいて執筆してください。

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
# Streamlit UI
# ============================

st.set_page_config(
    page_title="PR Times プレスリリース生成",
    page_icon="PR",
    layout="wide",
)

st.title("PR Times プレスリリース自動生成")
st.caption("AI自動生成 / esse-sense形式ベース / 最小入力で完成度の高いプレスリリースを作成")

# -- Sidebar --
with st.sidebar:
    # API Key setup
    has_env_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if has_env_key:
        st.success("APIキー: 設定済み")
    else:
        st.header("APIキー設定")
        api_key_input = st.text_input(
            "Anthropic APIキー",
            type="password",
            value=st.session_state.get("api_key", ""),
            help="環境変数 ANTHROPIC_API_KEY またはプロジェクト内 .env ファイルでも設定可能",
        )
        if api_key_input:
            st.session_state["api_key"] = api_key_input
            # Save to .env for persistence
            ENV_FILE.write_text(f"ANTHROPIC_API_KEY={api_key_input}\n")
            os.environ["ANTHROPIC_API_KEY"] = api_key_input
        else:
            st.warning("AI機能を使うにはAPIキーが必要です")

    st.divider()
    st.header("会社プロフィール")

    profiles = list_profiles()
    profile_choice = st.selectbox(
        "保存済みプロフィール",
        ["（新規入力）"] + profiles,
        key="profile_select",
    )

    if profile_choice != "（新規入力）" and profile_choice in profiles:
        loaded = load_profile(profile_choice)
        st.success(f"「{profile_choice}」を読み込みました")
    else:
        loaded = None

    st.divider()

    # URL-based company info extraction
    st.header("会社情報をURLから取得")
    company_url_input = st.text_input(
        "会社URLを入力",
        placeholder="https://example.com",
        key="scrape_url",
    )
    if st.button("URLから自動取得", use_container_width=True):
        if company_url_input:
            if not os.environ.get("ANTHROPIC_API_KEY") and not st.session_state.get("api_key"):
                st.error("先にAPIキーを設定してください")
            else:
                with st.spinner("ウェブサイトを読み取り中..."):
                    scraped = scrape_company_info(company_url_input)
                if scraped["success"]:
                    with st.spinner("AIで会社情報を抽出中..."):
                        try:
                            extracted = extract_company_with_ai(scraped["text"], company_url_input)
                        except Exception as e:
                            extracted = None
                            st.error(f"AI抽出エラー: {e}")
                    if extracted:
                        st.session_state["extracted_company"] = extracted
                        st.success("会社情報を取得しました")
                        st.rerun()
                    elif not extracted:
                        st.error("会社情報の抽出に失敗しました")
                else:
                    st.error(f"取得エラー: {scraped['error']}")

    st.divider()
    st.header("リリース種類")
    release_type = st.radio(
        "種類を選択",
        list(RELEASE_TYPES.keys()),
        format_func=lambda x: f"{RELEASE_TYPES[x]}",
        key="release_type",
    )
    st.caption(RELEASE_DESCRIPTIONS[release_type])

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
tab_input, tab_company = st.tabs(["リリース内容", "会社情報"])

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

    # -- Notion import section --
    with st.expander("Notionページから読み込む", expanded=False):
        st.caption("NotionページのURLを貼り付けると、ページ内容を自動で読み取り・解析してフォームに反映します。")

        notion_key = os.environ.get("NOTION_API_KEY", "")
        NOTION_CONTENT_FILE = Path(__file__).parent / "notion_content.json"
        FETCH_SCRIPT = Path(__file__).parent / "fetch_notion.sh"

        # Method selection
        if notion_key:
            fetch_method = "api"
        else:
            fetch_method = "cli"

        notion_url = st.text_input(
            "NotionページURL",
            placeholder="https://www.notion.so/Your-Page-abc123...",
            key="notion_url",
        )

        def _run_notion_analysis(page_data: dict):
            """Notionデータを解析し、会社情報も自動取得する共通処理。"""
            title = page_data["title"]
            content = page_data["content"]
            st.success(f"「{title}」を読み取りました（{len(content)}文字）")

            with st.spinner("AIで内容を解析中...（会社特定＋リリース情報抽出）"):
                try:
                    result = analyze_notion_full(title, content, release_type)
                except Exception as e:
                    st.error(f"AI解析エラー: {e}")
                    return

            if not result:
                st.error("解析結果を取得できませんでした")
                return

            # Save release info
            st.session_state["notion_analyzed"] = {
                "analyzed_text": result.get("release_info", ""),
                "raw_content": content,
                "title": title,
            }
            # Flag to force-update form fields on next render
            st.session_state["_notion_fresh"] = True

            # Auto-detect company and scrape website
            company_info = result.get("company", {})
            company_url_detected = company_info.get("company_url", "")

            if company_url_detected:
                with st.spinner(f"会社情報を自動取得中... ({company_url_detected})"):
                    try:
                        scraped = scrape_company_info(company_url_detected)
                        if scraped["success"]:
                            extracted = extract_company_with_ai(scraped["text"], company_url_detected)
                            if extracted:
                                st.session_state["extracted_company"] = extracted
                        else:
                            # Scraping failed, use AI-detected info as fallback
                            st.session_state["extracted_company"] = {
                                "company_name": company_info.get("company_name", ""),
                                "url": company_url_detected,
                            }
                    except Exception:
                        st.session_state["extracted_company"] = {
                            "company_name": company_info.get("company_name", ""),
                            "url": company_url_detected,
                        }
            elif company_info.get("company_name"):
                # No URL but have company name - try web search
                search_name = company_info["company_name"]
                with st.spinner(f"「{search_name}」のウェブサイトを検索中..."):
                    try:
                        scraped = scrape_company_info(f"https://www.google.com/search?q={search_name}+会社概要")
                        if scraped["success"]:
                            # Extract URL from search results
                            client = get_anthropic_client()
                            resp = client.messages.create(
                                model="claude-sonnet-4-20250514",
                                max_tokens=200,
                                messages=[{"role": "user", "content": f"以下の検索結果から「{search_name}」の公式ウェブサイトURLを1つだけ返してください。URLのみ返してください。\n\n{scraped['text'][:3000]}"}],
                            )
                            found_url = resp.content[0].text.strip()
                            if found_url.startswith("http"):
                                scraped2 = scrape_company_info(found_url)
                                if scraped2["success"]:
                                    extracted = extract_company_with_ai(scraped2["text"], found_url)
                                    if extracted:
                                        st.session_state["extracted_company"] = extracted
                    except Exception:
                        st.session_state["extracted_company"] = {
                            "company_name": search_name,
                        }

            # Suggest release type
            suggested = result.get("release_type_suggestion", "")
            if suggested and suggested != release_type:
                st.info(f"AIの提案: このNotionの内容は「{RELEASE_TYPES.get(suggested, suggested)}」に最適です。サイドバーで変更できます。")

            st.rerun()

        # -- Fetch buttons --
        if fetch_method == "api":
            if st.button("Notionから自動読み込み", type="primary", use_container_width=True):
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
                        st.warning("ページの内容が空です。インテグレーションがページに接続されているか確認してください。")
        else:
            col_fetch1, col_fetch2 = st.columns([2, 1])
            with col_fetch1:
                if st.button("Notionから読み込む（CLI経由）", use_container_width=True):
                    if notion_url:
                        with st.spinner("Claude CLI経由でNotionページを読み取り中...（30〜60秒）"):
                            import subprocess
                            try:
                                sub_result = subprocess.run(
                                    [str(FETCH_SCRIPT), notion_url],
                                    capture_output=True, text=True, timeout=120,
                                    cwd=str(Path(__file__).parent),
                                )
                                if NOTION_CONTENT_FILE.exists():
                                    page_data = json.loads(NOTION_CONTENT_FILE.read_text())
                                    if page_data.get("content"):
                                        _run_notion_analysis(page_data)
                                    else:
                                        st.warning("ページの内容が空です")
                                else:
                                    st.error(f"読み取りに失敗しました\n{sub_result.stderr}")
                            except subprocess.TimeoutExpired:
                                st.error("タイムアウトしました。もう一度お試しください。")
                            except Exception as e:
                                st.error(f"エラー: {e}")
            with col_fetch2:
                if NOTION_CONTENT_FILE.exists():
                    if st.button("前回のデータを使用", use_container_width=True):
                        page_data = json.loads(NOTION_CONTENT_FILE.read_text())
                        if page_data.get("content"):
                            _run_notion_analysis(page_data)

            st.caption("Notion APIキーが未設定のため、Claude CLIのMCP接続を利用します。")

            with st.popover("Notion APIキーを設定（高速化）"):
                st.caption(
                    "APIキーを設定すると直接APIアクセスで高速になります。\n\n"
                    "1. [Notion Integrations](https://www.notion.so/profile/integrations) でインテグレーション作成\n"
                    "2. 対象ページで「コネクト」から追加\n"
                    "3. トークンを入力"
                )
                notion_key_input = st.text_input("Notion APIキー", type="password", key="notion_key_input")
                if notion_key_input:
                    env_content = ENV_FILE.read_text() if ENV_FILE.exists() else ""
                    if "NOTION_API_KEY" not in env_content:
                        env_content += f"\nNOTION_API_KEY={notion_key_input}\n"
                    else:
                        env_content = re.sub(r'NOTION_API_KEY=.*', f'NOTION_API_KEY={notion_key_input}', env_content)
                    ENV_FILE.write_text(env_content)
                    os.environ["NOTION_API_KEY"] = notion_key_input
                    st.success("保存しました。ページを再読み込みしてください。")

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
            ("サービス名", "svc_name", "text", "例: ANSWER法人版"),
            ("サービスURL", "svc_url", "text", "例: https://answer.esse-sense.com"),
            ("ターゲット", "svc_target", "text", "例: 大企業の研究開発部門"),
            ("サービス概要", "svc_summary", "area", "何ができるサービスか、1〜2文で"),
            ("背景・課題", "svc_bg", "area", "なぜ今これが必要か。箇条書きでもOK"),
            ("主な特徴", "svc_features", "area", "3つ程度、箇条書きで"),
            ("差別化ポイント", "svc_diff", "area", "競合との違い、数値があれば"),
            ("数値データ", "svc_numbers", "text", "例: 23.5万人のデータベース、99.7%のコスト削減"),
            ("価格", "svc_price", "text", ""),
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
            ("投資家", "fund_investors", "area", "1行1社で"),
            ("リードインベスター", "fund_lead", "text", ""),
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
            ("イベント概要", "evt_summary", "area", ""),
            ("プログラム・登壇者", "evt_program", "area", ""),
            ("定員", "evt_capacity", "text", ""),
            ("参加費", "evt_price", "text", ""),
            ("申込URL", "evt_url", "text", ""),
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

    for label, key, field_type, placeholder in fields:
        if field_type == "text":
            field_values[label] = st.text_input(label, key=key, placeholder=placeholder)
        else:
            field_values[label] = st.text_area(label, key=key, height=80, placeholder=placeholder)

    # Build user_input from field values
    user_input_parts = []
    for label, val in field_values.items():
        if val.strip():
            user_input_parts.append(f"{label}: {val}")
    user_input = "\n".join(user_input_parts)

    can_generate = bool(user_input.strip())

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
    if missing_company:
        st.warning("サイドバーでプロフィール「esse-sense」を選択するか、会社情報タブで入力してください。")

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

    col_gen1, col_gen2 = st.columns([1, 1])
    with col_gen1:
        generate_clicked = st.button(
            "プレスリリースを生成",
            type="primary",
            use_container_width=True,
            disabled=(not can_generate or missing_company),
        )
    with col_gen2:
        if "press_release_result" in st.session_state:
            regenerate_clicked = st.button(
                "再生成",
                use_container_width=True,
                disabled=(not can_generate or missing_company),
            )
        else:
            regenerate_clicked = False

    if generate_clicked or regenerate_clicked:
        # Append past release references to user input for AI context
        full_input = user_input
        if past_releases_context:
            full_input += past_releases_context
        with st.spinner("AIがプレスリリースを生成中..."):
            result = generate_press_release_ai(release_type, common, full_input)
            st.session_state["press_release_result"] = result

    # -- Display result with styled preview --
    if "press_release_result" in st.session_state:
        result = st.session_state["press_release_result"]

        st.divider()

        view_mode = st.radio(
            "表示モード",
            ["プレビュー", "Markdown", "プレーンテキスト"],
            horizontal=True,
            key="view_mode",
        )

        if view_mode == "プレビュー":
            # Styled preview with esse-sense / Miratsuku design tone
            st.markdown("""
            <style>
            .pr-preview {
                font-family: 'Noto Sans JP', 'Inter', -apple-system, sans-serif;
                max-width: 780px;
                margin: 0 auto;
                padding: 52px 56px;
                background: #FFFFFF;
                border: 1px solid #E8E2DC;
                border-radius: 12px;
                line-height: 1.9;
                color: #1A1A1A;
                box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 6px 24px rgba(120, 60, 40, 0.06);
            }
            .pr-preview h1 {
                font-size: 1.45rem;
                font-weight: 700;
                color: #1A1A1A;
                border-bottom: 2px solid #783C28;
                padding-bottom: 16px;
                margin-bottom: 8px;
                line-height: 1.55;
                letter-spacing: -0.01em;
            }
            .pr-preview h2 {
                font-size: 1.05rem;
                font-weight: 600;
                color: #783C28;
                margin-top: 40px;
                margin-bottom: 14px;
                padding-left: 16px;
                border-left: 3px solid #D3836F;
                letter-spacing: 0.01em;
            }
            .pr-preview p {
                margin-bottom: 18px;
                text-align: justify;
                color: #333;
                font-size: 0.95rem;
            }
            .pr-preview strong {
                color: #1A1A1A;
                font-weight: 600;
            }
            .pr-preview hr {
                border: none;
                border-top: 1px solid #F0EBE5;
                margin: 40px 0;
            }
            .pr-preview table {
                width: 100%;
                border-collapse: collapse;
                margin: 20px 0;
                font-size: 0.875rem;
                border-radius: 8px;
                overflow: hidden;
            }
            .pr-preview th, .pr-preview td {
                border: 1px solid #E8E2DC;
                padding: 11px 16px;
                text-align: left;
            }
            .pr-preview th {
                background: #F7F2ED;
                font-weight: 600;
                color: #783C28;
                width: 110px;
                font-size: 0.8125rem;
            }
            .pr-preview td {
                background: #FFFFFF;
            }
            .pr-preview ul, .pr-preview ol {
                padding-left: 24px;
                margin-bottom: 18px;
            }
            .pr-preview li {
                margin-bottom: 6px;
                font-size: 0.95rem;
                color: #333;
            }
            .pr-preview blockquote {
                border-left: 3px solid #D3836F;
                padding: 18px 28px;
                margin: 24px 0;
                background: #FDFAF7;
                color: #4a4a4a;
                font-style: normal;
                border-radius: 0 8px 8px 0;
                font-size: 0.95rem;
            }
            .pr-label {
                display: inline-block;
                background: #783C28;
                color: #FDFAF7;
                font-size: 0.6875rem;
                padding: 4px 16px;
                border-radius: 4px;
                margin-bottom: 24px;
                letter-spacing: 0.18em;
                font-weight: 600;
                text-transform: uppercase;
            }
            </style>
            """, unsafe_allow_html=True)

            # Convert markdown to styled HTML
            import markdown
            html_body = markdown.markdown(
                result,
                extensions=["tables", "fenced_code"],
            )
            st.markdown(
                f'<div class="pr-preview">'
                f'<span class="pr-label">PRESS RELEASE</span>'
                f'{html_body}'
                f'</div>',
                unsafe_allow_html=True,
            )
        elif view_mode == "Markdown":
            st.code(result, language="markdown")
        else:
            plain = result.replace("# ", "").replace("## ", "").replace("**", "").replace("---", "").replace("|", " ")
            st.code(plain, language=None)

        st.divider()
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                label="Markdownでダウンロード",
                data=result,
                file_name=f"press_release_{release_type}_{datetime.now().strftime('%Y%m%d')}.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with col_dl2:
            plain = result.replace("# ", "").replace("## ", "").replace("**", "").replace("---", "").replace("|", " ")
            st.download_button(
                label="プレーンテキストでダウンロード",
                data=plain,
                file_name=f"press_release_{release_type}_{datetime.now().strftime('%Y%m%d')}.txt",
                mime="text/plain",
                use_container_width=True,
            )

        st.caption("PR Timesへの入稿時: 画像を3〜5枚以上準備してください（トップ画像はSNSサムネイルに使用されます）")

# -- Footer --
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Noto+Sans+JP:wght@400;500;600;700&display=swap');

    /* -- Global -- */
    .stApp {
        background-color: #FDFAF7 !important;
        font-family: 'Inter', 'Noto Sans JP', -apple-system, sans-serif !important;
    }
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }

    /* -- Sidebar -- */
    section[data-testid="stSidebar"] {
        background-color: #F7F2ED !important;
        border-right: 1px solid #E8E2DC;
    }

    /* -- Typography -- */
    h1 { color: #1A1A1A !important; font-weight: 700 !important; letter-spacing: -0.02em; }
    h2, h3 { color: #783C28 !important; font-weight: 600 !important; }

    /* -- Form Inputs -- */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea {
        border: 1px solid #E8E2DC !important;
        border-radius: 8px !important;
        padding: 10px 14px !important;
        font-size: 0.9375rem !important;
        font-family: 'Inter', 'Noto Sans JP', sans-serif !important;
        color: #1A1A1A !important;
        background: #FFFFFF !important;
        transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
    }
    .stTextInput > div > div > input:focus,
    .stTextArea > div > div > textarea:focus {
        border-color: #A0503C !important;
        box-shadow: 0 0 0 3px rgba(120, 60, 40, 0.08) !important;
        outline: none !important;
    }
    .stTextInput label, .stTextArea label, .stSelectbox label {
        font-size: 0.875rem !important;
        font-weight: 500 !important;
        color: #6B6560 !important;
    }

    /* -- Select boxes -- */
    .stSelectbox > div > div {
        border: 1px solid #E8E2DC !important;
        border-radius: 8px !important;
        background: #FFFFFF !important;
    }

    /* -- Buttons -- */
    div[data-testid="stButton"] button[kind="primary"] {
        background-color: #783C28 !important;
        border: 1px solid #783C28 !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-family: 'Inter', 'Noto Sans JP', sans-serif !important;
        transition: all 0.15s ease !important;
        box-shadow: 0 1px 2px rgba(120, 60, 40, 0.08) !important;
    }
    div[data-testid="stButton"] button[kind="primary"]:hover {
        background-color: #8B4A34 !important;
        border-color: #8B4A34 !important;
        box-shadow: 0 2px 8px rgba(120, 60, 40, 0.15) !important;
        transform: translateY(-1px);
    }
    div[data-testid="stButton"] button:not([kind="primary"]) {
        background-color: #FFFFFF !important;
        border: 1px solid #E8E2DC !important;
        border-radius: 8px !important;
        color: #6B6560 !important;
        font-weight: 500 !important;
        transition: all 0.15s ease !important;
    }
    div[data-testid="stButton"] button:not([kind="primary"]):hover {
        border-color: #D4CFC8 !important;
        background-color: #F7F2ED !important;
    }

    /* -- Tabs -- */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        border-bottom: 1px solid #E8E2DC;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 10px 24px;
        font-weight: 500;
        color: #9C9590;
        border-bottom: 2px solid transparent;
    }
    .stTabs [aria-selected="true"] {
        border-bottom-color: #783C28 !important;
        color: #783C28 !important;
        font-weight: 600;
    }

    /* -- Expander -- */
    .streamlit-expanderHeader {
        font-weight: 500 !important;
        color: #6B6560 !important;
    }

    /* -- Dividers -- */
    hr {
        border-color: #F0EBE5 !important;
    }

    /* -- Download buttons -- */
    .stDownloadButton button {
        border-radius: 8px !important;
        border: 1px solid #E8E2DC !important;
        font-weight: 500 !important;
    }

    /* -- Radio -- */
    .stRadio > div { gap: 4px; }
    .stRadio label { font-size: 0.875rem !important; }
</style>
""", unsafe_allow_html=True)
st.divider()
st.caption("PR Times Press Release Generator | esse-sense format | Powered by Claude AI")
