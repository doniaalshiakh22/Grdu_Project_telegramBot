import threading
from fastapi import FastAPI
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
        "menu_after_every_response": True
    }

@app.get("/health")
def health():
    return {"status": "ok", "started": started}
