import threading
from sale_bot import build_application

def run_bot():
    app = build_application()
    app.run_polling()

threading.Thread(target=run_bot, daemon=True).start()

from flask import Flask
application = Flask(__name__)

@application.route("/")
def index():
    return "✅ Telegram bot is running on server"
