#!/usr/bin/env python3
"""
app.py — Telegram Logs Search Bot (no key system)

- Anyone can use search immediately (no keys).
- Uploads stored under /tmp/uploads (Render-friendly).
- Admin commands retained: /addadmin, /removeadmin, /listadmins, /clearglobal
- BOT_TOKEN is hard-coded here (use env var in production if you prefer).
"""
import os
import re
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Set, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# -------- CONFIG --------
# NOTE: Token provided by user (hard-coded here). Prefer using env var in production.
BOT_TOKEN = "8568040647:AAHrjk2CnFeKJ0gYFZQp4mDCKd02nyyOii0"

OWNER_ID = int(os.environ.get("OWNER_ID") or 0)  # optional numeric id to seed admin list
ADMINS_FILE = "admins.json"
DEFAULT_LOGS = "logs.txt"
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/tmp/uploads")  # use /tmp on Render

DEFAULT_KEYWORDS = [
    "mtacc", "roblox.com", "garena.com", "facebook.com",
    "crunchyroll.com", "netease.com", "expressvpn.com", "tiktok.com"
]

# -------- logging --------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------- runtime state --------
sessions: Dict[int, Dict[str, Any]] = {}
global_seen: Set[str] = set()
admins: Set[int] = set()

EMAIL_REGEX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# -------- helpers --------
def ensure_dirs():
    os.makedirs(UPLOAD_DIR, exist_ok=True)

def load_admins():
    global admins
    try:
        if os.path.exists(ADMINS_FILE):
            with open(ADMINS_FILE, "r", encoding="utf-8") as f:
                arr = json.load(f)
                admins = set(int(x) for x in arr)
        else:
            admins = set()
        if OWNER_ID:
            admins.add(OWNER_ID)
    except Exception as e:
        logger.exception("Failed to load admins: %s", e)
        admins = set()

def save_admins():
    try:
        with open(ADMINS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(admins)), f)
    except Exception as e:
        logger.exception("Failed to save admins: %s", e)

def ensure_session(user_id: int):
    if user_id not in sessions:
        sessions[user_id] = {
            "keywords": set(),
            "email_filter": "mix",  # mix | email_only | without_email
            "line_limit": 50,
            "uploaded_file": None,
            "results": [],
            "_awaiting_limit": False,
            "_awaiting_upload": False,
        }
    return sessions[user_id]

def keyword_buttons_markup(user_id: int):
    sess = ensure_session(user_id)
    kb = []
    row = []
    for kw in DEFAULT_KEYWORDS:
        checked = "✅" if kw in sess["keywords"] else "◻️"
        row.append(InlineKeyboardButton(f"{checked} {kw}", callback_data=f"togglekw|{kw}"))
        if len(row) >= 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([
        InlineKeyboardButton("Email: mix", callback_data="setfilter|mix"),
        InlineKeyboardButton("Email: only", callback_data="setfilter|email_only"),
        InlineKeyboardButton("Email: without", callback_data="setfilter|without_email"),
    ])
    kb.append([
        InlineKeyboardButton("Set limit", callback_data="setlimit"),
        InlineKeyboardButton("Upload logs", callback_data="upload"),
    ])
    kb.append([
        InlineKeyboardButton("Search", callback_data="search"),
        InlineKeyboardButton("Download", callback_data="download"),
    ])
    kb.append([InlineKeyboardButton("Clear results", callback_data="clearresults")])
    return InlineKeyboardMarkup(kb)

# -------- command handlers --------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_session(user.id)
    text = (
        "Logs Search Bot — no key required.\n\n"
        "Use the buttons to pick keywords, upload logs, set filters, and run searches.\n\n"
        "Commands:\n"
        "/status - show session status\n"
        "Admin: /addadmin /removeadmin /listadmins /clearglobal\n"
    )
    await update.message.reply_text(text, reply_markup=keyword_buttons_markup(user.id))

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sess = ensure_session(user.id)
    msg = (
        f"User: {user.mention_html()}\n"
        f"Keywords: {', '.join(sess['keywords']) or '(none)'}\n"
        f"Email filter: {sess['email_filter']}\n"
        f"Line limit: {sess['line_limit']}\n"
        f"Uploaded file: {os.path.basename(sess['uploaded_file']) if sess['uploaded_file'] else '(using logs.txt)'}\n"
        f"Results cached: {len(sess['results'])}\n"
    )
    await update.message.reply_html(msg, reply_markup=keyword_buttons_markup(user.id))

# -------- callbacks --------
async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    sess = ensure_session(user.id)
    data = query.data or ""
    if data.startswith("togglekw|"):
        kw = data.split("|", 1)[1]
        if kw in sess["keywords"]:
            sess["keywords"].remove(kw)
        else:
            sess["keywords"].add(kw)
        await query.edit_message_reply_markup(reply_markup=keyword_buttons_markup(user.id))
        return
    if data.startswith("setfilter|"):
        val = data.split("|", 1)[1]
        sess["email_filter"] = val
        await query.edit_message_reply_markup(reply_markup=keyword_buttons_markup(user.id))
        return
    if data == "setlimit":
        sess["_awaiting_limit"] = True
        await query.message.reply_text("Send the max number of lines to return (1..300).")
        return
    if data == "upload":
        sess["_awaiting_upload"] = True
        await query.message.reply_text("Now upload a .txt file; it will be used as the source for searches.")
        return
    if data == "search":
        await query.message.reply_text("Starting search...")
        await perform_search_for_user(user.id, context)
        return
    if data == "download":
        await send_results_file(user.id, context)
        return
    if data == "clearresults":
        sess["results"] = []
        await query.message.reply_text("Cleared visible results.")
        return

# -------- message handlers --------
async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sess = ensure_session(user.id)
    txt = update.message.text.strip() if update.message.text else ""
    if sess.pop("_awaiting_limit", False):
        try:
            v = int(txt)
            v = max(1, min(300, v))
            sess["line_limit"] = v
            await update.message.reply_text(f"Line limit set to {v}", reply_markup=keyword_buttons_markup(user.id))
        except Exception:
            await update.message.reply_text("Invalid number. Send 1..300.")
        return
    await update.message.reply_text("Use the buttons or /status to manage session.", reply_markup=keyword_buttons_markup(user.id))

async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sess = ensure_session(user.id)
    if not sess.pop("_awaiting_upload", False):
        await update.message.reply_text("If you want a file used for searches: press Upload then send the .txt file.")
        return
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text("Please upload a .txt file.")
        return
    f = await doc.get_file()
    ensure_dirs()
    safe_name = f"{user.id}_{int(datetime.utcnow().timestamp())}_{os.path.basename(doc.file_name)}"
    dest = os.path.join(UPLOAD_DIR, safe_name)
    # download_to_drive accepts a path (no keyword)
    await f.download_to_drive(dest)
    sess["uploaded_file"] = dest
    await update.message.reply_text(f"Uploaded: {os.path.basename(dest)}", reply_markup=keyword_buttons_markup(user.id))

# -------- search logic --------
def line_matches(line: str, keywords: List[str], email_filter: str) -> bool:
    if not line or not line.strip():
        return False
    has_email = bool(EMAIL_REGEX.search(line))
    if email_filter == "email_only" and not has_email:
        return False
    if email_filter == "without_email" and has_email:
        return False
    if not keywords:
        return True
    low = line.lower()
    for k in keywords:
        if k.lower() in low:
            return True
    return False

async def perform_search_for_user(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    sess = ensure_session(user_id)
    source = sess.get("uploaded_file") or DEFAULT_LOGS
    if not os.path.exists(source):
        await context.bot.send_message(chat_id=user_id, text="No logs.txt on server and no uploaded file. Upload a file or place logs.txt next to the bot.")
        return
    try:
        results = []
        keywords = list(sess["keywords"])
        limit = max(1, min(300, int(sess.get("line_limit", 50))))
        with open(source, "r", encoding="utf-8", errors="ignore") as f:
            for ln in f:
                ln_str = ln.rstrip("\n")
                if ln_str in global_seen:
                    continue
                if line_matches(ln_str, keywords, sess.get("email_filter", "mix")):
                    if ln_str in results:
                        continue
                    results.append(ln_str)
                    global_seen.add(ln_str)
                    if len(results) >= limit:
                        break
        sess["results"] = results
        if not results:
            await context.bot.send_message(chat_id=user_id, text="No results found (filters/dedupe).", reply_markup=keyword_buttons_markup(user_id))
            return
        preview = "\n".join(results[:10])
        await context.bot.send_message(chat_id=user_id, text=f"Found {len(results)} results. First items:\n\n{preview}\n\nTotal: {len(results)} (limit {limit})", reply_markup=keyword_buttons_markup(user_id))
    except Exception as e:
        logger.exception("Search failed: %s", e)
        await context.bot.send_message(chat_id=user_id, text="Search failed: " + str(e))

async def send_results_file(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    sess = ensure_session(user_id)
    results = sess.get("results") or []
    if not results:
        await context.bot.send_message(chat_id=user_id, text="No results to download.")
        return
    try:
        now = datetime.now().strftime("%Y-%m-%d_%H%M")
        fname = f"Results[{now}].txt"
        tmp = os.path.join(UPLOAD_DIR, f"tmp_results_{user_id}.txt")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(results))
        await context.bot.send_document(chat_id=user_id, document=InputFile(tmp, filename=fname))
        os.remove(tmp)
    except Exception as e:
        logger.exception("Failed to send results file: %s", e)
        await context.bot.send_message(chat_id=user_id, text="Failed to send results file: " + str(e))

# -------- admin commands --------
def is_admin(user_id: int) -> bool:
    return user_id in admins

async def clearglobal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Only admins.")
        return
    global_seen.clear()
    await update.message.reply_text("Cleared global seen set.")

async def addadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Only admins can add admins.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /addadmin <numeric_user_id>")
        return
    try:
        uid = int(args[0])
        admins.add(uid)
        save_admins()
        await update.message.reply_text(f"Added admin: {uid}")
    except Exception:
        await update.message.reply_text("Invalid user id.")

async def removeadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Only admins can remove admins.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /removeadmin <numeric_user_id>")
        return
    try:
        uid = int(args[0])
        if uid in admins:
            admins.remove(uid)
            save_admins()
            await update.message.reply_text(f"Removed admin: {uid}")
        else:
            await update.message.reply_text(f"{uid} is not an admin.")
    except Exception:
        await update.message.reply_text("Invalid user id.")

async def listadmins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Only admins.")
        return
    await update.message.reply_text("Admins: " + ", ".join(str(x) for x in sorted(admins)))

# -------- help / misc --------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - open the UI\n"
        "/status - show your session\n"
        "/addadmin <id> /removeadmin <id> /listadmins /clearglobal (admin only)\n"
    )

# -------- entrypoint --------
def main():
    ensure_dirs()
    load_admins()
    # ensure OWNER_ID present if set
    if OWNER_ID:
        admins.add(OWNER_ID)
        save_admins()

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set. Edit the script or set an environment variable.")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_cmd))

    app.add_handler(CallbackQueryHandler(cb_handler))

    # Use filters.Document (matches documents) and ensure no command messages
    app.add_handler(MessageHandler(filters.Document & (~filters.COMMAND), file_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_message_handler))

    app.add_handler(CommandHandler("clearglobal", clearglobal_cmd))
    app.add_handler(CommandHandler("addadmin", addadmin_cmd))
    app.add_handler(CommandHandler("removeadmin", removeadmin_cmd))
    app.add_handler(CommandHandler("listadmins", listadmins_cmd))

    logger.info("Bot starting (polling)...")
    app.run_polling()

if __name__ == "__main__":
    main()
