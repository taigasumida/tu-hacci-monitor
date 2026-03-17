"""
tu-hacci 出面順位モニター
楽天市場・Yahoo!ショッピングで各キーワードのtu-hacci順位を調査してLINE通知する
通知: LINE Messaging API (Push Message)
"""

import requests
from bs4 import BeautifulSoup
import urllib.parse
import time
import os
import json
from datetime import datetime

# ==================== 設定 ====================

# GitHub Secrets に設定する2つの値
LINE_CHANNEL_TOKEN = os.environ.get("LINE_CHANNEL_TOKEN", "")  # チャネルアクセストークン
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")              # 送信先のユーザーID

KEYWORDS = [
    "ナイトブラ",
    "ブラジャー",
    "ブラトップ",
    "胸が小さく見えるブラ",
    "授乳ブラ",
    "ガードル",
    "バスローブ",
    "タンクトップ",
    "キャミソール",
]

# tu-hacciの表記揺れ（全て小文字で比較）
TU_HACCI_VARIANTS = [
    "tu-hacci",
    "tu_hacci",
    "tuhacci",
    "tu hacci",
    "ツハッチ",
    "つはっち",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}

# ==================== ヘルパー ====================

def is_tu_hacci(text: str) -> bool:
    """テキスト・URLにtu-hacciが含まれるか判定"""
    if not text:
        return False
    text_lower = text.lower()
    return any(v.lower() in text_lower for v in TU_HACCI_VARIANTS)


def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


# ==================== 楽天市場 ====================

def search_rakuten(keyword: str) -> list[dict]:
    """楽天市場で検索し上位20件の商品情報を返す"""
    encoded = urllib.parse.quote(keyword)
    url = f"https://search.rakuten.co.jp/search/mall/{encoded}/"

    try:
        session = get_session()
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "lxml")

        products = []

        # --- セレクタ戦略1: searchresultitem ---
        items = soup.select("div.searchresultitem")

        # --- セレクタ戦略2: dui-card系 ---
        if not items:
            items = soup.select("div.dui-card")

        # --- セレクタ戦略3: 商品リンクを直接取得 ---
        if not items:
            items = soup.select('a[href*="item.rakuten.co.jp"]')

        # --- セレクタ戦略4: 汎用アイテム ---
        if not items:
            items = soup.select('[class*="item"]:has(a[href])')

        rank = 1
        for item in items:
            if rank > 20:
                break

            # 商品名を取得
            name = ""
            href = ""

            if item.name == "a":
                name = item.get_text(strip=True)[:80]
                href = item.get("href", "")
            else:
                # titleクラスやitemNameクラスを探す
                name_selectors = [
                    ".title a", ".itemName a", ".title", ".itemName",
                    "h2 a", "h3 a", "h2", "h3",
                    '[class*="title"] a', '[class*="name"] a',
                    '[class*="title"]', '[class*="name"]',
                ]
                for sel in name_selectors:
                    elem = item.select_one(sel)
                    if elem and elem.get_text(strip=True):
                        name = elem.get_text(strip=True)[:80]
                        href = elem.get("href", "")
                        break

                if not name:
                    # フォールバック: 最初のリンクテキスト
                    link = item.select_one("a[href]")
                    if link:
                        name = link.get_text(strip=True)[:80]
                        href = link.get("href", "")

            if not name:
                continue

            products.append({
                "rank": rank,
                "name": name,
                "href": href,
                "is_tu_hacci": is_tu_hacci(name) or is_tu_hacci(href),
            })
            rank += 1

        if not products:
            # 全体テキストからtu-hacciを直接検索（フォールバック）
            all_text = soup.get_text()
            found = is_tu_hacci(all_text)
            products.append({
                "rank": 0,
                "name": "（商品リスト取得失敗 - ページ構造変更の可能性）",
                "href": "",
                "is_tu_hacci": found,
                "error": True,
            })

        return products

    except Exception as e:
        return [{"rank": 0, "name": f"エラー: {str(e)[:50]}", "href": "", "is_tu_hacci": False, "error": True}]


# ==================== Yahoo!ショッピング ====================

def search_yahoo(keyword: str) -> list[dict]:
    """Yahoo!ショッピングで検索し上位20件の商品情報を返す"""
    encoded = urllib.parse.quote(keyword)
    url = f"https://shopping.yahoo.co.jp/search?p={encoded}&ei=UTF-8"

    try:
        session = get_session()
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "lxml")

        products = []

        # --- セレクタ戦略1: Items ulのli ---
        items = soup.select("ul.Items > li")

        # --- セレクタ戦略2: SearchResult系 ---
        if not items:
            items = soup.select('[class*="SearchResult"] li')

        # --- セレクタ戦略3: 汎用商品li ---
        if not items:
            items = soup.select('li[class*="Item"]')

        # --- セレクタ戦略4: 商品リンクを直接収集 ---
        if not items:
            items = soup.select('a[href*="store.shopping.yahoo.co.jp"], a[href*="shopping.yahoo.co.jp/product"]')

        rank = 1
        for item in items:
            if rank > 20:
                break

            name = ""
            href = ""

            if item.name == "a":
                name = item.get_text(strip=True)[:80]
                href = item.get("href", "")
            else:
                name_selectors = [
                    '[class*="name"]', '[class*="title"]',
                    '[class*="Name"]', '[class*="Title"]',
                    "h3 a", "h2 a", "h3", "h2",
                    "a[href]",
                ]
                for sel in name_selectors:
                    elem = item.select_one(sel)
                    if elem and elem.get_text(strip=True):
                        name = elem.get_text(strip=True)[:80]
                        href = elem.get("href", "")
                        break

            if not name:
                continue

            products.append({
                "rank": rank,
                "name": name,
                "href": href,
                "is_tu_hacci": is_tu_hacci(name) or is_tu_hacci(href),
            })
            rank += 1

        if not products:
            all_text = soup.get_text()
            found = is_tu_hacci(all_text)
            products.append({
                "rank": 0,
                "name": "（商品リスト取得失敗 - ページ構造変更の可能性）",
                "href": "",
                "is_tu_hacci": found,
                "error": True,
            })

        return products

    except Exception as e:
        return [{"rank": 0, "name": f"エラー: {str(e)[:50]}", "href": "", "is_tu_hacci": False, "error": True}]


# ==================== フォーマット ====================

def format_site_result(keyword: str, products: list[dict], site_name: str) -> str:
    lines = [f"\n【{site_name}】{keyword}"]

    # PR枠（1〜4位）の表示
    lines.append("  ▼PR枠(1〜4位)")
    for p in products[:4]:
        if p.get("error"):
            lines.append(f"  {p['name']}")
            continue
        mark = "✅tu-hacci" if p["is_tu_hacci"] else p["name"][:28]
        lines.append(f"  {p['rank']}. {mark}")

    # tu-hacciの順位を探す
    tu_pos = next((p["rank"] for p in products if p["is_tu_hacci"] and p["rank"] > 0), None)

    if tu_pos:
        if tu_pos <= 4:
            lines.append(f"  👑 tu-hacci: {tu_pos}位（PR枠内！）")
        else:
            lines.append(f"  📍 tu-hacci: {tu_pos}位")
    else:
        if any(p.get("error") for p in products):
            lines.append("  ⚠️ tu-hacci: 取得エラー")
        else:
            lines.append("  ❌ tu-hacci: 20位以内に未掲載")

    return "\n".join(lines)


# ==================== LINE通知 ====================

def send_line(message: str) -> None:
    """LINE Messaging API (Push Message) でメッセージを送信する"""
    if not LINE_CHANNEL_TOKEN or not LINE_USER_ID:
        print("[LINE] TOKEN or USER_ID未設定のため標準出力のみ")
        print(message)
        return

    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}",
        "Content-Type": "application/json",
    }

    # Messaging APIは1メッセージ最大5000文字 → 念のため分割
    max_len = 4900
    chunks = [message[i:i + max_len] for i in range(0, len(message), max_len)]

    for chunk in chunks:
        payload = {
            "to": LINE_USER_ID,
            "messages": [{"type": "text", "text": chunk}],
        }
        try:
            resp = requests.post(
                "https://api.line.me/v2/bot/message/push",
                headers=headers,
                data=json.dumps(payload),
                timeout=10,
            )
            if resp.status_code == 200:
                print(f"[LINE] 送信成功 ({len(chunk)}文字)")
            else:
                print(f"[LINE] 送信失敗: {resp.status_code} {resp.text}")
        except Exception as e:
            print(f"[LINE] 例外: {e}")
        time.sleep(0.5)


# ==================== メイン ====================

def main():
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    print(f"\n=== tu-hacci 出面調査開始: {now} ===\n")

    # サマリー用データ
    summary = []

    # メッセージを複数に分けて送る（1メッセージ = 1キーワード分）
    header_msg = f"\n🔍 tu-hacci 出面調査レポート\n{now}"
    send_line(header_msg)
    time.sleep(1)

    for keyword in KEYWORDS:
        print(f"[調査中] {keyword}")

        # 楽天
        rakuten = search_rakuten(keyword)
        time.sleep(2)

        # Yahoo!
        yahoo = search_yahoo(keyword)
        time.sleep(2)

        # 順位集計
        r_pos = next((p["rank"] for p in rakuten if p["is_tu_hacci"] and p["rank"] > 0), None)
        y_pos = next((p["rank"] for p in yahoo if p["is_tu_hacci"] and p["rank"] > 0), None)
        summary.append((keyword, r_pos, y_pos))

        # キーワードごとのメッセージ
        msg = format_site_result(keyword, rakuten, "楽天")
        msg += "\n"
        msg += format_site_result(keyword, yahoo, "Yahoo!")
        print(msg)
        send_line(msg)
        time.sleep(1)

    # サマリー送信
    summary_lines = ["\n📊 サマリー（tu-hacci順位）\n"]
    summary_lines.append(f"{'キーワード':<16} 楽天    Yahoo!")
    summary_lines.append("-" * 38)
    for kw, r, y in summary:
        r_str = f"{r}位" if r else "圏外"
        y_str = f"{y}位" if y else "圏外"
        summary_lines.append(f"{kw[:15]:<16} {r_str:<8} {y_str}")
    summary_msg = "\n".join(summary_lines)
    print(summary_msg)
    send_line(summary_msg)

    print("\n=== 調査完了 ===")


if __name__ == "__main__":
    main()
