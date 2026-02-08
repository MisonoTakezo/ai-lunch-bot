"""パス定数・環境変数の一元管理"""

from pathlib import Path

from dotenv import load_dotenv

# プロジェクトルート = lunch_bot/ の親
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# .env をロード
load_dotenv(PROJECT_ROOT / ".env")

# ディレクトリ
IMG_DIR = PROJECT_ROOT / "img"
IMG_DIR.mkdir(exist_ok=True)

# データファイル
MENU_FILE = PROJECT_ROOT / "menu_data.json"

# 外部 URL
MENU_PAGE_URL = "https://sumiyoshi-bento.com/menu/"
ORDER_BASE_URL = "https://sumiyoshi.azurewebsites.net"

# HTTP
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
