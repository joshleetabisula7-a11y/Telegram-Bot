import os
import json
import shlex
import time
from flask import Flask, request, Response
import requests

# ==== HARDCODED TOKEN + ADMIN (as you requested) ====
TOKEN = "8568040647:AAHrjk2CnFeKJ0gYFZQp4mDCKd02nyyOii0"
ADMIN_ID = 7301067810
# ====================================================

BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
WEBHOOK_PATH = f"/webhook/{TOKEN}"

LOGS_FILE = "logs.txt"
SUBSCRIBERS_FILE = "subscribers.txt"

app = Flask(__name__)


# --- File Helpers ---

def append_log(text: str):
    with open(LOGS_FILE, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def read_logs():
    if not os.path.exists(LOGS_FILE):
        return []
    with open(LOGS_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f.readlines()]


def add_subscriber(chat_id):
    chat_id = str(chat_id)
    if not os.path.exists(SUBSCRIBERS_FILE):
        with open(SUBSCRIBERS_FILE, "w") as f:
            pass

    with open(SUBSCRIBERS_FILE, "r") as f:
        subs = [s.strip() for s in f.readlines()]

    if chat_id not in subs:
        with open(SUBSCRIBERS_FILE, "a") as f:
            f.write(chat_id + "\n")


def get_subscribers():
    if not os.path.exists(SUBSCRIBERS_FILE):
        return []
    with open(SUBSCRIBERS_FILE, "r") as f:
        return [line.strip() for line in f]


# --- Telegram Send Function ---

def send_message(chat_id: int, text: str):
    payload = {"chat_id": chat_id, "text": text}
    requests.post(f"{BASE_URL}/sendMessage", json=payload)


# ========== MAIN BOT LOGIC ==========

def handle_command(chat_id, text):

    # /start -----------------------------------------------------
    if text.startswith("/start"):
        add_subscriber(chat_id)
        send_message(chat_id, "Welcome!\nUse /search <keywords> to search logs.")
        return

    # /help ------------------------------------------------------
    if text.startswith("/help"):
        send_message(chat_id,
                     "/search <keywords> — search in logs\n"
                     "/announce <message> — admin only")
        return

    # /search ----------------------------------------------------
    if text.startswith("/search"):
        parts = shlex.split(text)
        if len(parts) < 2:
            send_message(chat_id, "Usage: /search <keywords>")
            return

        query = " ".join(parts[1:]).lower()
        logs = read_logs()

        results = [line for line in logs if query in line.lower()]

        if results:
            send_message(chat_id, "\n".join(results))
        else:
            send_message(chat_id, "No results found.")
        return

    # /announce ---------------------------------------------------
    if text.startswith("/announce"):
        if int(chat_id) != int(ADMIN_ID):
            send_message(chat_id, "You are not admin.")
            return

        parts = shlex.split(text)
        if len(parts) < 2:
            send_message(chat_id, "Usage: /announce <message>")
            return

        msg = " ".join(parts[1:])
        for user in get_subscribers():
            send_message(user, f"[ANNOUNCEMENT]\n{msg}")

        send_message(chat_id, "Announcement sent.")
        return


# ========== WEBHOOK ENDPOINT ==========

@app.route(WEBHOOK_PATH, methods=["POST"])
def bot_webhook():
    data = request.json

    if "message" in data:
        msg = data["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")

        # Log messages (including searches)
        append_log(f"{time.ctime()} | {chat_id} | {text}")

        handle_command(chat_id, text)

    return Response("OK", status=200)


# ========== ROOT PAGE ==========

@app.route("/")
def index():
    return "Bot is running."


# ========== RUN LOCAL ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)