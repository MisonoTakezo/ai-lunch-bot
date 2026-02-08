"""CLI エントリポイント

1コマンドで「メニュー PDF ダウンロード → OCR → MCP サーバー起動」を実行する。
"""

import argparse
import logging
import sys

from lunch_bot.downloader import download_all_menus
from lunch_bot.ocr import load_menu_data, ocr_all_menus, save_menu_data

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ─────────────────────────── pipeline ───────────────────────────


def run_pipeline(*, skip_download: bool = False, skip_ocr: bool = False) -> None:
    """PDF DL → OCR → menu_data.json 生成のパイプラインを実行する。"""

    pdf_paths = None

    if not skip_download:
        logger.info("=== ステップ 1: メニュー PDF ダウンロード ===")
        pdf_paths = download_all_menus()
        if not pdf_paths:
            logger.warning("PDF が取得できませんでした。既存データで続行します。")
    else:
        logger.info("=== ステップ 1: PDF ダウンロードをスキップ ===")

    if not skip_ocr:
        logger.info("=== ステップ 2: Gemini OCR (PDF → JSON) ===")
        menu_list = ocr_all_menus(pdf_paths if not skip_download else None)
        if menu_list:
            save_menu_data(menu_list)
        else:
            logger.warning("OCR 結果が空です。既存データで続行します。")
    else:
        logger.info("=== ステップ 2: OCR をスキップ ===")

    data = load_menu_data()
    if data:
        logger.info(
            "メニューデータ: %d 日分 (%s 〜 %s)",
            len(data),
            data[0]["date"],
            data[-1]["date"],
        )
    else:
        logger.warning("メニューデータがありません。サーバーは起動しますがメニュー参照できません。")


# ─────────────────────────── server ───────────────────────────


def start_server(
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """MCP サーバーを起動する。"""
    logger.info("=== ステップ 3: MCP サーバー起動 (%s) ===", transport)

    if transport == "stdio":
        from lunch_bot.server import mcp
        mcp.run(transport="stdio")
    elif transport == "sse":
        from lunch_bot.server import create_mcp
        sse_mcp = create_mcp(host=host, port=port)
        sse_mcp.run(transport="sse")
    else:
        logger.error("未対応のトランスポート: %s", transport)
        sys.exit(1)


# ─────────────────────────── main ───────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="🍱 すみよしランチ MCP サーバー",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
使用例:
  python -m lunch_bot                    PDF DL → OCR → stdio サーバー起動
  python -m lunch_bot --sse              SSE モードで起動
  python -m lunch_bot --sse --port 9000  SSE + ポート指定
  python -m lunch_bot --skip-ocr         既存 JSON でサーバー起動
  python -m lunch_bot --pipeline-only    パイプラインのみ (サーバー起動なし)
""",
    )

    transport_group = parser.add_argument_group("トランスポート")
    transport_group.add_argument(
        "--stdio", action="store_true", default=True, help="stdio モード (デフォルト)"
    )
    transport_group.add_argument("--sse", action="store_true", help="SSE モード")
    transport_group.add_argument("--host", default="127.0.0.1", help="SSE ホスト")
    transport_group.add_argument("--port", type=int, default=8765, help="SSE ポート")

    pipeline_group = parser.add_argument_group("パイプライン制御")
    pipeline_group.add_argument(
        "--skip-download", action="store_true", help="PDF ダウンロードをスキップ"
    )
    pipeline_group.add_argument(
        "--skip-ocr", action="store_true", help="OCR をスキップ (既存 JSON 使用)"
    )
    pipeline_group.add_argument(
        "--pipeline-only", action="store_true", help="パイプラインのみ実行"
    )

    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログ")

    args = parser.parse_args()
    _setup_logging(args.verbose)

    transport = "sse" if args.sse else "stdio"

    run_pipeline(skip_download=args.skip_download, skip_ocr=args.skip_ocr)

    if not args.pipeline_only:
        start_server(transport=transport, host=args.host, port=args.port)
