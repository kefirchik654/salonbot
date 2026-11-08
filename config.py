import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SUPER_ADMINS = {int(x) for x in os.getenv("SUPER_ADMINS", "").replace(" ", "").split(",") if x.strip().isdigit()}
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
DATABASE_URL = os.getenv("DATABASE_URL", "")
PORT = int(os.getenv("PORT", "8080"))
DEFAULT_TZ = os.getenv("DEFAULT_TZ", "Europe/Moscow")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS", "data/google.json")  # файл (локально)
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")        # содержимое json (Railway)
