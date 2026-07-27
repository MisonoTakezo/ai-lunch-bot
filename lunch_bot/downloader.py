"""メニューのファイル（PDF/画像）をダウンロードするモジュール

sumiyoshi-bento.com/menu/ から掲載中の全メニューファイル（PDF/JPG/PNG）を取得し、
img/ ディレクトリに保存する。
"""

import logging
import re
from pathlib import Path
from urllib.parse import unquote, urljoin

import httpx
from bs4 import BeautifulSoup

from lunch_bot.config import IMG_DIR, MENU_PAGE_URL

logger = logging.getLogger(__name__)

MENU_FILE_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png")
# 装飾用画像を除外するキーワード（URLに含まれれば除外）
EXCLUDED_URL_KEYWORDS = (
    "logo", "instagram", "facebook", "header", "icon", "banner",
    "-scaled.",  # WordPress が自動生成する原本の縮小版（原本PDF/画像と重複するため除外）
)


def fetch_pdf_urls() -> list[str]:
    """メニューページをスクレイピングし、掲載中の全メニューファイル URL を抽出する。

    <a href> と <img src> の両方を対象に、拡張子が PDF/JPG/JPEG/PNG のものを収集。
    ロゴ/SNSアイコン等の装飾画像は除外する。
    """
    logger.info("メニューページを取得中: %s", MENU_PAGE_URL)
    resp = httpx.get(MENU_PAGE_URL, follow_redirects=True, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    urls: list[str] = []

    for tag in soup.find_all(["a", "img"]):
        raw = tag.get("href") or tag.get("src")
        if not raw:
            continue
        raw_lower = raw.lower()
        if not raw_lower.endswith(MENU_FILE_EXTENSIONS):
            continue
        if any(k in raw_lower for k in EXCLUDED_URL_KEYWORDS):
            continue
        full_url = urljoin(MENU_PAGE_URL, raw)
        if full_url not in urls:
            urls.append(full_url)

    logger.info("メニューファイルを %d 件検出", len(urls))
    return urls


def _convert_url_to_filename(url: str) -> str:
    """URL からファイル名を生成する。日本語ファイル名はデコードして保持。"""
    decoded = unquote(url.split("/")[-1])
    return re.sub(r"[^\w\-.\u3000-\u9fff\uff00-\uffef]", "_", decoded)


def download_pdf(url: str, dest_dir: Path | None = None) -> Path:
    """単一の PDF をダウンロードし、ローカルパスを返す。既に存在すればスキップ。"""
    dest_dir = dest_dir or IMG_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    filename = _convert_url_to_filename(url)
    filepath = dest_dir / filename

    if filepath.exists():
        logger.info("スキップ (既存): %s", filepath.name)
        return filepath

    logger.info("ダウンロード中: %s", url)
    resp = httpx.get(url, follow_redirects=True, timeout=60)
    resp.raise_for_status()

    filepath.write_bytes(resp.content)
    logger.info("保存完了: %s (%.1f KB)", filepath.name, len(resp.content) / 1024)
    return filepath


def _cleanup_old_pdfs(pdf_urls: list[str], dest_dir: Path) -> None:
    """サイトに掲載されていないローカルのメニューファイル（PDF/画像）を削除する。"""
    # サイトのURLから期待されるファイル名のセットを作成
    expected_filenames = {_convert_url_to_filename(url) for url in pdf_urls}

    # ローカルのメニューファイルを確認し、サイトにないものを削除
    for local_file in dest_dir.iterdir():
        if not local_file.is_file():
            continue
        if local_file.suffix.lower() not in MENU_FILE_EXTENSIONS:
            continue
        if local_file.name not in expected_filenames:
            logger.info("古いメニューファイルを削除: %s", local_file.name)
            local_file.unlink()


def download_all_menus(dest_dir: Path | None = None) -> list[Path]:
    """メニューページから全 PDF をダウンロードし、パスのリストを返す。"""
    dest_dir = dest_dir or IMG_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    pdf_urls = fetch_pdf_urls()
    if not pdf_urls:
        logger.warning("メニュー PDF が見つかりませんでした。")
        return []

    # サイトにない古い PDF を削除
    _cleanup_old_pdfs(pdf_urls, dest_dir)

    downloaded: list[Path] = []
    for url in pdf_urls:
        try:
            path = download_pdf(url, dest_dir)
            downloaded.append(path)
        except Exception as e:
            logger.error("ダウンロード失敗 (%s): %s", url, e)

    logger.info("合計 %d 件の PDF を取得しました。", len(downloaded))
    return downloaded
