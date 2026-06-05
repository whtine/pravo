import os
import requests
import psycopg2
from flask import Flask, render_template, request

app = Flask(__name__)
DB_URL = "postgresql://pravodb_user:8A4IjLRmwrTRvdU5IGFmFBcLrjSzKV2n@dpg-d8heof28pkls73ccbitg-a.ohio-postgres.render.com/pravodb"

def get_db_connection():
    return psycopg2.connect(DB_URL)

@app.route('/send-request', methods=['POST'])
def send_request():
    # Данные из формы
    name = request.form.get('name')
    phone = request.form.get('phone')
    country_code = request.form.get('country_code', '')
    full_phone = f"{country_code}{phone}"
    service = request.form.get('service')
    message = request.form.get('message')

    # 1. Сохранение в БД
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO leads (name, phone, service, message) VALUES (%s, %s, %s, %s)",
                (name, full_phone, service, message))
    conn.commit()
    cur.close()
    conn.close()

    # 2. Отправка в ТГ
    text = f"📩 <b>Нова заявка!</b>\nІм'я: {name}\nТелефон: {full_phone}\nПослуга: {service}\nПитання: {message}"
    requests.post(f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage", 
                  data={"chat_id": os.environ['TG_CHAT_ID'], "text": text, "parse_mode": "HTML"})
    
    return "Дякуємо!"

# Эндпоинт для команд бота (настройте Webhook в BotFather на этот URL)
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
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
        reply = "Останні 5 заявок:\n" + "\n".join([f"{l[0]} ({l[1]}) - {l[2]}" for l in leads])
    else:
        reply = "Невідома команда."

    requests.post(f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage", 
                  data={"chat_id": chat_id, "text": reply})
    return "ok"

if __name__ == '__main__':
    app.run()
