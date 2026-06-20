"""Apex Affiliate Bot — entry point."""
import os
import threading
from dotenv import load_dotenv

load_dotenv()

import bot as affiliate_bot
import webhook

if __name__ == "__main__":
    print("[APEX AFFILIATE BOT] Starting...")
    affiliate_bot.start()
    webhook.start_server()  # blocking
