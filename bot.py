import os
import sqlite3
import asyncio
from datetime import datetime, date
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

TOKEN = os.getenv("BOT_TOKEN")
TZ = ZoneInfo("Asia/Karachi")
DUTY_START_HOUR = 10
DUTY_START_MINUTE = 0
DB_PATH = os.getenv("DB_PATH", "worktime.db")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Set it as an environment variable.")

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute("""
CREATE TABLE IF NOT EXISTS sessions (
    user_id INTEGER NOT NULL,
    work_date TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    active_break TEXT,
    break_started_at TEXT,
    toilet_seconds INTEGER NOT NULL DEFAULT 0,
    eat_seconds INTEGER NOT NULL DEFAULT 0,
    smoke_seconds INTEGER NOT NULL DEFAULT 0,
    status_message_id INTEGER,
    PRIMARY KEY (user_id, work_date)
)
""")
db.commit()

keyboard = ReplyKeyboardMarkup(
    [
        ["▶️ Start Work", "⏹️ Off Work"],
        ["🚻 Toilet", "🍽️ Eat", "🚬 Smoke"],
        ["💺 Back to Seat"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

def now():
    return datetime.now(TZ)

def today():
    return now().date().isoformat()

def get_session(user_id):
    d = today()
    row = db.execute(
        "SELECT * FROM sessions WHERE user_id=? AND work_date=?",
        (user_id, d)
    ).fetchone()
    if row is None:
        db.execute(
            "INSERT INTO sessions(user_id, work_date) VALUES (?, ?)",
            (user_id, d)
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM sessions WHERE user_id=? AND work_date=?",
            (user_id, d)
        ).fetchone()
    return row

def update(user_id, **fields):
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [user_id, today()]
    db.execute(
        f"UPDATE sessions SET {sets} WHERE user_id=? AND work_date=?",
        vals
    )
    db.commit()

def parse_dt(s):
    return datetime.fromisoformat(s) if s else None

def fmt(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"

def current_break_seconds(row):
    if not row["active_break"] or not row["break_started_at"]:
        return 0
    return max(0, int((now() - parse_dt(row["break_started_at"])).total_seconds()))

def totals(row):
    toilet = row["toilet_seconds"]
    eat = row["eat_seconds"]
    smoke = row["smoke_seconds"]
    if row["active_break"] == "toilet":
        toilet += current_break_seconds(row)
    elif row["active_break"] == "eat":
        eat += current_break_seconds(row)
    elif row["active_break"] == "smoke":
        smoke += current_break_seconds(row)

    total_break = toilet + eat + smoke

    start = parse_dt(row["started_at"])
    end = parse_dt(row["ended_at"]) or now()
    elapsed = 0
    if start:
        elapsed = max(0, int((end - start).total_seconds()))

    work = max(0, elapsed - total_break)
    return work, total_break, toilet, eat, smoke

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Work Time Bot is ready.\nUse the buttons below to start work, end work, or record breaks.",
        reply_markup=keyboard
    )

async def start_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = get_session(user_id)

    if row["started_at"] and not row["ended_at"]:
        await update.message.reply_text("You have already started work today.", reply_markup=keyboard)
        return

    t = now()
    scheduled = t.replace(hour=DUTY_START_HOUR, minute=DUTY_START_MINUTE, second=0, microsecond=0)
    late = max(0, int((t - scheduled).total_seconds()))

    update_fields = {
        "started_at": t.isoformat(),
        "ended_at": None,
        "active_break": None,
        "break_started_at": None,
        "toilet_seconds": 0,
        "eat_seconds": 0,
        "smoke_seconds": 0,
    }
    update(user_id, **update_fields)

    if late:
        await update.message.reply_text(
            f"⚠️ Late Start Alert\nOfficial start time: 10:00 AM\n"
            f"Your start time: {t.strftime('%I:%M:%S %p')}\n"
            f"Late by: {fmt(late)}",
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            f"✅ Work started at {t.strftime('%I:%M:%S %p')}.\nDuty timer is now running.",
            reply_markup=keyboard
        )

async def off_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = get_session(user_id)

    if not row["started_at"]:
        await update.message.reply_text("You have not started work today.", reply_markup=keyboard)
        return

    if row["ended_at"]:
        work, br, toilet, eat, smoke = totals(row)
        await update.message.reply_text(
            summary_text(work, br, toilet, eat, smoke, row),
            reply_markup=keyboard
        )
        return

    if row["active_break"]:
        await finish_break_internal(user_id, row)

    row = get_session(user_id)
    t = now()
    update(user_id, ended_at=t.isoformat(), active_break=None, break_started_at=None)
    row = get_session(user_id)
    work, br, toilet, eat, smoke = totals(row)

    await update.message.reply_text(
        "⏹️ Work ended.\n\n" + summary_text(work, br, toilet, eat, smoke, row),
        reply_markup=keyboard
    )

def summary_text(work, br, toilet, eat, smoke, row):
    return (
        f"📊 Today's Work Summary\n"
        f"Work time: {fmt(work)}\n"
        f"Total break time: {fmt(br)}\n\n"
        f"🚻 Toilet: {fmt(toilet)}\n"
        f"🍽️ Eat: {fmt(eat)}\n"
        f"🚬 Smoke: {fmt(smoke)}"
    )

async def begin_break(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str, label: str):
    user_id = update.effective_user.id
    row = get_session(user_id)

    if not row["started_at"] or row["ended_at"]:
        await update.message.reply_text("Please start work first.", reply_markup=keyboard)
        return

    if row["active_break"]:
        await update.message.reply_text(
            f"You are already on a {row['active_break']} break. Press Back to Seat first.",
            reply_markup=keyboard
        )
        return

    t = now()
    update(user_id, active_break=kind, break_started_at=t.isoformat())

    await update.message.reply_text(
        f"{label} break started at {t.strftime('%I:%M:%S %p')}.\n"
        f"Press Back to Seat when you return.",
        reply_markup=keyboard
    )

async def finish_break_internal(user_id, row):
    if not row["active_break"] or not row["break_started_at"]:
        return None

    duration = current_break_seconds(row)
    kind = row["active_break"]
    field = f"{kind}_seconds"
    new_total = row[field] + duration
    update(
        user_id,
        **{
            field: new_total,
            "active_break": None,
            "break_started_at": None,
        }
    )
    return kind, duration

async def back_to_seat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = get_session(user_id)

    if not row["active_break"]:
        await update.message.reply_text("You are not currently on a break.", reply_markup=keyboard)
        return

    result = await finish_break_internal(user_id, row)
    kind, duration = result

    labels = {"toilet": "🚻 Toilet", "eat": "🍽️ Eat", "smoke": "🚬 Smoke"}
    await update.message.reply_text(
        f"💺 Back to Seat\n{labels[kind]} break duration: {fmt(duration)}",
        reply_markup=keyboard
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = get_session(user_id)
    if not row["started_at"]:
        await update.message.reply_text("No work session started today.", reply_markup=keyboard)
        return
    work, br, toilet, eat, smoke = totals(row)
    active = f"\nCurrent break: {row['active_break']} ({fmt(current_break_seconds(row))})" if row["active_break"] else ""
    await update.message.reply_text(
        summary_text(work, br, toilet, eat, smoke, row) + active,
        reply_markup=keyboard
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text == "▶️ Start Work":
        return await start_work(update, context)
    if text == "⏹️ Off Work":
        return await off_work(update, context)
    if text == "🚻 Toilet":
        return await begin_break(update, context, "toilet", "🚻 Toilet")
    if text == "🍽️ Eat":
        return await begin_break(update, context, "eat", "🍽️ Eat")
    if text == "🚬 Smoke":
        return await begin_break(update, context, "smoke", "🚬 Smoke")
    if text == "💺 Back to Seat":
        return await back_to_seat(update, context)
    await update.message.reply_text(
        "Please use the buttons below.", reply_markup=keyboard
    )

async def post_init(application: Application):
    await application.bot.set_my_commands([
        ("startwork", "Start work and begin duty timer"),
        ("offwork", "End work and show today's summary"),
        ("toilet", "Start toilet break timer"),
        ("eat", "Start eating break timer"),
        ("smoke", "Start smoke break timer"),
        ("backtoseat", "End current break and show duration"),
        ("status", "Show today's work and break summary"),
    ])

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("startwork", start_work))
    app.add_handler(CommandHandler("offwork", off_work))
    app.add_handler(CommandHandler("toilet", lambda u, c: begin_break(u, c, "toilet", "🚻 Toilet")))
    app.add_handler(CommandHandler("eat", lambda u, c: begin_break(u, c, "eat", "🍽️ Eat")))
    app.add_handler(CommandHandler("smoke", lambda u, c: begin_break(u, c, "smoke", "🚬 Smoke")))
    app.add_handler(CommandHandler("backtoseat", back_to_seat))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Work Time Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
