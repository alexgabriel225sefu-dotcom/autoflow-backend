"""Apex Affiliate Bot — entry point.

Tracking and link generation now live on the main server (Supabase). This bot
just polls Telegram and talks to the server API, so no local webhook/store is
needed anymore.
"""
from dotenv import load_dotenv

load_dotenv()            # reads .env if present
load_dotenv('bot.env', override=True)  # bot.env takes precedence (workflow may write either)

import bot as affiliate_bot

if __name__ == "__main__":
    print("[APEX AFFILIATE BOT] Starting...")
    affiliate_bot.run()  # blocking poll loop
