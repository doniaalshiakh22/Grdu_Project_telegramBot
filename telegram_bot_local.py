import os
import time
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import telegram_bot_local

app = FastAPI(title="Smart Greenhouse Telegram Webhook Bot")

ENABLE_WEATHER_PING_LOOP = os.getenv("ENABLE_WEATHER_PING_LOOP", "true").strip().lower() in ["1", "true", "yes", "on"]
WEATHER_PING_INTERVAL_SECONDS = int(os.getenv("WEATHER_PING_INTERVAL_SECONDS", "60"))

ENABLE_DAILY_REPORT_LOOP = os.getenv("ENABLE_DAILY_REPORT_LOOP", "true").strip().lower() in ["1", "true", "yes", "on"]
DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "8"))
DAILY_REPORT_MINUTE = int(os.getenv("DAILY_REPORT_MINUTE", "0"))
TIMEZONE_NAME = os.getenv("TIMEZONE_NAME", "Asia/Hebron")

try:
    LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)
except Exception:
    LOCAL_TZ = ZoneInfo("UTC")

_ping_loop_started = False
_daily_loop_started = False
_last_daily_key = ""


def weather_ping_loop():
    while True:
        try:
            result = telegram_bot_local.ping_weather_check_sensors()
            print("Weather /check-sensors ping:", result)
        except Exception as e:
            print("Weather /check-sensors ping error:", repr(e))
        time.sleep(max(30, WEATHER_PING_INTERVAL_SECONDS))


def daily_report_loop():
    global _last_daily_key
    while True:
        try:
            now = datetime.now(LOCAL_TZ)
            key = now.strftime("%Y-%m-%d")
            if now.hour == DAILY_REPORT_HOUR and now.minute == DAILY_REPORT_MINUTE and _last_daily_key != key:
                result = telegram_bot_local.send_daily_report()
                print("Daily report result:", result)
                _last_daily_key = key
        except Exception as e:
            print("daily_report_loop error:", repr(e))
        time.sleep(30)


@app.on_event("startup")
def startup():
    global _ping_loop_started, _daily_loop_started
    result = telegram_bot_local.set_telegram_webhook()
    print("setWebhook:", result)
    print("getWebhookInfo:", telegram_bot_local.get_webhook_info())

    if ENABLE_WEATHER_PING_LOOP and not _ping_loop_started:
        _ping_loop_started = True
        threading.Thread(target=weather_ping_loop, daemon=True).start()
        print("Weather ping loop started.")

    if ENABLE_DAILY_REPORT_LOOP and not _daily_loop_started:
        _daily_loop_started = True
        threading.Thread(target=daily_report_loop, daemon=True).start()
        print("Daily report loop started.")


@app.get("/")
def root():
    return {
        "status": "running",
        "service": "Smart Greenhouse Telegram Webhook Bot",
        "commands": ["/start", "/readings", "/report", "/weather", "/disease", "/camera", "/update_weather"],
        "telegram_webhook": "/telegram-webhook",
        "yolo_endpoint": "/yolo-alert",
        "weather_check_sensors_proxy": "/ping-weather-sensors",
        "daily_report_endpoint": "/send-daily-report",
        "daily_report_aliases": ["/send-daily-report", "/daily-report", "/send_daily_report"],
        "history_enabled": False,
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "mode": "webhook",
        "history_enabled": False,
        "weather_ping_loop_enabled": ENABLE_WEATHER_PING_LOOP,
        "weather_ping_interval_seconds": WEATHER_PING_INTERVAL_SECONDS,
        "daily_report_loop_enabled": ENABLE_DAILY_REPORT_LOOP,
        "daily_time": f"{DAILY_REPORT_HOUR:02d}:{DAILY_REPORT_MINUTE:02d}",
        "timezone": TIMEZONE_NAME,
    }


@app.get("/set-webhook")
def set_webhook():
    result = telegram_bot_local.set_telegram_webhook()
    info = telegram_bot_local.get_webhook_info()
    return {"setWebhook": result, "getWebhookInfo": info}


@app.get("/webhook-info")
def webhook_info():
    return telegram_bot_local.get_webhook_info()


@app.get("/ping-weather-sensors")
def ping_weather_sensors():
    return telegram_bot_local.ping_weather_check_sensors()


def _send_daily_report_response():
    return telegram_bot_local.send_daily_report()


@app.get("/send-daily-report")
def send_daily_report():
    return _send_daily_report_response()


@app.get("/daily-report")
def daily_report_alias():
    return _send_daily_report_response()


@app.get("/send_daily_report")
def send_daily_report_alias():
    return _send_daily_report_response()


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    try:
        update = await request.json()
        result = telegram_bot_local.handle_telegram_update(update)
        return {"ok": True, "result": result}
    except Exception as e:
        print("telegram_webhook error:", repr(e))
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.post("/yolo-alert")
async def yolo_alert(request: Request):
    try:
        payload = await request.json()
        result = telegram_bot_local.send_yolo_alert_payload(payload)
        return {
            "ok": bool(result.get("message_sent")) and result.get("photos_sent", 0) == result.get("photos_total", 0),
            "result": result
        }
    except Exception as e:
        print("yolo_alert error:", repr(e))
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})
