import os
import base64
import io
import json
import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
WEATHER_APP_BASE_URL = os.getenv("WEATHER_APP_BASE_URL", "https://grudproject-weather-app.hf.space").rstrip("/")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", os.getenv("RENDER_BOT_URL", "")).strip().rstrip("/")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in environment variables")
if not TELEGRAM_CHAT_ID:
    raise RuntimeError("Missing TELEGRAM_CHAT_ID in environment variables")

TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

COMMAND_MENU_TEXT = (
    "🌿 Smart Greenhouse Bot is running.\n\n"
    "Commands:\n"
    "/readings - current sensor + disease report\n"
    "/report - full report with sensors + disease + weather\n"
    "/weather - weather information\n"
    "/disease - latest disease status\n"
    "/history - all nodes sensor + disease history\n"
    "/daily - send daily report now"
)

COMMAND_MENU_BLOCK = "\n\n━━━━━━━━━━━━━━\n📌 Commands:\n" + "\n".join(COMMAND_MENU_TEXT.splitlines()[3:])


def tg_post(method, data=None, files=None, timeout=30):
    url = f"{TG_API}/{method}"
    r = requests.post(url, data=data or {}, files=files, timeout=timeout)
    try:
        return r.json()
    except Exception:
        return {"ok": False, "description": r.text}


def tg_get(method, params=None, timeout=30):
    url = f"{TG_API}/{method}"
    r = requests.get(url, params=params or {}, timeout=timeout)
    try:
        return r.json()
    except Exception:
        return {"ok": False, "description": r.text}


def set_telegram_webhook():
    if not PUBLIC_BASE_URL:
        return {
            "ok": False,
            "description": "PUBLIC_BASE_URL is missing. Add PUBLIC_BASE_URL=https://smart-greenhouse-telegram-bot.onrender.com in Render environment variables."
        }

    webhook_url = f"{PUBLIC_BASE_URL}/telegram-webhook"
    return tg_post("setWebhook", {
        "url": webhook_url,
        "drop_pending_updates": "true"
    }, timeout=30)


def get_webhook_info():
    return tg_get("getWebhookInfo", timeout=30)


def send_message(text):
    text = str(text)
    chunks = [text[i:i+3800] for i in range(0, len(text), 3800)] or [""]
    ok_all = True
    errors = []

    for part in chunks:
        js = tg_post("sendMessage", {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": part
        }, timeout=30)

        if not js.get("ok"):
            ok_all = False
            errors.append(js)
            print("sendMessage error:", js)

    return ok_all, errors


def send_photo_data_url(data_url, caption=""):
    try:
        if not data_url:
            return False, "Empty image"

        if "," in data_url:
            _, encoded = data_url.split(",", 1)
        else:
            encoded = data_url

        image_bytes = base64.b64decode(encoded)
        bio = io.BytesIO(image_bytes)
        bio.name = "yolo_result.jpg"

        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": str(caption)[:1024]
        }
        files = {
            "photo": ("yolo_result.jpg", bio, "image/jpeg")
        }

        js = tg_post("sendPhoto", data=data, files=files, timeout=60)

        if not js.get("ok"):
            print("sendPhoto error:", js)
            return False, js

        return True, "OK"

    except Exception as e:
        print("sendPhoto exception:", repr(e))
        return False, str(e)


def send_yolo_alert_payload(payload):
    message = payload.get("message", "")
    if not message:
        message = "🦠 AI TOMATO DISEASE DETECTION ALERT\n\n" + json.dumps(
            payload.get("final_summary", {}),
            ensure_ascii=False,
            indent=2
        )

    ok_msg, msg_errors = send_message(message)

    photos_sent = 0
    photo_errors = []

    images = payload.get("images") or payload.get("prediction_images") or []
    for i, item in enumerate(images, start=1):
        if isinstance(item, dict):
            img = item.get("image", "")
            caption = item.get("caption", f"YOLO annotated image {i}")
        else:
            img = str(item)
            caption = f"YOLO annotated image {i}"

        ok, err = send_photo_data_url(img, caption)
        if ok:
            photos_sent += 1
        else:
            photo_errors.append({"image": i, "error": str(err)})

    return {
        "message_sent": ok_msg,
        "message_errors": msg_errors,
        "photos_sent": photos_sent,
        "photos_total": len(images),
        "photo_errors": photo_errors
    }


def get_json(path, timeout=90):
    url = f"{WEATHER_APP_BASE_URL}{path}"
    r = requests.get(url, timeout=timeout)
    try:
        return r.json()
    except Exception:
        return {"error": r.text}


def pretty_json(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


def get_report_message(endpoint):
    js = get_json(endpoint, timeout=120)
    msg = js.get("message")
    if msg:
        return msg
    return pretty_json(js)


def handle_command(text):
    text = (text or "").strip()

    if text in ["/start", "/help"]:
        return COMMAND_MENU_TEXT

    if text == "/readings":
        return get_report_message("/send-readings")

    if text in ["/report", "/daily"]:
        return get_report_message("/send-report")

    if text == "/history":
        return get_report_message("/send-history")

    if text == "/weather":
        js = get_json("/weather")
        return "🌤 WEATHER INFO\n\n" + pretty_json(js)

    if text == "/disease":
        # Use message if Weather_app /disease returns one later; otherwise JSON.
        js = get_json("/disease")
        if isinstance(js, dict) and js.get("message"):
            return js["message"]
        return "🦠 LATEST DISEASE STATUS\n\n" + pretty_json(js)

    if text == "/sensors":
        js = get_json("/sensors")
        return "🌿 SENSORS DATA\n\n" + pretty_json(js)

    return "Unknown command. Send /help to see available commands."


def handle_telegram_update(update):
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat", {})
    chat_id = str(chat.get("id", ""))

    if chat_id != str(TELEGRAM_CHAT_ID):
        print("Ignoring chat_id:", chat_id)
        return {"ignored": True, "chat_id": chat_id}

    text = msg.get("text", "")
    print("Webhook command:", text)

    reply = handle_command(text)
    ok, errors = send_message(reply)

    # Send commands menu as a separate message after every command response,
    # except /start and /help because they already return the menu.
    menu_ok = True
    menu_errors = []
    if text not in ["/start", "/help"]:
        menu_ok, menu_errors = send_message(COMMAND_MENU_TEXT)

    return {
        "ignored": False,
        "command": text,
        "reply_sent": ok,
        "errors": errors,
        "menu_sent": menu_ok,
        "menu_errors": menu_errors,
    }
