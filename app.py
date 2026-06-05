import os
import requests
import psycopg2
from flask import Flask, render_template, request

app = Flask(__name__)

# Берем URL базы из Environment Variables на Render
DB_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    # sslmode='require' обязательно для Render
    return psycopg2.connect(DB_URL, sslmode='require')

@app.route('/send-request', methods=['POST'])
def send_request():
    name = request.form.get('name')
    phone = request.form.get('phone')
    country_code = request.form.get('country_code', '')
    full_phone = f"{country_code}{phone}"
    service = request.form.get('service')
    message = request.form.get('message')

    # Сохранение в БД
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO leads (name, phone, service, message) VALUES (%s, %s, %s, %s)",
                (name, full_phone, service, message))
    conn.commit()
    cur.close()
    conn.close()

    # Отправка в ТГ
    text = f"📩 <b>Нова заявка!</b>\nІм'я: {name}\nТелефон: {full_phone}\nПослуга: {service}\nПитання: {message}"
    requests.post(f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage", 
                  data={"chat_id": os.environ['TG_CHAT_ID'], "text": text, "parse_mode": "HTML"})
    
    return "Дякуємо!"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    # Безопасное получение chat_id
    chat_id = data['message']['chat']['id']
    text = data['message'].get('text', '')

    if text == '/start':
        reply = "Вітаю! Я бот для прийому заявок. Використовуйте /history для перегляду останніх 5 заявок."
    elif text == '/history':
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, phone, service FROM leads ORDER BY created_at DESC LIMIT 5")
        leads = cur.fetchall()
        cur.close()
        conn.close()
        # Форматирование списка заявок
        if not leads:
            reply = "Заявок поки що немає."
        else:
            reply = "Останні 5 заявок:\n" + "\n".join([f"👤 {l[0]} | 📞 {l[1]} | 🛠 {l[2]}" for l in leads])
    else:
        reply = "Невідома команда."

    requests.post(f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage", 
                  data={"chat_id": chat_id, "text": reply})
    return "ok"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/service')
def service_page():  
    return render_template('service.html')

@app.route('/test')
def test_page():   
    return render_template('test.html')

if __name__ == '__main__':
    app.run()
