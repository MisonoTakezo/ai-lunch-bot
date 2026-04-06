"""すみよしランチ MCP サーバー

MCPツール:
  - get_lunch_menu   — 日付指定でメニュー取得
  - search_menu      — キーワードでメニュー検索
  - list_all_menus   — 全メニュー一覧
  - place_order      — 注文実行
  - cancel_order     — 注文取り消し
  - get_order_status — 注文状況確認
  - update_menu_data — メニューデータ更新（PDF DL → OCR → JSON）
"""

import logging
import re
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP

from lunch_bot.downloader import download_all_menus
from lunch_bot.ocr import load_menu_data, ocr_all_menus, save_menu_data
from lunch_bot.order import cancel_order as _cancel_order
from lunch_bot.order import get_monthly_orders as _get_monthly_orders
from lunch_bot.order import get_order_status as _get_order_status
from lunch_bot.order import place_order as _place_order

logger = logging.getLogger(__name__)

# stdio 用デフォルトインスタンス
mcp = FastMCP("LunchBot")


def create_mcp(host: str = "127.0.0.1", port: int = 8765) -> FastMCP:
    """SSE 用に host/port を指定した FastMCP インスタンスを生成する。

    ツールはデフォルトの mcp インスタンスに登録済みなので、
    同じツールを新インスタンスにコピーする。
    """
    new_mcp = FastMCP("LunchBot", host=host, port=port)
    # デフォルトインスタンスからツールを引き継ぐ
    new_mcp._tool_manager = mcp._tool_manager
    return new_mcp


# ─────────────────────────── helpers ───────────────────────────


def _load_menu() -> list[dict]:
    return load_menu_data()


def _ensure_menu_for_date(target_date: str) -> list[dict]:
    """指定日付のメニューがなければ、PDFダウンロード→OCRを実行してデータを更新する。

    Args:
        target_date: YYYY-MM-DD 形式の日付

    Returns:
        更新後のメニューリスト
    """
    menu_list = load_menu_data()

    # 該当日付があればそのまま返す
    if any(item["date"] == target_date for item in menu_list):
        return menu_list

    # 日付をパース
    try:
        target = datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        return menu_list  # パース失敗ならそのまま返す

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # 過去または30日より先の未来は更新しない
    if target < today or target > today + timedelta(days=30):
        return menu_list

    # PDF ダウンロード → OCR 実行
    logger.info("📥 メニューデータを自動更新中 (対象: %s)...", target_date)
    try:
        pdf_paths = download_all_menus()
        if pdf_paths:
            new_menus = ocr_all_menus(pdf_paths)
            if new_menus:
                save_menu_data(new_menus)
                logger.info("✅ メニューデータを更新しました (%d 日分)", len(new_menus))
                return new_menus
    except Exception as e:
        logger.warning("⚠️ メニューデータの自動更新に失敗: %s", e)

    return menu_list


def _resolve_date_query(query: str) -> str | None:
    """自然言語の日付表現を YYYY-MM-DD に変換する。"""
    today = datetime.now()

    # 直接日付形式
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d", "%m月%d日"):
        try:
            dt = datetime.strptime(query.strip(), fmt)
            if dt.year == 1900:
                dt = dt.replace(year=today.year)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # 相対日付
    q = query.strip()
    if q in ("今日", "きょう"):
        return today.strftime("%Y-%m-%d")
    if q in ("明日", "あした", "あす"):
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if q in ("明後日", "あさって"):
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")

    # 曜日指定 (次の〇曜日 / 来週の〇曜日)
    weekdays = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}
    for name, wd in weekdays.items():
        if name in q and "曜" in q:
            days_ahead = (wd - today.weekday()) % 7
            if days_ahead == 0 and "来週" in q:
                days_ahead = 7
            elif "来週" in q:
                days_ahead += 7
            return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    return None


# ─────────────────────────── MCP tools ───────────────────────────


@mcp.tool()
def get_lunch_menu(date_str: str) -> str:
    """指定された日付のランチメニューを取得します。

    Args:
        date_str: 日付 (YYYY-MM-DD, YYYY/MM/DD, M/D, "今日", "明日", "来週の月曜日" など)
    """
    target = _resolve_date_query(date_str) or date_str.strip()

    # 該当日付がなければ自動でPDFダウンロード→OCRを試みる
    menu_list = _ensure_menu_for_date(target)

    if not menu_list:
        return "メニューデータが見つかりません。先にパイプラインを実行してください。"

    for item in menu_list:
        if item["date"] == target:
            return (
                f"📅 {target} のランチメニュー\n"
                f"🍱 あいランチ: {item['ai_lunch']}\n"
                f"🐟 和風ランチ: {item['wafu_lunch']}"
            )

    available = ", ".join(i["date"] for i in menu_list)
    return f"{target} のメニューは見つかりませんでした。\n利用可能な日付: {available}"


@mcp.tool()
def search_menu(query: str) -> str:
    """メニューをキーワードで検索します。料理名、食材、日付などで検索できます。

    Args:
        query: 検索キーワード (例: "フライ", "ハンバーグ", "来週", "2月10日")
    """
    # 日付として解決を試みる
    resolved = _resolve_date_query(query)
    if resolved:
        # 該当日付がなければ自動でPDFダウンロード→OCRを試みる
        menu_list = _ensure_menu_for_date(resolved)
        if not menu_list:
            return "メニューデータが見つかりません。"

        for item in menu_list:
            if item["date"] == resolved:
                return (
                    f"📅 {resolved} のランチメニュー\n"
                    f"🍱 あいランチ: {item['ai_lunch']}\n"
                    f"🐟 和風ランチ: {item['wafu_lunch']}"
                )
        return f"{resolved} のメニューは見つかりませんでした。"

    # キーワード検索
    menu_list = _load_menu()
    if not menu_list:
        return "メニューデータが見つかりません。"

    keywords = query.strip().split()
    results: list[str] = []

    for item in menu_list:
        combined = f"{item['ai_lunch']} {item['wafu_lunch']}"
        if all(kw.lower() in combined.lower() for kw in keywords):
            matched = []
            if any(kw.lower() in item["ai_lunch"].lower() for kw in keywords):
                matched.append(f"  🍱 あいランチ: {item['ai_lunch']}")
            if any(kw.lower() in item["wafu_lunch"].lower() for kw in keywords):
                matched.append(f"  🐟 和風ランチ: {item['wafu_lunch']}")
            results.append(f"📅 {item['date']}\n" + "\n".join(matched))

    if results:
        return f"「{query}」の検索結果 ({len(results)} 件):\n\n" + "\n\n".join(results)

    return f"「{query}」に一致するメニューは見つかりませんでした。"


@mcp.tool()
def list_all_menus() -> str:
    """登録されている全てのランチメニュー一覧を表示します。"""
    menu_list = _load_menu()
    if not menu_list:
        return "メニューデータが見つかりません。"

    lines = [f"📋 全メニュー一覧 ({len(menu_list)} 日分)\n"]
    for item in menu_list:
        lines.append(
            f"📅 {item['date']}\n"
            f"  🍱 あいランチ: {item['ai_lunch']}\n"
            f"  🐟 和風ランチ: {item['wafu_lunch']}"
        )
    return "\n\n".join(lines)


@mcp.tool()
def place_order(date: str, menu_type: str, quantity: int = 1) -> str:
    """ランチを注文します。

    Args:
        date: 注文日 (YYYY-MM-DD, "今日", "明日" など)
        menu_type: メニュー種別 ("和風", "あいランチ", "その他")
        quantity: 注文数 (デフォルト: 1)
    """
    order_date = _resolve_date_query(date) or date
    try:
        result = _place_order(order_date, menu_type, quantity)
        return f"{'✅' if result.success else '❌'} {result.message}"
    except Exception as e:
        return f"❌ 注文に失敗しました: {e}"


@mcp.tool()
def cancel_order(date: str, menu_type: str) -> str:
    """ランチの注文を取り消します。

    Args:
        date: 取り消し対象日 (YYYY-MM-DD, "今日", "明日" など)
        menu_type: メニュー種別 ("和風", "あいランチ", "その他")
    """
    order_date = _resolve_date_query(date) or date
    try:
        result = _cancel_order(order_date, menu_type)
        return f"{'✅' if result.success else '❌'} {result.message}"
    except Exception as e:
        return f"❌ 注文の取り消しに失敗しました: {e}"


@mcp.tool()
def get_order_status(date_str: str) -> str:
    """指定された日付、週、または月全体の注文状況を確認します。
    特定の日の注文内容や、今週/来週/今月の注文一覧を確認できます。

    Args:
        date_str: 日付 (YYYY-MM-DD, "今日", "明日", "今週", "来週", "今月", "来月" など)
    """
    today = datetime.now()

    # 月全体の照会
    month_query = _resolve_month_query(date_str)
    if month_query:
        year, month = month_query
        try:
            statuses = _get_monthly_orders(year, month)
        except Exception as e:
            return f"❌ 注文状況の取得に失敗しました: {e}"

        if not statuses:
            return f"📅 {year}年{month}月の注文データはありません。"

        lines = [f"📋 {year}年{month}月の注文状況\n"]
        has_order = False
        for s in statuses:
            if s.holiday:
                continue  # 休業日は省略
            if s.orders:
                has_order = True
                order_str = ", ".join(f"{k} {v}個" for k, v in s.orders.items())
                lines.append(f"  📅 {s.date}: {order_str}")
            # 注文なしの日は省略
        if not has_order:
            lines.append("  注文はありません。")
        return "\n".join(lines)

    # 週の照会（今週/来週/再来週）
    week_dates = _resolve_week_query(date_str)
    if week_dates:
        week_labels = {"今週": "今週", "こんしゅう": "今週", "来週": "来週", "らいしゅう": "来週", "再来週": "再来週", "さらいしゅう": "再来週"}
        label = week_labels.get(date_str.strip(), date_str)
        lines = [f"📋 {label}の注文状況 ({week_dates[0]} 〜 {week_dates[-1]})\n"]
        has_order = False
        for date in week_dates:
            try:
                status = _get_order_status(date)
                if status.holiday:
                    continue  # 休業日は省略
                if status.orders:
                    has_order = True
                    order_str = ", ".join(f"{k} {v}個" for k, v in status.orders.items())
                    lines.append(f"  📅 {date}: {order_str}")
                # 注文なしの日は省略
            except Exception:
                continue  # エラーの日はスキップ
        if not has_order:
            lines.append("  注文はありません。")
        return "\n".join(lines)

    # 特定日の照会
    target = _resolve_date_query(date_str) or date_str.strip()
    try:
        status = _get_order_status(target)
    except Exception as e:
        return f"❌ 注文状況の取得に失敗しました: {e}"

    if not status.orders:
        return f"📅 {target} の注文はありません。"

    order_str = ", ".join(f"{k} {v}個" for k, v in status.orders.items())
    return f"📅 {target} の注文状況: {order_str}"


@mcp.tool()
def update_menu_data(skip_download: bool = False) -> str:
    """メニューデータを更新します（PDF ダウンロード → Gemini OCR → JSON 保存）。

    Args:
        skip_download: True の場合、PDF ダウンロードをスキップし既存 PDF で OCR のみ実行
    """
    try:
        pdf_paths = None
        if not skip_download:
            pdf_paths = download_all_menus()
            if not pdf_paths:
                return "⚠️ PDF が取得できませんでした。既存データで OCR を試みます。"

        menu_list = ocr_all_menus(pdf_paths if not skip_download else None)
        if menu_list:
            save_menu_data(menu_list)
            dates = [item["date"] for item in menu_list]
            return (
                f"✅ メニューデータを更新しました ({len(menu_list)} 日分)\n"
                f"期間: {dates[0]} 〜 {dates[-1]}"
            )
        return "⚠️ OCR 結果が空でした。既存データは変更されていません。"
    except Exception as e:
        return f"❌ メニューデータの更新に失敗しました: {e}"


def _resolve_week_query(query: str) -> list[str] | None:
    """週の照会クエリを平日（月〜金）の日付リストに解決する。"""
    today = datetime.now()
    q = query.strip()

    # 週のオフセットを決定
    if q in ("今週", "こんしゅう"):
        week_offset = 0
    elif q in ("来週", "らいしゅう"):
        week_offset = 1
    elif q in ("再来週", "さらいしゅう"):
        week_offset = 2
    else:
        return None

    # 今週の月曜日を基準に計算
    days_since_monday = today.weekday()  # 月=0, 火=1, ...
    monday = today - timedelta(days=days_since_monday)
    monday += timedelta(weeks=week_offset)

    # 月〜金の日付リストを生成
    return [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(5)]


def _resolve_month_query(query: str) -> tuple[int, int] | None:
    """月の照会クエリを (year, month) に解決する。"""
    today = datetime.now()
    q = query.strip()

    if q in ("今月", "こんげつ"):
        return (today.year, today.month)
    if q in ("来月", "らいげつ"):
        nxt = today.replace(day=1) + timedelta(days=32)
        return (nxt.year, nxt.month)
    if q in ("先月", "せんげつ"):
        prev = today.replace(day=1) - timedelta(days=1)
        return (prev.year, prev.month)

    # "2月", "12月" etc.
    m = re.match(r"(\d{1,2})月$", q)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            return (today.year, month)

    # "2026年2月" etc.
    m = re.match(r"(\d{4})年(\d{1,2})月$", q)
    if m:
        return (int(m.group(1)), int(m.group(2)))

    return None
