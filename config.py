import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@support")
PAYMENT_NUMBER = os.getenv("PAYMENT_NUMBER", "")
PAYMENT_METHODS = [
    x.strip()
    for x in os.getenv("PAYMENT_METHODS", "bKash,Nagad").split(",")
    if x.strip()
]

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing in .env file")
if not ADMIN_IDS:
    raise RuntimeError("ADMIN_IDS missing in .env file")
