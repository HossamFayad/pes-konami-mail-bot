import os
import sys

# Ensure root directory is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI, Request, Response
import telebot
from database import init_db
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
    if request.headers.get("content-type") == "application/json":
        json_string = await request.body()
        update = telebot.types.Update.de_json(json_string.decode("utf-8"))
        bot.process_new_updates([update])
        return Response(status_code=200)
    return Response(status_code=403)
