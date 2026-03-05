"""URLやファイルパスなどの定数を管理するモジュール"""

from pathlib import Path

import keyring

# プロジェクトルート（lunch_bot/ の親）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ディレクトリ
IMG_DIR = PROJECT_ROOT / "img"
IMG_DIR.mkdir(exist_ok=True)

# データファイル
MENU_FILE = PROJECT_ROOT / "menu_data.json"
COOKIE_FILE = PROJECT_ROOT / ".bento_cookies.json"

# メニューのPDFが掲載されているホームページのURL
MENU_PAGE_URL = "https://sumiyoshi-bento.com/menu/"
# 注文システムのベースのURL
ORDER_BASE_URL = "https://sumiyoshi.azurewebsites.net"

# HTTPリクエストのヘッダー（ブラウザっぽくしてBOT検知回避）
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# ─────────────────────── 秘密情報管理 ───────────────────────

SERVICE_NAME = "ai-lunch-bot"


def get_secret(key: str, required: bool = True) -> str | None:
    """キーチェーンから秘密情報を取得する。

    Args:
        key: 取得するキー名
        required: True の場合、キーが見つからないと RuntimeError を送出

    Returns:
        キーチェーンに保存された値、または None（required=False の場合）

    Raises:
        RuntimeError: required=True でキーが見つからない場合
    """
    value = keyring.get_password(SERVICE_NAME, key)
    if required and not value:
        raise RuntimeError(
            f"{key} がキーチェーンに登録されていません。\n"
            f"登録方法: security add-generic-password -s {SERVICE_NAME} -a {key} -w 'YOUR_VALUE'"
        )
    return value


def get_gemini_api_key() -> str:
    """Gemini API キーを取得する。"""
    return get_secret("GEMINI_API_KEY")


def get_bento_credentials() -> tuple[str, str, str]:
    """ベントー社認証情報を取得する。

    Returns:
        (company_cd, user_cd, password) のタプル
    """
    company_cd = get_secret("BENTO_COMPANY_CD")
    user_cd = get_secret("BENTO_USER_CD")
    password = get_secret("BENTO_PASSWORD")
    return company_cd, user_cd, password
