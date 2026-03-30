"""
Press Release Generator - Streamlit Web App
AI-powered, PR Times optimized, esse-sense format based

Minimal input -> AI auto-generates full press release
Company info auto-extracted from URL
"""

import json
import re
import streamlit as st
import requests
import anthropic
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path

# -- Config --
PROFILE_DIR = Path(__file__).parent / "profiles"
PROFILE_DIR.mkdir(exist_ok=True)

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


def extract_company_with_ai(scraped_text: str, url: str) -> dict:
    """Use Claude to extract structured company info from scraped text."""
    client = anthropic.Anthropic()

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
    client = anthropic.Anthropic()

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

上記の情報をもとに、以下のルールに従ってプレスリリースを生成してください:

1. Markdown形式で出力
2. 構成は必ず以下の順序:
   - タイトル（# で）: 「会社名が、〜を[提供開始/締結/完了/開催/公開/受賞]」の形式
   - サブタイトル（太字で）: タイトルの詳細補足
   - 区切り線（---）
   - リード文: 「会社名（本社：所在地、代表取締役：代表者名）は、日付より〜」で始める。5W2Hを含む
   - 背景・課題セクション
   - 詳細セクション（リリース種類に応じた内容）
   - 代表コメント（入力があれば。なければ自然な内容を生成）
   - 今後の展望
   - 区切り線（---）
   - 会社概要（表形式）
   - お問い合わせ先
3. 文体はフォーマルだが堅すぎない。です・ます調
4. 具体的な数値やデータを積極的に使う（入力にあればそれを活かす。なければ自然な表現で）
5. 社会的意義やニュースバリューを明確にする
6. 各セクションは見出し（## ）で区切る
7. プレスリリースのみを出力。説明や前置きは不要"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text.strip()


def _get_format_guide(release_type: str, common: dict) -> str:
    """Return format guide based on esse-sense's actual press releases."""
    company = common.get("company_name", "会社名")

    base = f"""あなたはPR Times向けプレスリリースの専門ライターです。
以下はesse-sense社（株式会社エッセンス）の実際のプレスリリースから抽出したフォーマットです。
このフォーマットに忠実に従ってください。

【esse-senseフォーマットの特徴】
- タイトル: 「{company}が、[具体的な内容]を[動詞]」の形
- サブタイトル: 読み仮名入り、タイトルの補足情報
- リード文: 会社名（本社：所在地、代表取締役：代表者名）は、[日付]より[内容]を[開始]いたします。
- 本文: 背景→特徴→差別化→コメント→展望の逆三角形構造
- 数値を多用してインパクトを出す
- 「◇」マークでポイントを強調することもある
- 会社概要は表形式で末尾に配置
- お問い合わせ先は会社概要の後"""

    type_guides = {
        "service": """
【サービスリリースの参考構成】
1. サービス名・URL・概要
2. 背景にある社会課題（数値データで裏付け）
3. サービスの特徴（3つ程度に整理、番号付き太字）
4. 差別化ポイント（「99.7%のコスト削減」等インパクトある数値）
5. 料金（あれば）
6. 代表コメント
7. 今後の展望""",
        "partnership": """
【提携リリースの参考構成】
1. 提携の種類と提携先
2. 提携の背景・目的
3. 提携先企業の概要
4. 提携内容の詳細
5. 期待される成果
6. 両社代表のコメント
7. 今後の展望""",
        "funding": """
【資金調達リリースの参考構成】
1. ラウンド・調達金額・引受先
2. 事業概要と実績
3. 市場背景・課題認識
4. 資金使途
5. 引受先一覧
6. 代表コメント・投資家コメント
7. 今後の事業展開
8. 採用情報（あれば）""",
        "event": """
【イベントリリースの参考構成】
1. イベント名・日時・会場
2. 開催背景・目的
3. イベント概要
4. 開催情報（表形式: 名称/日時/会場/定員/参加費/URL）
5. プログラム・登壇者
6. 主催者コメント""",
        "update": """
【アップデートリリースの参考構成】
1. サービス名・アップデート概要
2. アップデートの背景
3. 主な変更点（番号付き太字で列挙）
4. ユーザーへのメリット
5. 代表コメント
6. 今後の展望""",
        "award": """
【受賞リリースの参考構成】
1. 受賞/認定の名称・授与機関
2. 受賞理由
3. 対象サービス/取り組みの概要
4. 受賞の意義
5. 代表コメント""",
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
            with st.spinner("ウェブサイトを読み取り中..."):
                scraped = scrape_company_info(company_url_input)
            if scraped["success"]:
                with st.spinner("AIで会社情報を抽出中..."):
                    extracted = extract_company_with_ai(scraped["text"], company_url_input)
                if extracted:
                    st.session_state["extracted_company"] = extracted
                    st.success("会社情報を取得しました")
                    st.rerun()
                else:
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
    st.caption("簡潔に要点だけ入力してください。AIが自動的にプレスリリースの文体・構成に仕上げます。")

    # --- Release-type-specific minimal input ---
    if release_type == "service":
        st.subheader("基本情報")
        col_a, col_b = st.columns(2)
        with col_a:
            svc_name = st.text_input("サービス/プロダクト名 *", key="svc_name")
        with col_b:
            svc_url = st.text_input("サービスURL", key="svc_url")
        svc_target = st.text_input("ターゲット（誰向けか） *", key="svc_target",
                                    placeholder="例: 大企業の研究開発部門")
        svc_oneliner = st.text_input("一言で何ができるサービスか *", key="svc_oneliner",
                                      placeholder="例: AIを活用して最適な研究者を探索できるサービス")

        st.subheader("詳細（わかる範囲で）")
        svc_background = st.text_area("なぜ今これが必要か（背景・課題）", key="svc_bg", height=100,
                                       placeholder="箇条書きでもOK。AIが文章化します")
        svc_features = st.text_area("主な特徴・機能", key="svc_feat", height=100,
                                     placeholder="箇条書きで3つ程度")
        svc_numbers = st.text_input("アピールできる数値", key="svc_num",
                                     placeholder="例: 23万人のデータベース、99%のコスト削減")
        svc_price = st.text_input("価格・料金", key="svc_price")
        svc_extra = st.text_area("その他伝えたいこと", key="svc_extra", height=80)

        user_input = f"""サービス名: {svc_name}
サービスURL: {svc_url}
ターゲット: {svc_target}
サービス概要: {svc_oneliner}
背景・課題: {svc_background}
主な特徴: {svc_features}
数値データ: {svc_numbers}
価格: {svc_price}
その他: {svc_extra}"""
        can_generate = bool(svc_name and svc_target and svc_oneliner)

    elif release_type == "partnership":
        col_a, col_b = st.columns(2)
        with col_a:
            ptr_name = st.text_input("提携先企業名 *", key="ptr_name")
        with col_b:
            ptr_type = st.text_input("提携の種類 *", key="ptr_type",
                                      placeholder="例: 業務提携、共同研究")
        ptr_purpose = st.text_area("提携の目的（何を一緒にやるか） *", key="ptr_purpose", height=100)
        ptr_detail = st.text_area("具体的な内容", key="ptr_detail", height=100,
                                   placeholder="箇条書きでもOK")
        ptr_extra = st.text_area("その他（提携先の特徴、期待する効果など）", key="ptr_extra", height=80)

        user_input = f"""提携先: {ptr_name}
提携の種類: {ptr_type}
目的: {ptr_purpose}
具体的な内容: {ptr_detail}
その他: {ptr_extra}"""
        can_generate = bool(ptr_name and ptr_type and ptr_purpose)

    elif release_type == "funding":
        col_a, col_b = st.columns(2)
        with col_a:
            fund_round = st.text_input("ラウンド *", key="fund_round",
                                        placeholder="例: シード、プレシリーズA")
        with col_b:
            fund_amount = st.text_input("調達金額 *", key="fund_amount",
                                         placeholder="例: 1億円")
        fund_investors = st.text_area("投資家（1行1社） *", key="fund_inv", height=80)
        fund_purpose = st.text_area("資金の使い道 *", key="fund_purpose", height=100)
        fund_extra = st.text_area("その他（事業の実績、今後の戦略など）", key="fund_extra", height=100)

        user_input = f"""ラウンド: {fund_round}
調達金額: {fund_amount}
投資家: {fund_investors}
資金使途: {fund_purpose}
その他: {fund_extra}"""
        can_generate = bool(fund_round and fund_amount and fund_investors and fund_purpose)

    elif release_type == "event":
        evt_name = st.text_input("イベント名 *", key="evt_name")
        col_a, col_b = st.columns(2)
        with col_a:
            evt_date = st.text_input("開催日時 *", key="evt_date")
        with col_b:
            evt_venue = st.text_input("開催場所 *", key="evt_venue")
        evt_target = st.text_input("対象者 *", key="evt_target")
        evt_summary = st.text_area("イベント概要 *", key="evt_summary", height=100)
        evt_program = st.text_area("プログラム・登壇者", key="evt_prog", height=100,
                                    placeholder="箇条書きでOK")
        col_c, col_d = st.columns(2)
        with col_c:
            evt_capacity = st.text_input("定員", key="evt_cap")
        with col_d:
            evt_price = st.text_input("参加費", key="evt_price")
        evt_url = st.text_input("申込URL", key="evt_url")

        user_input = f"""イベント名: {evt_name}
日時: {evt_date}
会場: {evt_venue}
対象者: {evt_target}
概要: {evt_summary}
プログラム: {evt_program}
定員: {evt_capacity}
参加費: {evt_price}
申込URL: {evt_url}"""
        can_generate = bool(evt_name and evt_date and evt_venue and evt_summary)

    elif release_type == "update":
        col_a, col_b = st.columns(2)
        with col_a:
            upd_name = st.text_input("サービス/プロダクト名 *", key="upd_name")
        with col_b:
            upd_url = st.text_input("サービスURL", key="upd_url")
        upd_summary = st.text_input("アップデート概要（一言で） *", key="upd_summary")
        upd_details = st.text_area("主な変更点 *", key="upd_detail", height=100,
                                    placeholder="箇条書きで")
        upd_why = st.text_area("アップデートの背景", key="upd_why", height=80)
        upd_extra = st.text_area("その他", key="upd_extra", height=80)

        user_input = f"""サービス名: {upd_name}
サービスURL: {upd_url}
アップデート概要: {upd_summary}
変更点: {upd_details}
背景: {upd_why}
その他: {upd_extra}"""
        can_generate = bool(upd_name and upd_summary and upd_details)

    elif release_type == "award":
        awd_name = st.text_input("受賞/認定名 *", key="awd_name")
        awd_body = st.text_input("授与機関/主催者 *", key="awd_body")
        awd_date = st.text_input("受賞/認定日 *", key="awd_date")
        awd_reason = st.text_area("受賞理由 *", key="awd_reason", height=100)
        awd_extra = st.text_area("その他（対象サービス、意義など）", key="awd_extra", height=100)

        user_input = f"""受賞名: {awd_name}
授与機関: {awd_body}
受賞日: {awd_date}
受賞理由: {awd_reason}
その他: {awd_extra}"""
        can_generate = bool(awd_name and awd_body and awd_date and awd_reason)

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
        st.warning("会社情報タブで会社名・代表者名・所在地を入力してください。")

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
        with st.spinner("AIがプレスリリースを生成中...（20〜30秒）"):
            result = generate_press_release_ai(release_type, common, user_input)
            st.session_state["press_release_result"] = result

    # -- Display result --
    if "press_release_result" in st.session_state:
        result = st.session_state["press_release_result"]

        st.divider()
        st.header("生成結果")

        view_mode = st.radio(
            "表示モード",
            ["プレビュー", "Markdown", "プレーンテキスト"],
            horizontal=True,
            key="view_mode",
        )

        if view_mode == "プレビュー":
            with st.container(border=True):
                st.markdown(result)
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

        st.caption("PR Timesへの入稿時の注意: 画像を3〜5枚以上準備してください（トップ画像はSNSサムネイルに使用されます）")

# -- Footer --
st.divider()
st.caption("PR Times プレスリリース自動生成ツール | esse-sense形式ベース | Claude AI搭載")
