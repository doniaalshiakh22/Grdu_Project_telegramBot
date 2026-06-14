import os
import time
import threading

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import telegram_bot_local

app = FastAPI(title="Smart Greenhouse Telegram Webhook Bot")

ENABLE_WEATHER_PING_LOOP = os.getenv("ENABLE_WEATHER_PING_LOOP", "false").strip().lower() in ["1", "true", "yes", "on"]
WEATHER_PING_INTERVAL_SECONDS = int(os.getenv("WEATHER_PING_INTERVAL_SECONDS", "60"))
_ping_loop_started = False


def weather_ping_loop():
    while True:
        try:
            result = telegram_bot_local.ping_weather_check_sensors()
            print("Weather /check-sensors ping:", result)
        except Exception as e:
            print("Weather /check-sensors ping error:", repr(e))
        time.sleep(max(30, WEATHER_PING_INTERVAL_SECONDS))


@app.on_event("startup")
def startup():
    global _ping_loop_started

    result = telegram_bot_local.set_telegram_webhook()
    print("setWebhook:", result)
    print("getWebhookInfo:", telegram_bot_local.get_webhook_info())

    # Optional background ping while Render is awake.
    # For reliable alerts on free tiers, use an external uptime monitor or Render cron
    # to ping Weather App /check-sensors every 1 minute.
    if ENABLE_WEATHER_PING_LOOP and not _ping_loop_started:
        _ping_loop_started = True
        t = threading.Thread(target=weather_ping_loop, daemon=True)
        t.start()
        print("Weather ping loop started.")


@app.get("/")
def root():
    return {
        "status": "running",
        "service": "Smart Greenhouse Telegram Webhook Bot",
        "commands": ["/start", "/readings", "/report", "/weather", "/disease", "/daily"],
        "telegram_webhook": "/telegram-webhook",
        "yolo_endpoint": "/yolo-alert",
        "weather_check_sensors_proxy": "/ping-weather-sensors",
        "history_enabled": False,
        "important": "For reliable automatic alerts, ping https://grudproject-weather-app.hf.space/check-sensors every 1 minute from Render cron or an uptime monitor."
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "mode": "webhook",
        "history_enabled": False,
        "weather_ping_loop_enabled": ENABLE_WEATHER_PING_LOOP,
        "weather_ping_interval_seconds": WEATHER_PING_INTERVAL_SECONDS,
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
    """
    Optional proxy endpoint.
    You can ping this Render endpoint, and it will call Weather App /check-sensors.
    Direct ping is also okay:
    https://grudproject-weather-app.hf.space/check-sensors
    """
    return telegram_bot_local.ping_weather_check_sensors()


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
