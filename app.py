import os
import requests
import psycopg2
import threading
import time
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

DB_URL = os.environ.get("DATABASE_URL")
SITE_URL = os.environ.get("SITE_URL", "https://ВАШ-САЙТ.onrender.com")

def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id         SERIAL PRIMARY KEY,
            name       VARCHAR(100),
            phone      VARCHAR(50),
            service    VARCHAR(200),
            message    TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id         SERIAL PRIMARY KEY,
            name       VARCHAR(100) NOT NULL,
            role       VARCHAR(150),
            review_text TEXT NOT NULL,
            rating     SMALLINT DEFAULT 5,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

def keep_alive():
    while True:
        time.sleep(14 * 60)
        try:
            requests.get(SITE_URL + "/ping", timeout=10)
        except Exception:
            pass

@app.route('/ping')
def ping():
    return "ok", 200

threading.Thread(target=keep_alive, daemon=True).start()
init_db()

# --- СТРАНИЦЫ ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/service')
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
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            'INSERT INTO leads (name, phone, service, message) VALUES (%s, %s, %s, %s)',
            (name, full_phone, service, message)
        )
        conn.commit()
        cur.close()
        conn.close()
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

# --- ВІДГУКИ ---
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
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            'INSERT INTO reviews (name, role, review_text, rating) VALUES (%s, %s, %s, %s)',
            (name, role, review_text, rating)
        )
        conn.commit()
        cur.close()
        conn.close()
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
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("""
            SELECT name, role, review_text, rating, created_at
            FROM reviews
            ORDER BY created_at DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        reviews = []
        for r in rows:
            reviews.append({
                "name":       r[0] or "",
                "role":       r[1] or "",
                "text":       r[2] or "",
                "rating":     int(r[3]) if r[3] else 5,
                "created_at": r[4].isoformat() if r[4] else ""
            })
        return jsonify({"reviews": reviews})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"reviews": [], "error": str(e)}), 500


# --- TELEGRAM BOT ---
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data    = request.json
        chat_id = data['message']['chat']['id']
        text    = data['message'].get('text', '')

        if text == '/start':
            reply = "Вітаю! Команди:\n/history — останні заявки\n/reviews — останні 5 відгуків"

        elif text == '/history':
            conn = get_db_connection()
            cur  = conn.cursor()
            cur.execute("""
                SELECT name, phone, service
                FROM leads
                ORDER BY created_at DESC
                LIMIT 5
            """)
            leads = cur.fetchall()
            cur.close()
            conn.close()
            if leads:
                reply = "Останні 5 заявок:\n\n" + "\n\n".join(
                    [f"👤 {l[0]}\n📞 {l[1]}\n🛠 {l[2]}" for l in leads]
                )
            else:
                reply = "Заявок немає."

        elif text == '/reviews':
            conn = get_db_connection()
            cur  = conn.cursor()
            cur.execute("""
                SELECT name, role, review_text, rating
                FROM reviews
                ORDER BY created_at DESC
                LIMIT 5
            """)
            revs = cur.fetchall()
            cur.close()
            conn.close()
            if revs:
                lines = []
                for r in revs:
                    stars    = '★' * (r[3] or 5) + '☆' * (5 - (r[3] or 5))
                    role_str = f" ({r[1]})" if r[1] else ""
                    lines.append(f"👤 {r[0]}{role_str} {stars}\n💬 {r[2]}")
                reply = "Останні 5 відгуків:\n\n" + "\n\n".join(lines)
            else:
                reply = "Відгуків немає."

        else:
            reply = "Невідома команда. Введіть /start для списку команд."

        requests.post(
            f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
            data={"chat_id": chat_id, "text": reply},
            timeout=5
        )
    except Exception as e:
        print(f"Webhook error: {e}")

    return "ok"


if __name__ == '__main__':
    app.run()
