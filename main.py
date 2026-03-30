#!/usr/bin/env python3
"""
Press Release Generator - PR Times optimized
esse-sense format based auto-generation tool

Usage:
    python main.py                  # Interactive mode
    python main.py --type service   # Specify release type
    python main.py --output pr.md   # Output to file
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# -- Release type definitions --
RELEASE_TYPES = {
    "service": "サービスリリース（新規プロダクト・機能リリース）",
    "partnership": "提携・協業（業務提携、共同研究、MOU締結等）",
    "funding": "資金調達完了（シード、シリーズA等）",
    "event": "イベント開催（カンファレンス、セミナー等）",
    "update": "サービスアップデート（既存プロダクトの大幅改善）",
    "award": "受賞・認定（表彰、認証取得等）",
}


def get_input(prompt: str, required: bool = True, multiline: bool = False) -> str:
    """Get user input with optional multiline support."""
    print(f"\n{prompt}")
    if multiline:
        print("  (複数行入力可。空行で入力終了)")
        lines = []
        while True:
            line = input()
            if line == "":
                break
            lines.append(line)
        value = "\n".join(lines)
    else:
        value = input("  > ").strip()

    if required and not value:
        print("  ※ この項目は必須です。もう一度入力してください。")
        return get_input(prompt, required, multiline)
    return value


def get_choice(prompt: str, options: dict) -> str:
    """Get user choice from numbered options."""
    print(f"\n{prompt}")
    keys = list(options.keys())
    for i, (key, desc) in enumerate(options.items(), 1):
        print(f"  {i}. {desc}")
    while True:
        choice = input("  番号を入力 > ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(keys):
                return keys[idx]
        except ValueError:
            pass
        print("  ※ 有効な番号を入力してください。")


def collect_common_info() -> dict:
    """Collect information common to all release types."""
    info = {}
    info["company_name"] = get_input(
        "会社名（正式名称）:",
        required=True,
    )
    info["company_name_kana"] = get_input(
        "会社名（読み仮名、例：エッセンス）:",
        required=False,
    )
    info["representative"] = get_input("代表者名:")
    info["location"] = get_input("本社所在地:")
    info["founded"] = get_input("設立年月（例：2021年3月）:", required=False)
    info["capital"] = get_input("資本金（例：4,800万円）:", required=False)
    info["url"] = get_input("会社URL:")
    info["company_description"] = get_input(
        "会社説明文（1〜3文で、事業内容・ポジショニング）:",
        multiline=True,
    )
    info["contact_email"] = get_input("お問い合わせメールアドレス:")
    info["contact_person"] = get_input("お問い合わせ担当者名（カンマ区切り）:")
    info["contact_phone"] = get_input("電話番号:", required=False)
    info["release_date"] = get_input(
        f"リリース日（空欄で本日 {datetime.now().strftime('%Y年%m月%d日')}）:",
        required=False,
    ) or datetime.now().strftime("%Y年%m月%d日")
    return info


def collect_service_info() -> dict:
    """Collect service release specific information."""
    info = {}
    info["service_name"] = get_input("サービス/プロダクト名:")
    info["service_url"] = get_input("サービスURL:", required=False)
    info["service_summary"] = get_input(
        "サービス概要（何ができるか、1〜2文で）:",
    )
    info["target_audience"] = get_input("ターゲット（誰向けのサービスか）:")
    info["background"] = get_input(
        "背景・社会課題（なぜこのサービスが必要か）:",
        multiline=True,
    )
    info["features"] = get_input(
        "主な特徴・機能（1行1項目で3つ程度）:",
        multiline=True,
    )
    info["differentiation"] = get_input(
        "差別化ポイント（競合との違い、具体的な数値があれば）:",
        multiline=True,
    )
    info["future_plan"] = get_input(
        "今後の展望（任意）:",
        multiline=True,
        required=False,
    )
    info["ceo_comment"] = get_input(
        "代表コメント（任意）:",
        multiline=True,
        required=False,
    )
    info["price"] = get_input("価格・料金体系（任意）:", required=False)
    return info


def collect_partnership_info() -> dict:
    """Collect partnership release specific information."""
    info = {}
    info["partner_name"] = get_input("提携先企業名:")
    info["partner_description"] = get_input(
        "提携先企業の概要（1〜2文）:",
    )
    info["partnership_type"] = get_input(
        "提携の種類（業務提携、共同研究、資本業務提携等）:",
    )
    info["partnership_purpose"] = get_input(
        "提携の目的・背景:",
        multiline=True,
    )
    info["partnership_content"] = get_input(
        "提携内容の詳細（具体的に何をするか）:",
        multiline=True,
    )
    info["expected_outcome"] = get_input(
        "期待される成果・効果:",
        multiline=True,
    )
    info["future_plan"] = get_input(
        "今後の展望（任意）:",
        multiline=True,
        required=False,
    )
    info["ceo_comment"] = get_input(
        "自社代表コメント（任意）:",
        multiline=True,
        required=False,
    )
    info["partner_comment"] = get_input(
        "提携先代表コメント（任意）:",
        multiline=True,
        required=False,
    )
    return info


def collect_funding_info() -> dict:
    """Collect funding release specific information."""
    info = {}
    info["round"] = get_input("ラウンド（シード、プレシリーズA、シリーズA等）:")
    info["amount"] = get_input("調達金額（例：1億円）:")
    info["investors"] = get_input(
        "投資家・引受先（1行1社で）:",
        multiline=True,
    )
    info["lead_investor"] = get_input("リードインベスター:", required=False)
    info["funding_purpose"] = get_input(
        "資金使途（何に使うか）:",
        multiline=True,
    )
    info["business_overview"] = get_input(
        "事業概要（現在の事業内容・実績）:",
        multiline=True,
    )
    info["market_background"] = get_input(
        "市場背景・課題認識:",
        multiline=True,
    )
    info["future_plan"] = get_input(
        "今後の事業展開・成長戦略:",
        multiline=True,
    )
    info["ceo_comment"] = get_input(
        "代表コメント（任意）:",
        multiline=True,
        required=False,
    )
    info["investor_comment"] = get_input(
        "投資家コメント（任意）:",
        multiline=True,
        required=False,
    )
    info["hiring"] = get_input(
        "採用情報（任意、採用強化する場合）:",
        required=False,
    )
    return info


def collect_event_info() -> dict:
    """Collect event release specific information."""
    info = {}
    info["event_name"] = get_input("イベント名:")
    info["event_date"] = get_input("開催日時:")
    info["event_venue"] = get_input("開催場所（オンライン/会場名）:")
    info["event_url"] = get_input("イベントURL/申込URL:", required=False)
    info["event_summary"] = get_input("イベント概要:")
    info["event_background"] = get_input(
        "開催背景・目的:",
        multiline=True,
    )
    info["event_program"] = get_input(
        "プログラム内容・登壇者情報:",
        multiline=True,
    )
    info["target_audience"] = get_input("対象者:")
    info["capacity"] = get_input("定員:", required=False)
    info["price"] = get_input("参加費:", required=False)
    info["ceo_comment"] = get_input(
        "代表/主催者コメント（任意）:",
        multiline=True,
        required=False,
    )
    return info


def collect_update_info() -> dict:
    """Collect service update release specific information."""
    info = {}
    info["service_name"] = get_input("サービス/プロダクト名:")
    info["service_url"] = get_input("サービスURL:", required=False)
    info["update_summary"] = get_input("アップデート概要:")
    info["update_details"] = get_input(
        "アップデート内容の詳細（主な変更点を1行1項目で）:",
        multiline=True,
    )
    info["background"] = get_input(
        "アップデートの背景（ユーザーの声、市場変化等）:",
        multiline=True,
    )
    info["impact"] = get_input(
        "ユーザーへの影響・メリット（数値があれば）:",
        multiline=True,
    )
    info["future_plan"] = get_input(
        "今後の展望（任意）:",
        multiline=True,
        required=False,
    )
    info["ceo_comment"] = get_input(
        "代表コメント（任意）:",
        multiline=True,
        required=False,
    )
    return info


def collect_award_info() -> dict:
    """Collect award release specific information."""
    info = {}
    info["award_name"] = get_input("受賞/認定名:")
    info["awarding_body"] = get_input("授与機関/主催者:")
    info["award_date"] = get_input("受賞/認定日:")
    info["award_reason"] = get_input(
        "受賞/認定理由:",
        multiline=True,
    )
    info["service_overview"] = get_input(
        "対象となったサービス/取り組みの概要:",
        multiline=True,
    )
    info["significance"] = get_input(
        "受賞の意義・今後への影響:",
        multiline=True,
    )
    info["ceo_comment"] = get_input(
        "代表コメント（任意）:",
        multiline=True,
        required=False,
    )
    return info


# -- Press release generators --

def generate_service_release(common: dict, specific: dict) -> str:
    """Generate a service launch press release."""
    c, s = common, specific
    company = c["company_name"]
    kana = f"（{c['company_name_kana']}）" if c.get("company_name_kana") else ""

    # Title
    title = f"{company}が、{s['service_summary']}「{s['service_name']}」を提供開始"

    # Subtitle
    subtitle = (
        f"{company}{kana}が、{s['target_audience']}向けに"
        f"「{s['service_name']}」の提供を{c['release_date']}より開始"
    )

    # Lead paragraph
    lead = (
        f"{company}（本社：{c['location']}、代表取締役：{c['representative']}）は、"
        f"{c['release_date']}より、{s['service_summary']}「{s['service_name']}」の"
        f"提供を開始いたします。"
    )
    if s.get("service_url"):
        lead += f"\n{s['service_name']}：{s['service_url']}"

    # Features section
    features_lines = s["features"].strip().split("\n") if s.get("features") else []
    features_text = ""
    if features_lines:
        features_text = "\n\n## 「{}」の主な特徴\n\n".format(s["service_name"])
        for i, feat in enumerate(features_lines, 1):
            feat = feat.strip().lstrip("・-– ")
            features_text += f"**{i}. {feat}**\n\n"

    # Background section
    background_text = ""
    if s.get("background"):
        background_text = f"\n\n## 背景\n\n{s['background']}"

    # Differentiation section
    diff_text = ""
    if s.get("differentiation"):
        diff_text = f"\n\n## 他にはない強み\n\n{s['differentiation']}"

    # Price section
    price_text = ""
    if s.get("price"):
        price_text = f"\n\n## 料金\n\n{s['price']}"

    # CEO comment
    comment_text = ""
    if s.get("ceo_comment"):
        comment_text = (
            f"\n\n## 代表コメント\n\n"
            f"{company} 代表取締役 {c['representative']}\n\n"
            f"「{s['ceo_comment']}」"
        )

    # Future plan
    future_text = ""
    if s.get("future_plan"):
        future_text = f"\n\n## 今後の展望\n\n{s['future_plan']}"

    # Assemble
    body = (
        f"# {title}\n\n"
        f"**{subtitle}**\n\n"
        f"---\n\n"
        f"{lead}"
        f"{background_text}"
        f"{features_text}"
        f"{diff_text}"
        f"{price_text}"
        f"{comment_text}"
        f"{future_text}"
    )

    return body + _company_boilerplate(c)


def generate_partnership_release(common: dict, specific: dict) -> str:
    """Generate a partnership press release."""
    c, s = common, specific
    company = c["company_name"]
    kana = f"（{c['company_name_kana']}）" if c.get("company_name_kana") else ""

    title = f"{company}が、{s['partner_name']}と{s['partnership_type']}を締結"
    subtitle = (
        f"{company}{kana}と{s['partner_name']}が{s['partnership_type']}を締結し、"
        f"{s['partnership_purpose'].split(chr(10))[0]}"
    )

    lead = (
        f"{company}（本社：{c['location']}、代表取締役：{c['representative']}）は、"
        f"{s['partner_name']}と{s['partnership_type']}を締結いたしました。"
        f"本提携により、{s['partnership_purpose'].split(chr(10))[0]}を推進してまいります。"
    )

    body = (
        f"# {title}\n\n"
        f"**{subtitle}**\n\n"
        f"---\n\n"
        f"{lead}\n\n"
        f"## 提携の背景・目的\n\n{s['partnership_purpose']}\n\n"
        f"## {s['partner_name']}について\n\n{s['partner_description']}\n\n"
        f"## 提携内容\n\n{s['partnership_content']}\n\n"
        f"## 期待される成果\n\n{s['expected_outcome']}"
    )

    if s.get("ceo_comment"):
        body += (
            f"\n\n## {company} 代表コメント\n\n"
            f"{company} 代表取締役 {c['representative']}\n\n"
            f"「{s['ceo_comment']}」"
        )
    if s.get("partner_comment"):
        body += f"\n\n## {s['partner_name']} コメント\n\n「{s['partner_comment']}」"
    if s.get("future_plan"):
        body += f"\n\n## 今後の展望\n\n{s['future_plan']}"

    return body + _company_boilerplate(c)


def generate_funding_release(common: dict, specific: dict) -> str:
    """Generate a funding press release."""
    c, s = common, specific
    company = c["company_name"]
    kana = f"（{c['company_name_kana']}）" if c.get("company_name_kana") else ""

    title = f"{company}が、{s['round']}で総額{s['amount']}の資金調達を完了"
    subtitle = (
        f"{company}{kana}が{s['round']}ラウンドにて総額{s['amount']}の資金調達を実施。"
        f"{s['funding_purpose'].split(chr(10))[0]}を加速"
    )

    # Format investors
    investors_list = [inv.strip() for inv in s["investors"].strip().split("\n") if inv.strip()]
    investors_str = "、".join(investors_list)

    lead = (
        f"{company}（本社：{c['location']}、代表取締役：{c['representative']}）は、"
        f"{investors_str}を引受先とする{s['round']}ラウンドにて、"
        f"総額{s['amount']}の資金調達を完了いたしました。"
    )
    if s.get("lead_investor"):
        lead += f"リードインベスターは{s['lead_investor']}です。"

    body = (
        f"# {title}\n\n"
        f"**{subtitle}**\n\n"
        f"---\n\n"
        f"{lead}\n\n"
        f"## 事業概要\n\n{s['business_overview']}\n\n"
        f"## 市場背景・課題認識\n\n{s['market_background']}\n\n"
        f"## 資金使途\n\n{s['funding_purpose']}\n\n"
        f"## 引受先一覧\n\n"
    )
    for inv in investors_list:
        body += f"- {inv}\n"

    if s.get("ceo_comment"):
        body += (
            f"\n## 代表コメント\n\n"
            f"{company} 代表取締役 {c['representative']}\n\n"
            f"「{s['ceo_comment']}」"
        )
    if s.get("investor_comment"):
        body += f"\n\n## 投資家コメント\n\n「{s['investor_comment']}」"

    body += f"\n\n## 今後の事業展開\n\n{s['future_plan']}"

    if s.get("hiring"):
        body += f"\n\n## 採用情報\n\n{s['hiring']}"

    return body + _company_boilerplate(c)


def generate_event_release(common: dict, specific: dict) -> str:
    """Generate an event press release."""
    c, s = common, specific
    company = c["company_name"]
    kana = f"（{c['company_name_kana']}）" if c.get("company_name_kana") else ""

    title = f"{company}が、「{s['event_name']}」を{s['event_date']}に開催"
    subtitle = (
        f"{company}{kana}が{s['target_audience']}を対象とした"
        f"「{s['event_name']}」を開催"
    )

    lead = (
        f"{company}（本社：{c['location']}、代表取締役：{c['representative']}）は、"
        f"{s['event_date']}に「{s['event_name']}」を"
        f"{s['event_venue']}にて開催いたします。"
    )

    body = (
        f"# {title}\n\n"
        f"**{subtitle}**\n\n"
        f"---\n\n"
        f"{lead}\n\n"
        f"## 開催背景・目的\n\n{s['event_background']}\n\n"
        f"## イベント概要\n\n{s['event_summary']}\n\n"
        f"| 項目 | 詳細 |\n"
        f"|------|------|\n"
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
        body += (
            f"\n\n## 主催者コメント\n\n"
            f"{company} 代表取締役 {c['representative']}\n\n"
            f"「{s['ceo_comment']}」"
        )

    return body + _company_boilerplate(c)


def generate_update_release(common: dict, specific: dict) -> str:
    """Generate a service update press release."""
    c, s = common, specific
    company = c["company_name"]
    kana = f"（{c['company_name_kana']}）" if c.get("company_name_kana") else ""

    title = f"{company}が、「{s['service_name']}」の大規模アップデート版を公開"
    subtitle = (
        f"{company}{kana}が「{s['service_name']}」をアップデート。"
        f"{s['update_summary']}"
    )

    lead = (
        f"{company}（本社：{c['location']}、代表取締役：{c['representative']}）は、"
        f"{c['release_date']}より、{s['update_summary']}"
    )
    if s.get("service_url"):
        lead += f"\n{s['service_name']}：{s['service_url']}"

    updates = s["update_details"].strip().split("\n") if s.get("update_details") else []
    updates_text = ""
    if updates:
        updates_text = "\n\n## 主なアップデート内容\n\n"
        for i, item in enumerate(updates, 1):
            item = item.strip().lstrip("・-– ")
            updates_text += f"**{i}. {item}**\n\n"

    body = (
        f"# {title}\n\n"
        f"**{subtitle}**\n\n"
        f"---\n\n"
        f"{lead}\n\n"
        f"## 背景\n\n{s['background']}"
        f"{updates_text}\n\n"
        f"## ユーザーへのメリット\n\n{s['impact']}"
    )

    if s.get("ceo_comment"):
        body += (
            f"\n\n## 代表コメント\n\n"
            f"{company} 代表取締役 {c['representative']}\n\n"
            f"「{s['ceo_comment']}」"
        )
    if s.get("future_plan"):
        body += f"\n\n## 今後の展望\n\n{s['future_plan']}"

    return body + _company_boilerplate(c)


def generate_award_release(common: dict, specific: dict) -> str:
    """Generate an award press release."""
    c, s = common, specific
    company = c["company_name"]
    kana = f"（{c['company_name_kana']}）" if c.get("company_name_kana") else ""

    title = f"{company}が、「{s['award_name']}」を受賞"
    subtitle = (
        f"{company}{kana}が{s['awarding_body']}による"
        f"「{s['award_name']}」を受賞"
    )

    lead = (
        f"{company}（本社：{c['location']}、代表取締役：{c['representative']}）は、"
        f"{s['award_date']}に{s['awarding_body']}より"
        f"「{s['award_name']}」を受賞いたしました。"
    )

    body = (
        f"# {title}\n\n"
        f"**{subtitle}**\n\n"
        f"---\n\n"
        f"{lead}\n\n"
        f"## 受賞理由\n\n{s['award_reason']}\n\n"
        f"## 対象サービス/取り組み概要\n\n{s['service_overview']}\n\n"
        f"## 受賞の意義\n\n{s['significance']}"
    )

    if s.get("ceo_comment"):
        body += (
            f"\n\n## 代表コメント\n\n"
            f"{company} 代表取締役 {c['representative']}\n\n"
            f"「{s['ceo_comment']}」"
        )

    return body + _company_boilerplate(c)


def _company_boilerplate(c: dict) -> str:
    """Generate the company overview and contact boilerplate."""
    kana = f"（{c['company_name_kana']}）" if c.get("company_name_kana") else ""

    boilerplate = f"\n\n---\n\n## 会社概要\n\n"
    boilerplate += f"| 項目 | 詳細 |\n|------|------|\n"
    boilerplate += f"| 会社名 | {c['company_name']}{kana} |\n"
    boilerplate += f"| 代表者 | {c['representative']} |\n"
    boilerplate += f"| 所在地 | {c['location']} |\n"
    if c.get("founded"):
        boilerplate += f"| 設立 | {c['founded']} |\n"
    if c.get("capital"):
        boilerplate += f"| 資本金 | {c['capital']} |\n"
    boilerplate += f"| URL | {c['url']} |\n"

    if c.get("company_description"):
        boilerplate += f"\n{c['company_description']}\n"

    boilerplate += (
        f"\n## 本件に関するお問い合わせ先\n\n"
        f"{c['company_name']}\n"
        f"担当：{c['contact_person']}\n"
        f"メール：{c['contact_email']}\n"
    )
    if c.get("contact_phone"):
        boilerplate += f"電話：{c['contact_phone']}\n"

    return boilerplate


# -- Profile save/load --

PROFILE_DIR = Path(__file__).parent / "profiles"


def save_profile(common: dict, name: str):
    """Save company info as reusable profile."""
    PROFILE_DIR.mkdir(exist_ok=True)
    path = PROFILE_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(common, f, ensure_ascii=False, indent=2)
    print(f"\n  プロフィール「{name}」を保存しました: {path}")


def load_profile(name: str) -> dict | None:
    """Load a saved company profile."""
    path = PROFILE_DIR / f"{name}.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def list_profiles() -> list[str]:
    """List available profiles."""
    if not PROFILE_DIR.exists():
        return []
    return [p.stem for p in PROFILE_DIR.glob("*.json")]


# -- Main flow --

GENERATORS = {
    "service": (collect_service_info, generate_service_release),
    "partnership": (collect_partnership_info, generate_partnership_release),
    "funding": (collect_funding_info, generate_funding_release),
    "event": (collect_event_info, generate_event_release),
    "update": (collect_update_info, generate_update_release),
    "award": (collect_award_info, generate_award_release),
}


def main():
    parser = argparse.ArgumentParser(
        description="PR Times向けプレスリリース自動生成ツール"
    )
    parser.add_argument(
        "--type", "-t",
        choices=RELEASE_TYPES.keys(),
        help="リリースの種類",
    )
    parser.add_argument(
        "--output", "-o",
        help="出力ファイルパス（省略時は標準出力）",
    )
    parser.add_argument(
        "--profile", "-p",
        help="保存済みの会社プロフィール名を使用",
    )
    parser.add_argument(
        "--save-profile", "-s",
        help="入力した会社情報をプロフィールとして保存（名前を指定）",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="保存済みプロフィール一覧を表示",
    )
    args = parser.parse_args()

    if args.list_profiles:
        profiles = list_profiles()
        if profiles:
            print("保存済みプロフィール:")
            for p in profiles:
                print(f"  - {p}")
        else:
            print("保存済みプロフィールはありません。")
        return

    print("=" * 60)
    print("  PR Times向け プレスリリース自動生成ツール")
    print("  (esse-sense形式ベース)")
    print("=" * 60)

    # Select release type
    if args.type:
        release_type = args.type
        print(f"\nリリース種類: {RELEASE_TYPES[release_type]}")
    else:
        release_type = get_choice(
            "プレスリリースの種類を選択してください:",
            RELEASE_TYPES,
        )

    # Collect or load company info
    if args.profile:
        common = load_profile(args.profile)
        if common:
            print(f"\nプロフィール「{args.profile}」を読み込みました。")
        else:
            print(f"\nプロフィール「{args.profile}」が見つかりません。手動入力します。")
            common = collect_common_info()
    else:
        profiles = list_profiles()
        if profiles:
            print(f"\n保存済みプロフィールがあります: {', '.join(profiles)}")
            use_saved = get_input("使用するプロフィール名（新規入力はEnter）:", required=False)
            if use_saved and use_saved in profiles:
                common = load_profile(use_saved)
                print(f"プロフィール「{use_saved}」を読み込みました。")
                # Allow updating release date
                new_date = get_input(
                    f"リリース日（現在: {common.get('release_date', '未設定')}、変更しない場合はEnter）:",
                    required=False,
                )
                if new_date:
                    common["release_date"] = new_date
            else:
                common = collect_common_info()
        else:
            common = collect_common_info()

    # Collect release-specific info
    collector, generator = GENERATORS[release_type]
    print(f"\n--- {RELEASE_TYPES[release_type]}の情報を入力 ---")
    specific = collector()

    # Generate press release
    print("\n生成中...")
    result = generator(common, specific)

    # Output
    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"\nプレスリリースを保存しました: {output_path}")
    else:
        print("\n" + "=" * 60)
        print("  生成されたプレスリリース")
        print("=" * 60 + "\n")
        print(result)

    # Save profile if requested
    if args.save_profile:
        save_profile(common, args.save_profile)
    elif not args.profile:
        save_it = get_input(
            "会社情報をプロフィールとして保存しますか？（保存名を入力、不要ならEnter）:",
            required=False,
        )
        if save_it:
            save_profile(common, save_it)

    print("\n完了。PR Timesへの入稿時は、Markdown記法を適宜HTML/プレーンテキストに変換してください。")
    print("画像（3〜5枚推奨）の準備もお忘れなく。")


if __name__ == "__main__":
    main()
