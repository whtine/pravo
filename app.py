import os
import requests
import psycopg2
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Подключение к БД через переменную окружения (настройте в Render)
DB_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    # sslmode='require' обязательно для Render
    return psycopg2.connect(DB_URL, sslmode='require')

# --- МАРШРУТЫ СТРАНИЦ ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/service')
def service_page():
    return render_template('service.html')

@app.route('/test')
def test_page():
    return render_template('test.html')

# --- ОБРАБОТКА ЗАЯВОК (LEADS) ---
@app.route('/send-request', methods=['POST'])
def send_request():
    name = request.form.get('name')
    phone = request.form.get('phone')
    country_code = request.form.get('country_code', '')
    full_phone = f"{country_code}{phone}"
    service = request.form.get('service')
    message = request.form.get('message')

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO leads (name, phone, service, message) VALUES (%s, %s, %s, %s)",
                (name, full_phone, service, message))
    conn.commit()
    cur.close()
    conn.close()

    # Уведомление в ТГ
    text = f"📩 <b>Нова заявка!</b>\nІм'я: {name}\nТелефон: {full_phone}\nПослуга: {service}\nПитання: {message}"
    requests.post(f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage", 
                  data={"chat_id": os.environ['TG_CHAT_ID'], "text": text, "parse_mode": "HTML"})
    
    return jsonify({"status": "success"})

# --- СИСТЕМА ОТЗЫВОВ (REVIEWS) ---
@app.route('/save-review', methods=['POST'])
def save_review():
    name = request.form.get('name')
    service = request.form.get('service', 'Загальний')
    review_text = request.form.get('review_text')
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO reviews (name, service, review_text) VALUES (%s, %s, %s)",
                (name, service, review_text))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/get-reviews', methods=['GET'])
def get_reviews():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, service, review_text FROM reviews ORDER BY created_at DESC LIMIT 10")
    reviews = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({"reviews": [{"name": r[0], "service": r[1], "text": r[2]} for r in reviews]})

# --- ТЕЛЕГРАМ БОТ (WEBHOOK) ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    chat_id = data['message']['chat']['id']
    text = data['message'].get('text', '')

    if text == '/start':
        reply = "Вітаю! Команди:\n/history - заявки\n/reviews - останні 5 відгуків"
    elif text == '/history':
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, phone, service FROM leads ORDER BY created_at DESC LIMIT 5")
        leads = cur.fetchall()
        cur.close()
        conn.close()
        reply = "Останні 5 заявок:\n" + "\n".join([f"👤 {l[0]} | 📞 {l[1]} | 🛠 {l[2]}" for l in leads]) if leads else "Заявок немає."
    elif text == '/reviews':
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, review_text FROM reviews ORDER BY created_at DESC LIMIT 5")
        reviews = cur.fetchall()
        cur.close()
        conn.close()
        reply = "Останні 5 відгуків:\n\n" + "\n\n".join([f"👤 {r[0]}:\n💬 {r[1]}" for r in reviews]) if reviews else "Відгуків немає."
    else:
        reply = "Невідома команда."

    requests.post(f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage", 
                  data={"chat_id": chat_id, "text": reply})
    return "ok"

if __name__ == '__main__':
    app.run()
