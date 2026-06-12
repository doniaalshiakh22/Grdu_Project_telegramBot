import os
import time
import base64
import io
import json
import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
WEATHER_APP_BASE_URL = os.getenv("WEATHER_APP_BASE_URL", "https://grudproject-weather-app.hf.space").rstrip("/")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in .env or Render environment variables")
if not TELEGRAM_CHAT_ID:
    raise RuntimeError("Missing TELEGRAM_CHAT_ID in .env or Render environment variables")

TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

last_update_id = None

COMMAND_MENU = (
    "\n\n━━━━━━━━━━━━━━\n"
    "📌 Commands:\n"
    "/readings - current sensor + disease report\n"
    "/report - full report with sensors + disease + weather\n"
    "/weather - weather information\n"
    "/disease - latest disease status\n"
    "/daily - send daily report now"
)


def add_menu(message):
    return str(message) + COMMAND_MENU


def tg_request(method, data=None, timeout=30):
    url = f"{TG_API}/{method}"
    r = requests.post(url, data=data or {}, timeout=timeout)
    try:
        js = r.json()
    except Exception:
        return {"ok": False, "description": r.text}
    return js


def send_message(text):
    text = str(text)
    chunks = [text[i:i+3800] for i in range(0, len(text), 3800)] or [""]
    ok_all = True
    errors = []

    for part in chunks:
        js = tg_request("sendMessage", {
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

        url = f"{TG_API}/sendPhoto"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": str(caption)[:1024]
        }
        files = {
            "photo": ("yolo_result.jpg", bio, "image/jpeg")
        }

        r = requests.post(url, data=data, files=files, timeout=60)
        js = r.json()

        if not js.get("ok"):
            print("sendPhoto error:", js)
            return False, js

        return True, "OK"

    except Exception as e:
        print("sendPhoto exception:", repr(e))
        return False, str(e)


def send_yolo_alert_payload(payload):
    """
    Called by Render FastAPI endpoint /yolo-alert.
    YOLO Space sends:
      {
        "message": "...",
        "images": [{"image": "data:image/jpeg;base64,...", "caption": "..."}],
        "final_summary": {...}
      }
    Render sends the message and annotated images to Telegram.
    """
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


def get_json(path, timeout=60):
    url = f"{WEATHER_APP_BASE_URL}{path}"
    r = requests.get(url, timeout=timeout)
    try:
        return r.json()
    except Exception:
        return {"error": r.text}


def pretty_json(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


def get_report_message(endpoint):
    js = get_json(endpoint, timeout=90)
    msg = js.get("message")
    if msg:
        return msg
    return pretty_json(js)


def handle_command(text):
    text = (text or "").strip()

    if text in ["/start", "/help"]:
        return (
            "🌿 Smart Greenhouse Bot is running.\n\n"
            "Commands:\n"
            "/readings - current sensor + disease report\n"
            "/report - full report with sensors + disease + weather\n"
            "/weather - weather information\n"
            "/disease - latest disease status\n"
            "/daily - send daily report now"
        )

    if text == "/readings":
        return add_menu(get_report_message("/send-readings"))

    if text in ["/report", "/daily"]:
        return add_menu(get_report_message("/send-report"))

    if text == "/weather":
        js = get_json("/weather")
        return add_menu("🌤 WEATHER INFO\n\n" + pretty_json(js))

    if text == "/disease":
        js = get_json("/disease")
        return add_menu("🦠 LATEST DISEASE STATUS\n\n" + pretty_json(js))

    if text == "/sensors":
        js = get_json("/sensors")
        return add_menu("🌿 SENSORS DATA\n\n" + pretty_json(js))

    return add_menu("Send /help to see available commands.")


def poll_loop():
    global last_update_id

    print("Deleting webhook...")
    print(tg_request("deleteWebhook", timeout=20))

    me = requests.get(f"{TG_API}/getMe", timeout=20).json()
    print("getMe:", me)

    send_message("✅ Telegram bridge started on Render." + COMMAND_MENU)

    while True:
        try:
            params = {"timeout": 25}
            if last_update_id is not None:
                params["offset"] = last_update_id + 1

            r = requests.get(f"{TG_API}/getUpdates", params=params, timeout=35)
            js = r.json()

            if not js.get("ok"):
                print("getUpdates error:", js)
                time.sleep(5)
                continue

            for update in js.get("result", []):
                last_update_id = update.get("update_id", last_update_id)

                msg = update.get("message") or update.get("edited_message") or {}
                chat = msg.get("chat", {})
                chat_id = str(chat.get("id", ""))

                if chat_id != str(TELEGRAM_CHAT_ID):
                    print("Ignoring chat_id:", chat_id)
                    continue

                text = msg.get("text", "")
                print("Command:", text)

                reply = handle_command(text)
                send_message(reply)

        except KeyboardInterrupt:
            print("Stopped by user.")
            break
        except Exception as e:
            print("poll_loop error:", repr(e))
            time.sleep(5)


if __name__ == "__main__":
    poll_loop()
