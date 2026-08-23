import os
import hmac
import requests
import threading
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, jsonify
from supabase import create_client, Client
from cryptography.fernet import Fernet, InvalidToken
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SITE_URL = os.environ.get("SITE_URL", "https://ВАШ-САЙТ.onrender.com")


TG_WEBHOOK_SECRET = os.environ.get("TG_WEBHOOK_SECRET")


ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")
fernet = Fernet(ENCRYPTION_KEY.encode()) if ENCRYPTION_KEY else None

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- ЛИМИТЫ ЗАПРОСОВ ---
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",  # для продакшена с несколькими воркерами лучше redis://...
)


def encrypt_value(value: str) -> str:
    """Шифрует строку. Если ключа нет — возвращает как есть (для локальной разработки)."""
    if not fernet or not value:
        return value
    return fernet.encrypt(value.encode()).decode()


def decrypt_value(value: str) -> str:
    """Расшифровывает строку. Если не получилось (старые незашифрованные данные) — возвращает как есть."""
    if not fernet or not value:
        return value
    try:
        return fernet.decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return value


def clip(text: str, max_len: int) -> str:
    return (text or "").strip()[:max_len]


# --- УЧЕТ ПОСЕТИТЕЛЕЙ ---
@app.before_request
def track_visits():
    if request.path in ['/ping', '/webhook', '/send-request', '/save-review', '/get-reviews']:
        return

    user_agent = request.headers.get('User-Agent', '')

    bot_keywords = ['uptimerobot', 'bot', 'spider', 'crawler', 'python-requests']
    if any(keyword in user_agent.lower() for keyword in bot_keywords):
        return

    try:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()

        supabase.table("visits").insert({
            "ip_address": ip,
            "user_agent": user_agent[:255]
        }).execute()
    except Exception as e:
        print(f"Tracking error: {e}")


# --- KEEP ALIVE ---
def keep_alive():
    time.sleep(30)
    while True:
        try:
            requests.get(SITE_URL + "/ping", timeout=10)
            print("Ping sent")
        except Exception as e:
            print(f"Ping error: {e}")
        time.sleep(14 * 60)


threading.Thread(target=keep_alive, daemon=True).start()


@app.route('/ping')
def ping():
    return "ok", 200


# --- СТРАНИЦЫ ---
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/services')
def service_page():
    return render_template('service.html')


@app.route('/loaderio-4444df88f16b38e0f103263f10e9fdcc.txt')
def loaderio_verify():
    return 'loaderio-4444df88f16b38e0f103263f10e9fdcc', 200, {'Content-Type': 'text/plain'}


# --- ЗАЯВКИ ---
@app.route('/send-request', methods=['POST'])
@limiter.limit("5 per minute")
def send_request():
    name         = clip(request.form.get('name', ''), 100)
    phone_raw    = clip(request.form.get('phone', ''), 30)
    country_code = clip(request.form.get('country_code', ''), 10)
    service      = clip(request.form.get('service', ''), 100)
    message      = clip(request.form.get('message', ''), 2000)

    if not name or not phone_raw:
        return jsonify({"status": "error", "message": "Заповніть обов'язкові поля"}), 400

    full_phone = f"{country_code}{phone_raw}"

    try:
        supabase.table("leads").insert({
            "name": name,
            "phone": encrypt_value(full_phone),
            "service": service,
            "message": message
        }).execute()
    except Exception as e:
        print(f"DB error: {e}")
        return jsonify({"status": "error", "message": "Помилка збереження заявки"}), 500

    try:
        tg_text = (
            f"📩 <b>Нова заявка!</b>\n"
            f"Ім'я: {name}\n"
            f"Телефон: {full_phone}\n"
            f"Послуга: {service}\n"
            f"Питання: {message}"
        )
        requests.post(
            f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
            data={"chat_id": os.environ['TG_CHAT_ID'], "text": tg_text, "parse_mode": "HTML"},
            timeout=5
        )
    except Exception as e:
        print(f"TG error: {e}")

    return jsonify({"status": "success"})


# --- ОТЗЫВЫ ---
@app.route('/save-review', methods=['POST'])
@limiter.limit("3 per minute")
def save_review():
    name        = clip(request.form.get('name', ''), 100)
    role        = clip(request.form.get('role', ''), 100)
    review_text = clip(request.form.get('review_text', ''), 1000)

    try:
        rating = int(request.form.get('rating', 5))
        if rating < 1 or rating > 5:
            rating = 5
    except (ValueError, TypeError):
        rating = 5

    if not name or not review_text:
        return jsonify({"status": "error", "message": "Заповніть всі поля"}), 400

    try:
        supabase.table("reviews").insert({
            "name": name,
            "role": role,
            "review_text": review_text,
            "rating": rating
        }).execute()
    except Exception as e:
        print(f"DB error: {e}")
        return jsonify({"status": "error", "message": "Помилка бази даних"}), 500

    try:
        stars   = '★' * rating + '☆' * (5 - rating)
        tg_text = (
            f"💬 <b>Новий відгук!</b>\n"
            f"👤 {name}" + (f" ({role})" if role else "") +
            f"\n{stars} ({rating}/5)\n"
            f"📝 {review_text}"
        )
        requests.post(
            f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
            data={"chat_id": os.environ['TG_CHAT_ID'], "text": tg_text, "parse_mode": "HTML"},
            timeout=5
        )
    except Exception as e:
        print(f"TG error: {e}")

    return jsonify({"status": "success"})


@app.route('/get-reviews', methods=['GET'])
@limiter.limit("30 per minute")
def get_reviews():
    try:
        response = supabase.table("reviews") \
            .select("name, role, review_text, rating, created_at") \
            .order("created_at", desc=True) \
            .limit(20) \
            .execute()

        reviews = []
        for r in response.data:
            reviews.append({
                "name":       r.get("name") or "",
                "role":       r.get("role") or "",
                "text":       r.get("review_text") or "",
                "rating":     int(r.get("rating")) if r.get("rating") else 5,
                "created_at": r.get("created_at") or ""
            })
        return jsonify({"reviews": reviews})

    except Exception as e:
        print(f"get-reviews error: {e}")
        return jsonify({"reviews": []}), 500


# --- TELEGRAM BOT ---
def get_stats_text():
    now = datetime.now(timezone.utc)
    day_ago = (now - timedelta(days=1)).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()

    try:
        res_day = supabase.table("visits").select("id", count="exact").gte("created_at", day_ago).execute()
        res_week = supabase.table("visits").select("id", count="exact").gte("created_at", week_ago).execute()
        res_month = supabase.table("visits").select("id", count="exact").gte("created_at", month_ago).execute()

        count_day = res_day.count or 0
        count_week = res_week.count or 0
        count_month = res_month.count or 0

        return (
            f"📊 <b>Статистика відвідувань сайту:</b>\n\n"
            f"🟢За останні 24 години: <b>{count_day}</b>\n"
            f"🟡За останній тиждень: <b>{count_week}</b>\n"
            f"🔵За останній місяць: <b>{count_month}</b>\n\n"
        )
    except Exception as e:
        print(f"Stats error: {e}")
        return "Не вдалося отримати статистику."


def is_authorized_chat(chat_id) -> bool:
    """Сверяет chat_id входящего сообщения с владельцем бота — защита от чужих сообщений."""
    expected = os.environ.get('TG_CHAT_ID', '')
    return hmac.compare_digest(str(chat_id), str(expected))


@app.route('/webhook', methods=['POST'])
def webhook():
    # 1) Проверяем секретный токен, который Telegram присылает в заголовке.
    #    Настраивается один раз при регистрации вебхука через setWebhook(secret_token=...).
    incoming_secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
    if not TG_WEBHOOK_SECRET or not hmac.compare_digest(incoming_secret, TG_WEBHOOK_SECRET):
        return "forbidden", 403

    try:
        data    = request.json
        chat_id = data['message']['chat']['id']
        text    = data['message'].get('text', '')

        # 2) Даже с верным секретом отвечаем командами только своему chat_id.
        if not is_authorized_chat(chat_id):
            return "ok"

        if text == '/start':
            reply = "Вітаю! Команди:\n/stats — статистика відвідувань\n/history — останні заявки\n/reviews — останні 5 відгуків"

        elif text == '/stats':
            reply = get_stats_text()

        elif text == '/history':
            response = supabase.table("leads") \
                .select("name, phone, service") \
                .order("created_at", desc=True) \
                .limit(5) \
                .execute()

            leads = response.data
            if leads:
                reply = "Останні 5 заявок:\n\n" + "\n\n".join(
                    [f"👤 {l.get('name', '')}\n📞 {decrypt_value(l.get('phone', ''))}\n🛠 {l.get('service', '')}" for l in leads]
                )
            else:
                reply = "Заявок немає."

        elif text == '/reviews':
            response = supabase.table("reviews") \
                .select("name, role, review_text, rating") \
                .order("created_at", desc=True) \
                .limit(5) \
                .execute()

            revs = response.data
            if revs:
                lines = []
                for r in revs:
                    rating_val = r.get('rating') or 5
                    stars      = '★' * rating_val + '☆' * (5 - rating_val)
                    role_str   = f" ({r.get('role')})" if r.get('role') else ""
                    lines.append(f"👤 {r.get('name', '')}{role_str} {stars}\n💬 {r.get('review_text', '')}")
                reply = "Останні 5 відгуків:\n\n" + "\n\n".join(lines)
            else:
                reply = "Відгуків немає."

        else:
            reply = "Невідома команда. Введіть /start для списку команд."

        requests.post(
            f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
            data={"chat_id": chat_id, "text": reply, "parse_mode": "HTML"},
            timeout=5
        )
    except Exception as e:
        print(f"Webhook error: {e}")

    return "ok"


if __name__ == '__main__':
    app.run(debug=False)
