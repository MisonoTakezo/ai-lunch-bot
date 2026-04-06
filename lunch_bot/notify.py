"""Slack 通知モジュール — 今日の注文状況を Slack に通知する"""

import logging
from datetime import datetime

import httpx

from lunch_bot.config import get_secret
from lunch_bot.ocr import load_menu_data
from lunch_bot.order import get_order_status

logger = logging.getLogger(__name__)


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


def send_notification() -> None:
    """今日の注文状況を Slack に通知する。"""
    today = datetime.now().strftime("%Y-%m-%d")
    message = _build_message(today)
    webhook_url = _get_webhook_url()

    logger.info("Slack 通知送信: %s", message)
    resp = httpx.post(webhook_url, json={"text": message}, timeout=10)
    resp.raise_for_status()
    logger.info("Slack 通知完了 (status=%d)", resp.status_code)
