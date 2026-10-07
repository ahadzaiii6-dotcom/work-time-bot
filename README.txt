# Telegram Work Time Bot

This bot provides a persistent Telegram keyboard with:

Top row:
- Start Work
- Off Work

Second row:
- Toilet
- Eat
- Smoke

Bottom row:
- Back to Seat

Features:
- Starts duty timing when Start Work is pressed.
- Official duty start is 10:00 AM Asia/Karachi.
- Sends a late-start alert if Start Work is pressed after 10:00 AM.
- Starts a separate timer for Toilet/Eat/Smoke.
- Back to Seat stops the active break and reports its duration.
- Off Work reports working time, total break time, and each break category.
- Uses SQLite so daily records survive bot restarts.
- /status shows the current day's totals.

## Setup

1. Create a bot with BotFather and copy the bot token.
2. Install Python 3.10+.
3. Install dependencies:

    pip install -r requirements.txt

4. Set the token:

Linux/macOS:
    export BOT_TOKEN="YOUR_TOKEN"

Windows PowerShell:
    $env:BOT_TOKEN="YOUR_TOKEN"

5. Run:

    python bot.py

## BotFather command list

Send this to BotFather when it asks for commands:

startwork - Start work and begin duty timer
offwork - End work and show today's summary
toilet - Start toilet break timer
eat - Start eating break timer
smoke - Start smoke break timer
backtoseat - End current break and show duration
status - Show today's work and break summary

## Important

The bot token is a secret. Do not post it in a group or send it publicly.
