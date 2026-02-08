"""メニュー PDF ダウンローダー

sumiyoshi-bento.com/menu/ から掲載中の全メニュー PDF を取得し、
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


def fetch_pdf_urls() -> list[str]:
    """メニューページをスクレイピングし、掲載中の全 PDF リンクを抽出する。"""
    logger.info("メニューページを取得中: %s", MENU_PAGE_URL)
    resp = httpx.get(MENU_PAGE_URL, follow_redirects=True, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    pdf_urls: list[str] = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if href.lower().endswith(".pdf"):
            full_url = urljoin(MENU_PAGE_URL, href)
            if full_url not in pdf_urls:
                pdf_urls.append(full_url)

    logger.info("PDF リンクを %d 件検出", len(pdf_urls))
    return pdf_urls


def _url_to_filename(url: str) -> str:
    """URL からファイル名を生成する。日本語ファイル名はデコードして保持。"""
    decoded = unquote(url.split("/")[-1])
    return re.sub(r"[^\w\-.\u3000-\u9fff\uff00-\uffef]", "_", decoded)


def download_pdf(url: str, dest_dir: Path | None = None) -> Path:
    """単一の PDF をダウンロードし、ローカルパスを返す。既に存在すればスキップ。"""
    dest_dir = dest_dir or IMG_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    filename = _url_to_filename(url)
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


def download_all_menus(dest_dir: Path | None = None) -> list[Path]:
    """メニューページから全 PDF をダウンロードし、パスのリストを返す。"""
    pdf_urls = fetch_pdf_urls()
    if not pdf_urls:
        logger.warning("メニュー PDF が見つかりませんでした。")
        return []

    downloaded: list[Path] = []
    for url in pdf_urls:
        try:
            path = download_pdf(url, dest_dir)
            downloaded.append(path)
        except Exception as e:
            logger.error("ダウンロード失敗 (%s): %s", url, e)

    logger.info("合計 %d 件の PDF を取得しました。", len(downloaded))
    return downloaded
