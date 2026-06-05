import os
import requests
from flask import Flask, render_template, request

app = Flask(__name__)

# Сюда приходят данные со всех форм
@app.route('/send-request', methods=['POST'])
def send_request():
    token = os.environ.get("TG_TOKEN")
    chat_id = os.environ.get("TG_CHAT_ID")
    
    # Собираем данные из формы
    name = request.form.get('name')
    phone = request.form.get('phone')
    service = request.form.get('service')
    message = request.form.get('message')
    page = request.form.get('page_source') # Откуда пришла форма

    text = f"📩 <b>Нова заявка!</b>\nСторінка: {page}\nІм'я: {name}\nТелефон: {phone}\nПослуга: {service}\nПитання: {message}"
    
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                  data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    
    return "Дякуємо! Ми зв'яжемося з вами."

# Маршруты для страниц
@app.route('/')
def index():
    return render_template('index.html')

# Страница услуг
@app.route('/service')
def service():
    return render_template('service.html')

# Если нужно добавить еще страницу, например 'about.html':
@app.route('/about')
def about():
    return render_template('about.html')

if __name__ == '__main__':
    app.run()
