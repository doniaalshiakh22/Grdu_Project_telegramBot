from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import telegram_bot_local

app = FastAPI(title="Smart Greenhouse Telegram Webhook Bot")

@app.on_event("startup")
def startup():
    result = telegram_bot_local.set_telegram_webhook()
    print("setWebhook:", result)
    print("getWebhookInfo:", telegram_bot_local.get_webhook_info())

@app.get("/")
def root():
    return {
        "status": "running",
        "service": "Smart Greenhouse Telegram Webhook Bot",
        "commands": ["/start", "/readings", "/report", "/weather", "/disease", "/daily"],
        "telegram_webhook": "/telegram-webhook",
        "yolo_endpoint": "/yolo-alert"
    }

@app.get("/health")
def health():
    return {"status": "ok", "mode": "webhook"}

@app.get("/set-webhook")
def set_webhook():
    result = telegram_bot_local.set_telegram_webhook()
    info = telegram_bot_local.get_webhook_info()
    return {"setWebhook": result, "getWebhookInfo": info}

@app.get("/webhook-info")
def webhook_info():
    return telegram_bot_local.get_webhook_info()

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
