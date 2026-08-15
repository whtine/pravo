import os
import requests
import threading
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, jsonify
from supabase import create_client, Client

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SITE_URL = os.environ.get("SITE_URL", "https://ВАШ-САЙТ.onrender.com")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- УЧЕТ ПОСЕТИТЕЛЕЙ ---
@app.before_request
def track_visits():
    # Игнорируем фоновые запросы и служебные роуты
    if request.path in ['/ping', '/webhook', '/send-request', '/save-review', '/get-reviews']:
        return

    user_agent = request.headers.get('User-Agent', '')

    # Фильтруем пинги и известных ботов (UptimeRobot, Headless и т.д.)
    bot_keywords = ['uptimerobot', 'bot', 'spider', 'crawler', 'python-requests']
    if any(keyword in user_agent.lower() for keyword in bot_keywords):
        return

    # Сохраняем только реальные визиты пользователей
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

@app.route('/test')
def test_page():
    return render_template('test.html')

# --- ЗАЯВКИ ---
@app.route('/send-request', methods=['POST'])
def send_request():
    name         = request.form.get('name', '')
    phone        = request.form.get('phone', '')
    country_code = request.form.get('country_code', '')
    full_phone   = f"{country_code}{phone}"
    service      = request.form.get('service', '')
    message      = request.form.get('message', '')

    try:
        supabase.table("leads").insert({
            "name": name,
            "phone": full_phone,
            "service": service,
            "message": message
        }).execute()
    except Exception as e:
        print(f"DB error: {e}")

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
def save_review():
    name        = request.form.get('name', '').strip()
    role        = request.form.get('role', '').strip()
    review_text = request.form.get('review_text', '').strip()

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
        import traceback
        traceback.print_exc()
        return jsonify({"reviews": [], "error": str(e)}), 500


# --- TELEGRAM BOT ---
def get_stats_text():
    now = datetime.now(timezone.utc)
    day_ago = (now - timedelta(days=1)).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()

    try:
        # Запросы к БД
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

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data    = request.json
        chat_id = data['message']['chat']['id']
        text    = data['message'].get('text', '')

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
                    [f"👤 {l.get('name', '')}\n📞 {l.get('phone', '')}\n🛠 {l.get('service', '')}" for l in leads]
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
    app.run()
