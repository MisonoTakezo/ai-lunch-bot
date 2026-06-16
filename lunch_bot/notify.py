"""Slack 通知モジュール — 今日の注文状況を Slack に通知する"""

import logging
from datetime import datetime, timedelta

import httpx

from lunch_bot.config import get_secret
from lunch_bot.ocr import load_menu_data
from lunch_bot.order import DayOrderStatus, get_monthly_orders, get_order_status

logger = logging.getLogger(__name__)

JP_WEEKDAYS = "月火水木金土日"


def _get_webhook_url() -> str:
    return get_secret("SLACK_WEBHOOK_URL")


def _build_message(today: str) -> str:
    """今日の注文状況からSlack通知メッセージを組み立てる。"""
    status = get_order_status(today)

    if not status.orders:
        return "🍱 今日のランチ：注文なし"

    # 注文しているメニュー名を取得（和風ランチ or あいランチ）
    menu_name = list(status.orders.keys())[0]

    # メニュー詳細を取得
    menu_list = load_menu_data()
    detail = ""
    for item in menu_list:
        if item["date"] == today:
            if "和風" in menu_name and item.get("wafu_lunch"):
                detail = item["wafu_lunch"]
            elif "あい" in menu_name and item.get("ai_lunch"):
                detail = item["ai_lunch"]
            break

    if detail:
        return f"🍱 今日のランチ：{menu_name}（{detail}）"
    return f"🍱 今日のランチ：{menu_name}"


def _build_next_monday_reminder(friday: datetime) -> str | None:
    """金曜日に、来週月曜（休業日なら次の営業日）の注文有無を確認する。

    未注文なら確認メッセージを、注文済み・取得失敗・該当日なしなら None を返す。
    """
    monday = friday + timedelta(days=3)
    cached: dict[tuple[int, int], list[DayOrderStatus]] = {}

    for offset in range(5):  # 月〜金まで最大5日探索
        target = monday + timedelta(days=offset)
        key = (target.year, target.month)
        if key not in cached:
            try:
                cached[key] = get_monthly_orders(target.year, target.month)
            except Exception as e:
                logger.warning("月次注文状況の取得に失敗: %s", e)
                return None

        target_str = target.strftime("%Y-%m-%d")
        st = next((s for s in cached[key] if s.date == target_str), None)
        if st is None:
            # 月のテーブルに行がない（土日など） → 次の日へ
            continue
        if st.holiday:
            # 休業日 → 次の営業日を確認
            continue
        # 来週最初の営業日
        if st.orders:
            return None
        weekday_jp = JP_WEEKDAYS[target.weekday()]
        mmdd = f"{target.month}/{target.day}"
        return (
            f"⚠️ 来週{weekday_jp}曜（{mmdd}）の注文がありません。"
            "注文しなくて大丈夫ですか？"
        )

    return None


def send_notification() -> None:
    """今日の注文状況を Slack に通知する。"""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    message = _build_message(today)

    # 金曜日は来週月曜（休業日なら次の営業日）の注文有無も確認
    if now.weekday() == 4:
        reminder = _build_next_monday_reminder(now)
        if reminder:
            message = f"{message}\n{reminder}"

    webhook_url = _get_webhook_url()

    logger.info("Slack 通知送信: %s", message)
    resp = httpx.post(webhook_url, json={"text": message}, timeout=10)
    resp.raise_for_status()
    logger.info("Slack 通知完了 (status=%d)", resp.status_code)
