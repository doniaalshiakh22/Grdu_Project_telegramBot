import threading
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import telegram_bot_local

app = FastAPI(title="Smart Greenhouse Telegram Bridge")

started = False

@app.on_event("startup")
def startup():
    global started
    if not started:
        started = True
        t = threading.Thread(target=telegram_bot_local.poll_loop, daemon=True)
        t.start()

@app.get("/")
def root():
    return {
        "status": "running",
        "service": "Smart Greenhouse Telegram Bridge",
        "commands": ["/start", "/readings", "/report", "/weather", "/disease", "/daily"],
        "yolo_endpoint": "/yolo-alert"
    }

@app.get("/health")
def health():
    return {"status": "ok", "started": started}

@app.post("/yolo-alert")
async def yolo_alert(request: Request):
    """
    YOLO Hugging Face Space calls this endpoint.
    Render sends the disease alert and annotated images to Telegram.
    """
    try:
        payload = await request.json()
        result = telegram_bot_local.send_yolo_alert_payload(payload)
        return {
            "ok": bool(result.get("message_sent")) and result.get("photos_sent", 0) == result.get("photos_total", 0),
            "result": result
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})
