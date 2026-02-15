"""OCR モジュール 
Gemini API で PDF からメニュー JSON を生成する

google-genai を使い、PDF を直接アップロードして OCR → JSON 変換する。
複数 PDF に対応し、結果をマージして重複日付は除去する。
"""

import io
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from google import genai

from lunch_bot.config import IMG_DIR, MENU_FILE

logger = logging.getLogger(__name__)

MENU_EXTRACTION_PROMPT = """\
この PDF はランチメニュー表です。
全ての日付について、あいランチと和風ランチの情報を抽出し、以下のフォーマットの JSON 配列で出力してください。

ルール:
- YYYY が取得できない場合は {current_year} を使用してください。
- 土曜・日曜・祝日のメニューは含めないでください。
- JSON のみを出力し、マークダウンのコードブロック (```) は使わないでください。

フォーマット:
[
  {{
    "date": "YYYY-MM-DD",
    "ai_lunch": "おかず1, おかず2, ...",
    "wafu_lunch": "おかず1, おかず2, ..."
  }}
]
"""


def _get_client() -> genai.Client:
    """Gemini API クライアントを取得する。"""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY が .env に設定されていません。")
    return genai.Client(api_key=api_key)


def ocr_pdf(client: genai.Client, pdf_path: Path) -> list[dict]:
    """単一 PDF を Gemini で OCR し、メニューリストを返す。"""
    logger.info("OCR 処理中: %s", pdf_path.name)

    prompt = MENU_EXTRACTION_PROMPT.format(current_year=datetime.now().year)

    # ファイルをアップロード (日本語ファイル名対応のためバイナリで渡す)
    uploaded = client.files.upload(
        file=io.BytesIO(pdf_path.read_bytes()),
        config={"mime_type": "application/pdf"},
    )
    logger.info("Gemini にアップロード完了: %s", uploaded.name)

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[uploaded, prompt],
    )

    raw_text = response.text.strip()

    # マークダウンブロックが含まれている場合は除去してJSON部分だけ抽出する
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
    if raw_text.endswith("```"):
        raw_text = raw_text.rsplit("```", 1)[0]
    raw_text = raw_text.strip()

    try:
        menu_list = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error("JSON パース失敗: %s\n---\n%s", e, raw_text[:500])
        raise

    logger.info("  → %d 日分のメニューを抽出", len(menu_list))
    return menu_list


def ocr_all_menus(pdf_paths: list[Path] | None = None) -> list[dict]:
    """複数 PDF を OCR し、日付で重複排除したメニューリストを返す。

    pdf_paths が未指定の場合、IMG_DIR 配下の全 PDF を処理する。
    """
    if pdf_paths is None:
        pdf_paths = sorted(IMG_DIR.glob("*.pdf"))

    if not pdf_paths:
        logger.warning("処理対象の PDF がありません。")
        return []

    client = _get_client()
    all_menus: dict[str, dict] = {}

    for pdf_path in pdf_paths:
        try:
            menus = ocr_pdf(client, pdf_path)
            for item in menus:
                # 後勝ちで dedup
                all_menus[item["date"]] = item
        except Exception as e:
            logger.error("OCR 失敗 (%s): %s", pdf_path.name, e)

    result = sorted(all_menus.values(), key=lambda x: x["date"])
    logger.info("合計 %d 日分のメニューデータを生成", len(result))
    return result


def save_menu_data(menu_list: list[dict], output_path: Path | None = None) -> Path:
    """メニューデータを JSON ファイルに保存する。"""
    output_path = output_path or MENU_FILE
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(menu_list, f, ensure_ascii=False, indent=2)
    logger.info("メニューデータを保存: %s (%d 件)", output_path, len(menu_list))
    return output_path


def load_menu_data(path: Path | None = None) -> list[dict]:
    """保存済みメニューデータを読み込む。"""
    path = path or MENU_FILE
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
