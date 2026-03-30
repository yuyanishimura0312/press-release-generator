"""
Press Release Generator - Streamlit Web App
PR Times optimized, esse-sense format based
"""

import json
import streamlit as st
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


def delete_profile(name: str):
    path = PROFILE_DIR / f"{name}.json"
    if path.exists():
        path.unlink()


# -- Boilerplate generator --

def _company_boilerplate(c: dict) -> str:
    kana = f"（{c['company_name_kana']}）" if c.get("company_name_kana") else ""

    bp = "\n\n---\n\n## 会社概要\n\n"
    bp += "| 項目 | 詳細 |\n|------|------|\n"
    bp += f"| 会社名 | {c['company_name']}{kana} |\n"
    bp += f"| 代表者 | {c['representative']} |\n"
    bp += f"| 所在地 | {c['location']} |\n"
    if c.get("founded"):
        bp += f"| 設立 | {c['founded']} |\n"
    if c.get("capital"):
        bp += f"| 資本金 | {c['capital']} |\n"
    bp += f"| URL | {c['url']} |\n"

    if c.get("company_description"):
        bp += f"\n{c['company_description']}\n"

    bp += (
        f"\n## 本件に関するお問い合わせ先\n\n"
        f"{c['company_name']}\n"
        f"担当：{c['contact_person']}\n"
        f"メール：{c['contact_email']}\n"
    )
    if c.get("contact_phone"):
        bp += f"電話：{c['contact_phone']}\n"

    return bp


# -- Release generators --

def generate_service(c: dict, s: dict) -> str:
    company = c["company_name"]
    kana = f"（{c['company_name_kana']}）" if c.get("company_name_kana") else ""

    title = f"{company}が、{s['service_summary']}「{s['service_name']}」を提供開始"
    subtitle = (
        f"{company}{kana}が、{s['target_audience']}向けに"
        f"「{s['service_name']}」の提供を{c['release_date']}より開始"
    )
    lead = (
        f"{company}（本社：{c['location']}、代表取締役：{c['representative']}）は、"
        f"{c['release_date']}より、{s['service_summary']}「{s['service_name']}」の"
        f"提供を開始いたします。"
    )
    if s.get("service_url"):
        lead += f"\n{s['service_name']}：{s['service_url']}"

    body = f"# {title}\n\n**{subtitle}**\n\n---\n\n{lead}"

    if s.get("background"):
        body += f"\n\n## 背景\n\n{s['background']}"

    features = [f.strip() for f in s.get("features", "").strip().split("\n") if f.strip()]
    if features:
        body += f"\n\n## 「{s['service_name']}」の主な特徴\n\n"
        for i, feat in enumerate(features, 1):
            feat = feat.lstrip("・-– ")
            body += f"**{i}. {feat}**\n\n"

    if s.get("differentiation"):
        body += f"\n\n## 他にはない強み\n\n{s['differentiation']}"
    if s.get("price"):
        body += f"\n\n## 料金\n\n{s['price']}"
    if s.get("ceo_comment"):
        body += (
            f"\n\n## 代表コメント\n\n"
            f"{company} 代表取締役 {c['representative']}\n\n"
            f"「{s['ceo_comment']}」"
        )
    if s.get("future_plan"):
        body += f"\n\n## 今後の展望\n\n{s['future_plan']}"

    return body + _company_boilerplate(c)


def generate_partnership(c: dict, s: dict) -> str:
    company = c["company_name"]
    kana = f"（{c['company_name_kana']}）" if c.get("company_name_kana") else ""
    purpose_first = s["partnership_purpose"].split("\n")[0]

    title = f"{company}が、{s['partner_name']}と{s['partnership_type']}を締結"
    subtitle = f"{company}{kana}と{s['partner_name']}が{s['partnership_type']}を締結し、{purpose_first}"
    lead = (
        f"{company}（本社：{c['location']}、代表取締役：{c['representative']}）は、"
        f"{s['partner_name']}と{s['partnership_type']}を締結いたしました。"
        f"本提携により、{purpose_first}を推進してまいります。"
    )

    body = (
        f"# {title}\n\n**{subtitle}**\n\n---\n\n{lead}\n\n"
        f"## 提携の背景・目的\n\n{s['partnership_purpose']}\n\n"
        f"## {s['partner_name']}について\n\n{s['partner_description']}\n\n"
        f"## 提携内容\n\n{s['partnership_content']}\n\n"
        f"## 期待される成果\n\n{s['expected_outcome']}"
    )

    if s.get("ceo_comment"):
        body += f"\n\n## {company} 代表コメント\n\n{company} 代表取締役 {c['representative']}\n\n「{s['ceo_comment']}」"
    if s.get("partner_comment"):
        body += f"\n\n## {s['partner_name']} コメント\n\n「{s['partner_comment']}」"
    if s.get("future_plan"):
        body += f"\n\n## 今後の展望\n\n{s['future_plan']}"

    return body + _company_boilerplate(c)


def generate_funding(c: dict, s: dict) -> str:
    company = c["company_name"]
    kana = f"（{c['company_name_kana']}）" if c.get("company_name_kana") else ""
    purpose_first = s["funding_purpose"].split("\n")[0]

    investors_list = [inv.strip() for inv in s["investors"].strip().split("\n") if inv.strip()]
    investors_str = "、".join(investors_list)

    title = f"{company}が、{s['round']}で総額{s['amount']}の資金調達を完了"
    subtitle = f"{company}{kana}が{s['round']}ラウンドにて総額{s['amount']}の資金調達を実施。{purpose_first}を加速"
    lead = (
        f"{company}（本社：{c['location']}、代表取締役：{c['representative']}）は、"
        f"{investors_str}を引受先とする{s['round']}ラウンドにて、"
        f"総額{s['amount']}の資金調達を完了いたしました。"
    )
    if s.get("lead_investor"):
        lead += f"リードインベスターは{s['lead_investor']}です。"

    body = (
        f"# {title}\n\n**{subtitle}**\n\n---\n\n{lead}\n\n"
        f"## 事業概要\n\n{s['business_overview']}\n\n"
        f"## 市場背景・課題認識\n\n{s['market_background']}\n\n"
        f"## 資金使途\n\n{s['funding_purpose']}\n\n"
        f"## 引受先一覧\n\n"
    )
    for inv in investors_list:
        body += f"- {inv}\n"

    if s.get("ceo_comment"):
        body += f"\n## 代表コメント\n\n{company} 代表取締役 {c['representative']}\n\n「{s['ceo_comment']}」"
    if s.get("investor_comment"):
        body += f"\n\n## 投資家コメント\n\n「{s['investor_comment']}」"
    if s.get("future_plan"):
        body += f"\n\n## 今後の事業展開\n\n{s['future_plan']}"
    if s.get("hiring"):
        body += f"\n\n## 採用情報\n\n{s['hiring']}"

    return body + _company_boilerplate(c)


def generate_event(c: dict, s: dict) -> str:
    company = c["company_name"]
    kana = f"（{c['company_name_kana']}）" if c.get("company_name_kana") else ""

    title = f"{company}が、「{s['event_name']}」を{s['event_date']}に開催"
    subtitle = f"{company}{kana}が{s['target_audience']}を対象とした「{s['event_name']}」を開催"
    lead = (
        f"{company}（本社：{c['location']}、代表取締役：{c['representative']}）は、"
        f"{s['event_date']}に「{s['event_name']}」を{s['event_venue']}にて開催いたします。"
    )

    body = (
        f"# {title}\n\n**{subtitle}**\n\n---\n\n{lead}\n\n"
        f"## 開催背景・目的\n\n{s['event_background']}\n\n"
        f"## イベント概要\n\n{s['event_summary']}\n\n"
        f"| 項目 | 詳細 |\n|------|------|\n"
        f"| イベント名 | {s['event_name']} |\n"
        f"| 開催日時 | {s['event_date']} |\n"
        f"| 会場 | {s['event_venue']} |\n"
    )
    if s.get("capacity"):
        body += f"| 定員 | {s['capacity']} |\n"
    if s.get("price"):
        body += f"| 参加費 | {s['price']} |\n"
    if s.get("event_url"):
        body += f"| 申込URL | {s['event_url']} |\n"

    body += f"\n## プログラム・登壇者\n\n{s['event_program']}"

    if s.get("ceo_comment"):
        body += f"\n\n## 主催者コメント\n\n{company} 代表取締役 {c['representative']}\n\n「{s['ceo_comment']}」"

    return body + _company_boilerplate(c)


def generate_update(c: dict, s: dict) -> str:
    company = c["company_name"]
    kana = f"（{c['company_name_kana']}）" if c.get("company_name_kana") else ""

    title = f"{company}が、「{s['service_name']}」の大規模アップデート版を公開"
    subtitle = f"{company}{kana}が「{s['service_name']}」をアップデート。{s['update_summary']}"
    lead = (
        f"{company}（本社：{c['location']}、代表取締役：{c['representative']}）は、"
        f"{c['release_date']}より、{s['update_summary']}"
    )
    if s.get("service_url"):
        lead += f"\n{s['service_name']}：{s['service_url']}"

    body = f"# {title}\n\n**{subtitle}**\n\n---\n\n{lead}\n\n## 背景\n\n{s['background']}"

    updates = [u.strip() for u in s.get("update_details", "").strip().split("\n") if u.strip()]
    if updates:
        body += "\n\n## 主なアップデート内容\n\n"
        for i, item in enumerate(updates, 1):
            item = item.lstrip("・-– ")
            body += f"**{i}. {item}**\n\n"

    body += f"\n\n## ユーザーへのメリット\n\n{s['impact']}"

    if s.get("ceo_comment"):
        body += f"\n\n## 代表コメント\n\n{company} 代表取締役 {c['representative']}\n\n「{s['ceo_comment']}」"
    if s.get("future_plan"):
        body += f"\n\n## 今後の展望\n\n{s['future_plan']}"

    return body + _company_boilerplate(c)


def generate_award(c: dict, s: dict) -> str:
    company = c["company_name"]
    kana = f"（{c['company_name_kana']}）" if c.get("company_name_kana") else ""

    title = f"{company}が、「{s['award_name']}」を受賞"
    subtitle = f"{company}{kana}が{s['awarding_body']}による「{s['award_name']}」を受賞"
    lead = (
        f"{company}（本社：{c['location']}、代表取締役：{c['representative']}）は、"
        f"{s['award_date']}に{s['awarding_body']}より「{s['award_name']}」を受賞いたしました。"
    )

    body = (
        f"# {title}\n\n**{subtitle}**\n\n---\n\n{lead}\n\n"
        f"## 受賞理由\n\n{s['award_reason']}\n\n"
        f"## 対象サービス/取り組み概要\n\n{s['service_overview']}\n\n"
        f"## 受賞の意義\n\n{s['significance']}"
    )

    if s.get("ceo_comment"):
        body += f"\n\n## 代表コメント\n\n{company} 代表取締役 {c['representative']}\n\n「{s['ceo_comment']}」"

    return body + _company_boilerplate(c)


GENERATORS = {
    "service": generate_service,
    "partnership": generate_partnership,
    "funding": generate_funding,
    "event": generate_event,
    "update": generate_update,
    "award": generate_award,
}


# ============================
# Streamlit UI
# ============================

st.set_page_config(
    page_title="PR Times プレスリリース生成",
    page_icon="PR",
    layout="wide",
)

st.title("PR Times プレスリリース生成ツール")
st.caption("esse-sense形式ベース / PR Times最適化")

# -- Sidebar: Profile management --
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
    st.header("リリース種類")
    release_type = st.radio(
        "種類を選択",
        list(RELEASE_TYPES.keys()),
        format_func=lambda x: f"{RELEASE_TYPES[x]} - {RELEASE_DESCRIPTIONS[x]}",
        key="release_type",
    )

# -- Main: Two-column layout --
col_input, col_preview = st.columns([1, 1], gap="large")

with col_input:
    # === Company info section ===
    st.header("1. 会社情報")

    if loaded:
        st.info("プロフィールから読み込み済み。変更があれば上書きできます。")

    company_name = st.text_input("会社名（正式名称） *", value=loaded.get("company_name", "") if loaded else "")
    company_name_kana = st.text_input("会社名（読み仮名）", value=loaded.get("company_name_kana", "") if loaded else "")
    representative = st.text_input("代表者名 *", value=loaded.get("representative", "") if loaded else "")
    location = st.text_input("本社所在地 *", value=loaded.get("location", "") if loaded else "")

    col_a, col_b = st.columns(2)
    with col_a:
        founded = st.text_input("設立年月", value=loaded.get("founded", "") if loaded else "")
    with col_b:
        capital = st.text_input("資本金", value=loaded.get("capital", "") if loaded else "")

    company_url = st.text_input("会社URL *", value=loaded.get("url", "") if loaded else "")
    company_description = st.text_area(
        "会社説明文（1〜3文）",
        value=loaded.get("company_description", "") if loaded else "",
        height=80,
    )

    col_c, col_d = st.columns(2)
    with col_c:
        contact_email = st.text_input("お問い合わせメール *", value=loaded.get("contact_email", "") if loaded else "")
    with col_d:
        contact_person = st.text_input("担当者名 *", value=loaded.get("contact_person", "") if loaded else "")

    contact_phone = st.text_input("電話番号", value=loaded.get("contact_phone", "") if loaded else "")
    release_date = st.text_input(
        "リリース日",
        value=loaded.get("release_date", datetime.now().strftime("%Y年%m月%d日")) if loaded else datetime.now().strftime("%Y年%m月%d日"),
    )

    # Save profile button
    col_save1, col_save2 = st.columns([2, 1])
    with col_save1:
        profile_save_name = st.text_input("プロフィール保存名", value=profile_choice if loaded else "")
    with col_save2:
        st.write("")  # spacing
        st.write("")
        if st.button("保存", use_container_width=True):
            if profile_save_name and company_name:
                common_data = {
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
                save_profile(common_data, profile_save_name)
                st.success(f"「{profile_save_name}」を保存しました")
                st.rerun()

    st.divider()

    # === Release-specific info ===
    st.header(f"2. {RELEASE_TYPES[release_type]}の情報")

    specific = {}

    if release_type == "service":
        specific["service_name"] = st.text_input("サービス/プロダクト名 *")
        specific["service_url"] = st.text_input("サービスURL")
        specific["service_summary"] = st.text_input("サービス概要（何ができるか、1〜2文で） *")
        specific["target_audience"] = st.text_input("ターゲット（誰向けか） *")
        specific["background"] = st.text_area("背景・社会課題（なぜ必要か） *", height=120)
        specific["features"] = st.text_area("主な特徴・機能（1行1項目で3つ程度） *", height=100,
                                             help="改行で区切ってください")
        specific["differentiation"] = st.text_area("差別化ポイント（数値があれば）", height=100)
        specific["price"] = st.text_input("価格・料金体系")
        specific["ceo_comment"] = st.text_area("代表コメント", height=100)
        specific["future_plan"] = st.text_area("今後の展望", height=80)

    elif release_type == "partnership":
        specific["partner_name"] = st.text_input("提携先企業名 *")
        specific["partner_description"] = st.text_area("提携先企業の概要（1〜2文） *", height=80)
        specific["partnership_type"] = st.text_input("提携の種類（業務提携、共同研究等） *")
        specific["partnership_purpose"] = st.text_area("提携の目的・背景 *", height=120)
        specific["partnership_content"] = st.text_area("提携内容の詳細 *", height=120)
        specific["expected_outcome"] = st.text_area("期待される成果・効果 *", height=100)
        specific["ceo_comment"] = st.text_area("自社代表コメント", height=100)
        specific["partner_comment"] = st.text_area("提携先コメント", height=100)
        specific["future_plan"] = st.text_area("今後の展望", height=80)

    elif release_type == "funding":
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            specific["round"] = st.text_input("ラウンド（シード等） *")
        with col_f2:
            specific["amount"] = st.text_input("調達金額（例：1億円） *")
        specific["investors"] = st.text_area("投資家・引受先（1行1社） *", height=100)
        specific["lead_investor"] = st.text_input("リードインベスター")
        specific["funding_purpose"] = st.text_area("資金使途 *", height=100)
        specific["business_overview"] = st.text_area("事業概要（現在の事業内容・実績） *", height=120)
        specific["market_background"] = st.text_area("市場背景・課題認識 *", height=120)
        specific["future_plan"] = st.text_area("今後の事業展開・成長戦略 *", height=100)
        specific["ceo_comment"] = st.text_area("代表コメント", height=100)
        specific["investor_comment"] = st.text_area("投資家コメント", height=100)
        specific["hiring"] = st.text_input("採用情報（採用強化する場合）")

    elif release_type == "event":
        specific["event_name"] = st.text_input("イベント名 *")
        col_e1, col_e2 = st.columns(2)
        with col_e1:
            specific["event_date"] = st.text_input("開催日時 *")
        with col_e2:
            specific["event_venue"] = st.text_input("開催場所 *")
        specific["event_url"] = st.text_input("イベントURL/申込URL")
        specific["event_summary"] = st.text_area("イベント概要 *", height=80)
        specific["event_background"] = st.text_area("開催背景・目的 *", height=120)
        specific["event_program"] = st.text_area("プログラム・登壇者情報 *", height=120)
        specific["target_audience"] = st.text_input("対象者 *")
        col_e3, col_e4 = st.columns(2)
        with col_e3:
            specific["capacity"] = st.text_input("定員")
        with col_e4:
            specific["price"] = st.text_input("参加費")
        specific["ceo_comment"] = st.text_area("主催者コメント", height=100)

    elif release_type == "update":
        specific["service_name"] = st.text_input("サービス/プロダクト名 *")
        specific["service_url"] = st.text_input("サービスURL")
        specific["update_summary"] = st.text_input("アップデート概要 *")
        specific["update_details"] = st.text_area("主な変更点（1行1項目） *", height=100)
        specific["background"] = st.text_area("アップデートの背景 *", height=120)
        specific["impact"] = st.text_area("ユーザーへのメリット（数値があれば） *", height=100)
        specific["ceo_comment"] = st.text_area("代表コメント", height=100)
        specific["future_plan"] = st.text_area("今後の展望", height=80)

    elif release_type == "award":
        specific["award_name"] = st.text_input("受賞/認定名 *")
        specific["awarding_body"] = st.text_input("授与機関/主催者 *")
        specific["award_date"] = st.text_input("受賞/認定日 *")
        specific["award_reason"] = st.text_area("受賞/認定理由 *", height=120)
        specific["service_overview"] = st.text_area("対象サービス/取り組みの概要 *", height=120)
        specific["significance"] = st.text_area("受賞の意義・今後への影響 *", height=100)
        specific["ceo_comment"] = st.text_area("代表コメント", height=100)

# -- Right column: Preview --
with col_preview:
    st.header("プレビュー")

    # Build common dict from form values
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

    # Check required fields
    missing_common = not all([company_name, representative, location, company_url, contact_email, contact_person])

    # Check release-type-specific required fields
    required_fields = {
        "service": ["service_name", "service_summary", "target_audience", "background", "features"],
        "partnership": ["partner_name", "partner_description", "partnership_type", "partnership_purpose", "partnership_content", "expected_outcome"],
        "funding": ["round", "amount", "investors", "funding_purpose", "business_overview", "market_background", "future_plan"],
        "event": ["event_name", "event_date", "event_venue", "event_summary", "event_background", "event_program", "target_audience"],
        "update": ["service_name", "update_summary", "update_details", "background", "impact"],
        "award": ["award_name", "awarding_body", "award_date", "award_reason", "service_overview", "significance"],
    }

    missing_specific = not all(specific.get(f) for f in required_fields.get(release_type, []))

    if missing_common or missing_specific:
        st.warning("必須項目（*）を入力すると、プレビューが表示されます。")
        # Show what's missing
        if missing_common:
            missing = []
            if not company_name:
                missing.append("会社名")
            if not representative:
                missing.append("代表者名")
            if not location:
                missing.append("本社所在地")
            if not company_url:
                missing.append("会社URL")
            if not contact_email:
                missing.append("メール")
            if not contact_person:
                missing.append("担当者名")
            st.caption(f"会社情報の未入力: {', '.join(missing)}")
        if missing_specific:
            missing_s = [f for f in required_fields.get(release_type, []) if not specific.get(f)]
            st.caption(f"リリース情報の未入力: {', '.join(missing_s)}")
    else:
        # Generate press release
        generator = GENERATORS[release_type]
        result = generator(common, specific)

        # Render preview
        with st.container(border=True):
            st.markdown(result)

        st.divider()

        # Action buttons
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            st.download_button(
                label="Markdownでダウンロード",
                data=result,
                file_name=f"press_release_{release_type}_{datetime.now().strftime('%Y%m%d')}.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with col_btn2:
            # Plain text version for PR Times copy-paste
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
st.caption("PR Times プレスリリース生成ツール | esse-sense形式ベース | PR Timesガイドライン準拠")
