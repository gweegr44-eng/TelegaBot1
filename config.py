import os
from dotenv import load_dotenv

load_dotenv()

MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN")
if not MAX_BOT_TOKEN:
    raise ValueError("MAX_BOT_TOKEN не задан в .env!")

SUPERADMIN_ID = int(os.getenv("SUPERADMIN_ID", "0"))

DB_PATH = os.getenv("DB_PATH", "reports.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

TIMEZONE = os.getenv("TIMEZONE", "Asia/Yekaterinburg")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
EMPLOYEE_WEBAPP_URL = os.getenv("EMPLOYEE_WEBAPP_URL", "")
MANAGER_WEBAPP_URL = os.getenv("MANAGER_WEBAPP_URL", "")

MAX_BOT_ID = int(os.getenv("MAX_BOT_ID", "460305816"))

SLOTS = ["11:30", "13:30", "15:30", "17:30", "20:00"]

REPORT_METRICS = [
    "revenue", "sim_count", "gift_sim_count", "rev", "zc",
    "subscription", "mnp_requests", "combo_x2", "accessories_sum",
    "smartphones_buttons_sum", "paid_services", "credit_requests",
]