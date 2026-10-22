# -*- coding: utf-8 -*-
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

BYBIT_URL = "https://api.bybit.com/v5/market/tickers?category=spot"
STATE_FILE = Path("state.json")

DEFAULT_RANGES = {
    "AVAXUSDT": {"low": 9.23, "high": 11.86},
    "ETHUSDT": {"low": 2124.77, "high": 2596.96},
    "SOLUSDT": {"low": 90.76, "high": 122.80},
    "STXUSDT": {"low": 0.3528, "high": 0.4536},
}

def request_json(url, form=None):
    headers = {"User-Agent": "BybitGridMonitor/1.0"}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))

def send_telegram(token, chat_id, message):
    result = request_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {"chat_id": chat_id, "text": message}
    )
    if not result.get("ok"):
        raise RuntimeError("Telegram error: " + str(result))

def get_ranges():
    raw = os.getenv("RANGES_JSON", "").strip()
    source = json.loads(raw) if raw else DEFAULT_RANGES
    ranges = {}
    for symbol, limits in source.items():
        low = float(limits["low"])
        high = float(limits["high"])
        if low <= 0 or high <= low:
            raise ValueError("Неверный диапазон: " + symbol)
        ranges[symbol.upper()] = {"low": low, "high": high}
    return ranges

def get_prices():
    data = request_json(BYBIT_URL)
    if data.get("retCode") != 0:
        raise RuntimeError("Ошибка Bybit: " + str(data))
    return {
        item["symbol"]: float(item["lastPrice"])
        for item in data.get("result", {}).get("list", [])
        if item.get("symbol") and item.get("lastPrice")
    }

def describe(symbol, price, limits):
    low, high = limits["low"], limits["high"]
    raw_pct = (price - low) / (high - low) * 100
    pct = max(0.0, min(100.0, raw_pct))

    if price <= low:
        label, edge = "НИЖНЯЯ ГРАНИЦА ИЛИ НИЖЕ", "LOW"
    elif price >= high:
        label, edge = "ВЕРХНЯЯ ГРАНИЦА ИЛИ ВЫШЕ", "HIGH"
    elif pct <= 5:
        label, edge = "почти у низа", "IN"
    elif pct < 45:
        label, edge = "нижняя часть диапазона", "IN"
    elif pct <= 55:
        label, edge = "середина диапазона", "IN"
    elif pct < 95:
        label, edge = "верхняя часть диапазона", "IN"
    else:
        label, edge = "почти у верха", "IN"

    message = (
        f"{symbol}: {price:g} USDT\n"
        f"Границы: {low:g} — {high:g} USDT\n"
        f"Положение: {pct:.1f}% — {label}"
    )
    signature = {"band": int(raw_pct // 5), "edge": edge}
    return message, signature

def read_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"symbols": {}, "last_report": 0}

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError(
            "Добавьте TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в GitHub Secrets."
        )

    ranges = get_ranges()
    old_state = read_state()
    prices = get_prices()
    now = time.time()
    new_signatures = dict(old_state.get("symbols", {}))
    lines = []
    changed = []

    for symbol, limits in ranges.items():
        if symbol not in prices:
            lines.append(f"{symbol}: цена не получена от Bybit")
            continue
        line, signature = describe(symbol, prices[symbol], limits)
        lines.append(line)
        if old_state.get("symbols", {}).get(symbol) != signature:
            changed.append(line)
        new_signatures[symbol] = signature

    last_report = float(old_state.get("last_report", 0))
    report_due = not last_report or now - last_report >= 15 * 60

    if report_due:
        send_telegram(
            token, chat_id,
            "📊 Bybit Grid Monitor — положение цены\n\n" + "\n\n".join(lines)
        )
        last_report = now
    elif changed:
        send_telegram(
            token, chat_id,
            "🔔 Bybit Grid Monitor — изменение диапазона\n\n"
            + "\n\n".join(changed)
        )

    STATE_FILE.write_text(
        json.dumps({
            "symbols": new_signatures,
            "last_report": last_report
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )
    print(datetime.now(timezone.utc).isoformat(), "Проверка завершена.")

if __name__ == "__main__":
    main()
