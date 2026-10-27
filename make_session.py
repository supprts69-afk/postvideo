"""Ekbar nijer computer-e chalao (Render-e na):  python make_session.py
Phone number + Telegram-er code (+ 2FA password) dile ekta lomba string dibe.
Oita Render-er env var TG_SESSION-e boshao. Ei string kauke dio na, chat-e paste korba na."""
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

api_id = int(input("API ID: ").strip())
api_hash = input("API HASH: ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("\n=== TG_SESSION (secret!) ===")
    print(client.session.save())
