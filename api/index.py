import os
import sys

# Ensure root directory is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI, Request, Response
import telebot
from database import init_db, turso_execute
from bot import bot

app = FastAPI(title="PES Konami Mail Webhook")

@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/")
def home():
    return {
        "status": "online",
        "service": "PES Konami Mail Bot",
        "instructions": "Visit /set_webhook to automatically configure the Telegram Webhook."
    }

@app.get("/debug")
def debug():
    import database
    from mail_service import MailService
    try:
        acc = MailService.create_account("pes_dbg")
    except Exception as e:
        acc = str(e)
    return {
        "USE_TURSO": database.USE_TURSO,
        "TURSO_URL": database.TURSO_URL,
        "test_acc": acc
    }


@app.get("/set_webhook")
def set_webhook(request: Request):
    host = request.headers.get("host")
    if not host:
        return {"ok": False, "error": "Host header missing"}
    
    webhook_url = f"https://{host}/api/webhook"
    res = bot.set_webhook(url=webhook_url)
    return {
        "ok": res,
        "webhook_url": webhook_url,
        "bot_username": bot.get_me().username,
        "message": "Webhook has been set successfully! Your bot is now live 24/7."
    }

@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    raw_body = await request.body()
    try:
        if raw_body:
            json_str = raw_body.decode("utf-8")
            turso_execute("INSERT INTO debug_logs (event, data) VALUES (?, ?)", ["webhook_received", json_str[:300]])
            update = telebot.types.Update.de_json(json_str)
            if update:
                bot.process_new_updates([update])
                turso_execute("INSERT INTO debug_logs (event, data) VALUES (?, ?)", ["process_updates_done", "ok"])
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        turso_execute("INSERT INTO debug_logs (event, data) VALUES (?, ?)", ["webhook_error", err_msg[:500]])
    return Response(status_code=200)



