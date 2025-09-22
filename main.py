import os
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash

# --- Настройка логирования ---
logging.basicConfig(filename='server.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

# --- Инициализация приложения ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
# Используем eventlet для асинхронной работы, что рекомендуется для SocketIO
socketio = SocketIO(app, async_mode='eventlet')

# --- Модели базы данных ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_online = db.Column(db.Boolean, default=False)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<User {self.username}>'

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_username = db.Column(db.String(80), nullable=False)
    recipient_username = db.Column(db.String(80), nullable=False)
    encrypted_content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)

    def __repr__(self):
        return f'<Message from {self.sender_username} to {self.recipient_username}>'

# --- Маршруты Flask (для страниц) ---
@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('chat'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['username'] = user.username
            logging.info(f"User '{username}' logged in successfully.")
            return redirect(url_for('chat'))
        else:
            flash('Неверный логин или пароль')
            logging.warning(f"Failed login attempt for username '{username}'.")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        password2 = request.form['password2']

        if User.query.filter_by(username=username).first():
            flash('Пользователь с таким именем уже существует')
            return redirect(url_for('register'))
        
        if password != password2:
            flash('Пароли не совпадают')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password_hash=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        logging.info(f"New user '{username}' registered.")
        session['username'] = username
        return redirect(url_for('chat'))
    return render_template('register.html')

@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect(url_for('login'))
    all_users = User.query.filter(User.username != session['username']).all()
    return render_template('chat.html', username=session['username'], users=all_users)

@app.route('/logout')
def logout():
    username = session.get('username')
    if username:
        user = User.query.filter_by(username=username).first()
        if user:
            user.is_online = False
            user.last_seen = datetime.utcnow()
            db.session.commit()
            logging.info(f"User '{username}' logged out.")
        session.pop('username', None)
    return redirect(url_for('login'))

# --- Обработчики событий SocketIO ---
@socketio.on('connect')
def handle_connect():
    if 'username' in session:
        username = session['username']
        user = User.query.filter_by(username=username).first()
        if user:
            user.is_online = True
            db.session.commit()
            # Присоединяем пользователя к "комнате" с его именем
            join_room(username)
            logging.info(f"User '{username}' connected. SID: {request.sid}")
            # Оповещаем всех о статусе
            emit('status_update', {'username': username, 'is_online': True, 'last_seen': ''}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if 'username' in session:
        username = session['username']
        user = User.query.filter_by(username=username).first()
        if user:
            user.is_online = False
            user.last_seen = datetime.utcnow()
            db.session.commit()
            logging.info(f"User '{username}' disconnected.")
            # Оповещаем всех о статусе
            emit('status_update', {
                'username': username, 
                'is_online': False, 
                'last_seen': user.last_seen.strftime('%Y-%m-%d %H:%M')
            }, broadcast=True)

@socketio.on('send_message')
def handle_send_message(data):
    sender = session['username']
    recipient = data['recipient']
    encrypted_content = data['content']

    message = Message(sender_username=sender, recipient_username=recipient, encrypted_content=encrypted_content)
    db.session.add(message)
    db.session.commit()
    
    logging.info(f"Message from '{sender}' to '{recipient}' stored.")

    # Отправляем сообщение получателю (если он в своей комнате) и отправителю
    emit('new_message', {
        'sender': sender,
        'recipient': recipient,
        'content': encrypted_content,
        'timestamp': message.timestamp.strftime('%H:%M')
    }, room=recipient)
    
    emit('new_message', {
        'sender': sender,
        'recipient': recipient,
        'content': encrypted_content,
        'timestamp': message.timestamp.strftime('%H:%M')
    }, room=sender)

@socketio.on('get_chat_history')
def handle_get_chat_history(data):
    user1 = session['username']
    user2 = data['contact']
    
    messages = Message.query.filter(
        ((Message.sender_username == user1) & (Message.recipient_username == user2)) |
        ((Message.sender_username == user2) & (Message.recipient_username == user1))
    ).order_by(Message.timestamp.asc()).all()
    
    history = [{
        'sender': msg.sender_username,
        'content': msg.encrypted_content,
        'timestamp': msg.timestamp.strftime('%H:%M')
    } for msg in messages]
    
    emit('chat_history', {'contact': user2, 'history': history})

# --- Запуск приложения ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # Replit использует свой веб-сервер, но для локального теста это было бы так:
    socketio.run(app, host='0.0.0.0', port=8080, debug=True)
