"""注文クライアント — すみよし弁当注文システムへの HTTP 注文

order.sh の Python 移植版。httpx でログイン → トークン取得 → 注文送信を行う。
認証情報は .env から読み込む。Cookie を保存して再利用することでログイン回数を削減。
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from lunch_bot.config import BROWSER_HEADERS, COOKIE_FILE, ORDER_BASE_URL

logger = logging.getLogger(__name__)

# メニュー種別 → インデックス
MENU_TYPE_MAP: dict[str, int] = {
    "和風": 0,
    "和風ランチ": 0,
    "和風らんち": 0,
    "wafu": 0,
    "あいランチ": 1,
    "あい": 1,
    "ai": 1,
    "その他": 2,
    "other": 2,
}

# インデックス → 表示名
MENU_INDEX_NAME: dict[int, str] = {0: "和風ランチ", 1: "あいランチ", 2: "その他"}


@dataclass
class OrderResult:
    """注文結果"""

    success: bool
    message: str
    date: str
    menu_type: str
    quantity: int


@dataclass
class DayOrderStatus:
    """1 日分の注文状況"""

    date: str  # YYYY-MM-DD
    orders: dict[str, int] = field(default_factory=dict)  # {"和風らんち": 1, ...}
    holiday: bool = False
    holiday_label: str = ""


# ─────────────────────────── helpers ───────────────────────────


def _get_credentials() -> tuple[str, str, str]:
    """認証情報を .env から取得する。"""
    company_cd = os.getenv("BENTO_COMPANY_CD", "000748")
    user_cd = os.getenv("BENTO_USER_CD", "")
    password = os.getenv("BENTO_PASSWORD", "")

    if not user_cd or not password:
        raise RuntimeError(
            "注文には認証情報が必要です。"
            ".env に BENTO_USER_CD と BENTO_PASSWORD を設定してください。"
        )
    return company_cd, user_cd, password


def _save_cookies(client: httpx.Client) -> None:
    """認証 Cookie をファイルに保存する。"""
    cookies_data = {
        "saved_at": datetime.now().isoformat(),
        "cookies": [],
    }
    for cookie in client.cookies.jar:
        cookies_data["cookies"].append(
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
            }
        )
    COOKIE_FILE.write_text(json.dumps(cookies_data, indent=2, ensure_ascii=False))
    logger.info("Cookie を保存しました: %s", COOKIE_FILE)


def _load_cookies(client: httpx.Client) -> bool:
    """保存された Cookie を読み込む。成功時 True を返す。"""
    if not COOKIE_FILE.exists():
        return False

    try:
        data = json.loads(COOKIE_FILE.read_text())
        for c in data.get("cookies", []):
            client.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
        logger.info("保存された Cookie を読み込みました")
        return True
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Cookie ファイルの読み込みに失敗: %s", e)
        return False


def _is_session_valid(client: httpx.Client) -> bool:
    """保存された Cookie でセッションが有効か確認する。"""
    headers = BROWSER_HEADERS.copy()
    try:
        resp = client.get(
            f"{ORDER_BASE_URL}/Order",
            headers=headers,
            follow_redirects=False,
        )
        # ログインページにリダイレクトされなければ有効
        if resp.status_code == 200:
            return True
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "").lower()
            # ログインページへのリダイレクトはセッション無効
            if location == "/" or location.endswith("/") or "login" in location:
                logger.info("セッション無効: リダイレクト先 %s", location)
                return False
            return True
        return False
    except httpx.HTTPError:
        return False


def _extract_token(html: str) -> str:
    """HTML から __RequestVerificationToken を抽出する。"""
    match = re.search(
        r'name="__RequestVerificationToken"\s+[^>]*value="([^"]*)"', html
    )
    if not match:
        match = re.search(
            r'value="([^"]*)"\s+[^>]*name="__RequestVerificationToken"', html
        )
    if not match:
        raise RuntimeError("リクエスト検証トークンが取得できませんでした。")
    return match.group(1)


def _resolve_menu_index(menu_type: str) -> int:
    """メニュー種別文字列をインデックスに変換する。"""
    key = (
        menu_type.strip().lower()
        if menu_type.strip().lower() in MENU_TYPE_MAP
        else menu_type.strip()
    )
    if key in MENU_TYPE_MAP:
        return MENU_TYPE_MAP[key]
    try:
        idx = int(menu_type)
        if idx in (0, 1, 2):
            return idx
    except ValueError:
        pass
    raise ValueError(
        f"不明なメニュー種別: '{menu_type}'. "
        f"使用可能: {', '.join(MENU_TYPE_MAP.keys())} または 0/1/2"
    )


def _normalize_date(date_str: str) -> str:
    """日付文字列を YYYY/MM/DD 形式に正規化する。"""
    normalized = date_str.replace("-", "/")
    parts = normalized.split("/")
    if len(parts) != 3 or len(parts[0]) != 4:
        raise ValueError(
            f"日付形式が不正です: '{date_str}'. "
            "YYYY-MM-DD または YYYY/MM/DD を使用してください。"
        )
    return normalized


# ─────────────────────────── public API ───────────────────────────


def place_order(date: str, menu_type: str, quantity: int) -> OrderResult:
    """注文を実行する。

    Args:
        date: 注文日 (YYYY-MM-DD or YYYY/MM/DD)
        menu_type: メニュー種別 ("和風", "あいランチ", "その他" or 0/1/2)
        quantity: 注文数 (0 で取り消し)
    """
    menu_index = _resolve_menu_index(menu_type)
    order_date = _normalize_date(date)

    quantities = [0, 0, 0]
    quantities[menu_index] = quantity
    headers = BROWSER_HEADERS.copy()

    with httpx.Client(follow_redirects=True, timeout=30) as client:
        # 1. ログイン（保存 Cookie を優先使用）
        logger.info("[1/3] 認証処理...")
        if not _login(client):
            return OrderResult(
                success=False,
                message="ログインに失敗しました。認証情報を確認してください。",
                date=date,
                menu_type=menu_type,
                quantity=quantity,
            )

        # 2. 注文ページ → トークン取得
        logger.info("[2/3] 注文ページ取得 (日付: %s)...", order_date)
        order_url = (
            f"{ORDER_BASE_URL}/Order/CreateDetails"
            f"?dt={order_date}&kbn=1&err=false"
        )
        order_resp = client.get(
            order_url,
            headers={**headers, "Referer": f"{ORDER_BASE_URL}/"},
        )
        order_resp.raise_for_status()
        order_token = _extract_token(order_resp.text)

        # 3. 注文送信
        action = "取り消し" if quantity == 0 else "注文"
        logger.info("[3/3] %s送信 (メニュー: %s, 数量: %d)...", action, menu_type, quantity)

        client.post(
            order_url,
            data={
                "__RequestVerificationToken": order_token,
                "[0].数量": str(quantities[0]),
                "[1].数量": str(quantities[1]),
                "[2].数量": str(quantities[2]),
            },
            headers={**headers, "Referer": order_url, "Origin": ORDER_BASE_URL},
        ).raise_for_status()

    menu_name = {0: "和風ランチ", 1: "あいランチ", 2: "その他"}.get(
        menu_index, menu_type
    )
    msg = (
        f"{date} の {menu_name} の注文を取り消しました。"
        if quantity == 0
        else f"{date} の {menu_name} を {quantity} 個注文しました。"
    )
    logger.info("注文処理完了: %s", msg)
    return OrderResult(
        success=True, message=msg, date=date, menu_type=menu_name, quantity=quantity
    )


def cancel_order(date: str, menu_type: str) -> OrderResult:
    """注文を取り消す (数量 0 で送信)。"""
    return place_order(date, menu_type, quantity=0)


# ─────────────────────── order status ───────────────────────


def _login(client: httpx.Client, force: bool = False) -> bool:
    """共通ログイン処理。成功時 True を返す。

    Args:
        client: httpx クライアント
        force: True の場合、保存 Cookie を無視して再ログイン
    """
    # 保存された Cookie を試す
    if not force and _load_cookies(client):
        if _is_session_valid(client):
            logger.info("保存された Cookie でセッション有効")
            return True
        logger.info("保存された Cookie が無効、再ログインします")

    company_cd, user_cd, password = _get_credentials()
    headers = BROWSER_HEADERS.copy()

    login_resp = client.get(f"{ORDER_BASE_URL}/", headers=headers)
    login_resp.raise_for_status()
    login_token = _extract_token(login_resp.text)

    client.post(
        f"{ORDER_BASE_URL}/",
        data={
            "__RequestVerificationToken": login_token,
            "CompanyCD": company_cd,
            "UserCD": user_cd,
            "Password": password,
        },
        headers={**headers, "Referer": f"{ORDER_BASE_URL}/", "Origin": ORDER_BASE_URL},
    )
    auth_cookies = [c for c in client.cookies.jar if c.name == ".ASPXAUTH"]
    if auth_cookies:
        _save_cookies(client)
        return True
    return False


def get_order_status(date: str) -> DayOrderStatus:
    """特定日の注文状況を取得する。

    Args:
        date: 対象日 (YYYY-MM-DD or YYYY/MM/DD)
    """
    order_date = _normalize_date(date)
    headers = BROWSER_HEADERS.copy()

    with httpx.Client(follow_redirects=True, timeout=30) as client:
        if not _login(client):
            raise RuntimeError("ログインに失敗しました。")

        url = (
            f"{ORDER_BASE_URL}/Order/CreateDetails"
            f"?dt={order_date}&kbn=1&err=false"
        )
        resp = client.get(url, headers={**headers, "Referer": f"{ORDER_BASE_URL}/"})
        resp.raise_for_status()
        html = resp.text

    # [i].変更前数量 から現在の注文数を取得
    orders: dict[str, int] = {}
    for m in re.finditer(r'id="\[(\d+)\]\.変更前数量"\s*value="(\d+)"', html):
        idx = int(m.group(1))
        qty = int(m.group(2))
        name = MENU_INDEX_NAME.get(idx, f"メニュー{idx}")
        if qty > 0:
            orders[name] = qty

    return DayOrderStatus(date=date, orders=orders)


def get_monthly_orders(year: int, month: int) -> list[DayOrderStatus]:
    """月全体の注文状況を取得する。

    Args:
        year: 年 (例: 2026)
        month: 月 (1-12)
    """
    headers = BROWSER_HEADERS.copy()

    with httpx.Client(follow_redirects=True, timeout=30) as client:
        if not _login(client):
            raise RuntimeError("ログインに失敗しました。")

        resp = client.get(
            f"{ORDER_BASE_URL}/Order?idx={month}",
            headers={**headers, "Referer": f"{ORDER_BASE_URL}/"},
        )
        resp.raise_for_status()

    # BeautifulSoup でテーブル行をパース
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[DayOrderStatus] = []

    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue

        # 1列目: "10(火)" のような日付
        day_text = cells[0].get_text(strip=True)
        day_match = re.match(r"(\d+)\(.\)", day_text)
        if not day_match:
            continue
        day = int(day_match.group(1))
        date_str = f"{year}-{month:02d}-{day:02d}"

        # 2列目: 注文内容
        order_text = cells[1].get_text(strip=True)

        # 休業日チェック
        if "休業日" in order_text:
            results.append(
                DayOrderStatus(date=date_str, holiday=True, holiday_label=order_text)
            )
            continue

        # "和風らんち　1個あいランチ　2個" → {和風ランチ: 1, あいランチ: 2}
        orders: dict[str, int] = {}
        for m in re.finditer(r"([\w]+(?:らんち|ランチ|その他))\s*(\d+)個", order_text):
            name = m.group(1)
            qty = int(m.group(2))
            # 和風らんち → 和風ランチ に統一
            if "和風" in name:
                name = "和風ランチ"
            if qty > 0:
                orders[name] = qty

        results.append(DayOrderStatus(date=date_str, orders=orders))

    return results
