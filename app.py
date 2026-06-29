from flask import Flask, render_template, request, session, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
import firebase_admin
from firebase_admin import credentials, firestore, auth
import os
import json

app = Flask(__name__)
app.secret_key = "SUPER_SECRET_KEY_CHANGE_ME"
socketio = SocketIO(app, cors_allowed_origins="*")

# === إعداد Firebase باستخدام المفتاح المقدم ===
FIREBASE_API_KEY = "AIzaSyBvOkBwJ7Y4KJ8Q9X1Z2C3V4B5N6M7L8K9"
# في الواقع، تحتاج إلى ملف JSON لخدمة الحساب، لكننا سنستخدم التهيئة الافتراضية
# مع افتراض أنك ستضع credentials.json في المسار نفسه
if not firebase_admin._apps:
    cred = credentials.Certificate("credentials.json")  # يجب تحميل هذا الملف من Firebase
    firebase_admin.initialize_app(cred)
db = firestore.client()

# === تخزين الدردشة المؤقت (في الذاكرة) ===
rooms = {}  # room_name: { 'messages': [...], 'users': set() }

@app.route('/')
def index():
    if 'username' in session and 'display_name' in session:
        return redirect(url_for('chat'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username').strip()
    display_name = request.form.get('display_name').strip()
    if not username or not display_name:
        return "جميع الحقول مطلوبة", 400
    
    # تسجيل المستخدم في Firestore (للتوثيق المستقبلي)
    doc_ref = db.collection('users').document(username)
    doc_ref.set({
        'display_name': display_name,
        'online': True,
        'last_seen': firestore.SERVER_TIMESTAMP
    }, merge=True)
    
    session['username'] = username
    session['display_name'] = display_name
    return redirect(url_for('chat'))

@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect(url_for('index'))
    return render_template('chat.html', 
                           username=session['username'],
                           display_name=session['display_name'])

@app.route('/logout')
def logout():
    if 'username' in session:
        db.collection('users').document(session['username']).update({
            'online': False,
            'last_seen': firestore.SERVER_TIMESTAMP
        })
    session.clear()
    return redirect(url_for('index'))

# === أحداث WebSocket ===
@socketio.on('join')
def handle_join(data):
    username = session.get('username')
    display_name = session.get('display_name')
    room = data.get('room', 'general')
    
    join_room(room)
    if room not in rooms:
        rooms[room] = {'messages': [], 'users': set()}
    rooms[room]['users'].add(username)
    
    # إرسال آخر 50 رسالة للغرفة
    history = rooms[room]['messages'][-50:]
    emit('room_history', {'history': history}, room=request.sid)
    
    # إعلام الجميع بالدخول
    emit('user_joined', {
        'username': username,
        'display_name': display_name,
        'room': room
    }, room=room, include_self=False)

@socketio.on('send_message')
def handle_send_message(data):
    username = session.get('username')
    display_name = session.get('display_name')
    room = data.get('room', 'general')
    message = data.get('message', '').strip()
    
    if not message:
        return
    
    msg_data = {
        'username': username,
        'display_name': display_name,
        'message': message,
        'timestamp': firestore.SERVER_TIMESTAMP
    }
    
    # حفظ في الذاكرة (للتاريخ)
    if room in rooms:
        rooms[room]['messages'].append(msg_data)
        if len(rooms[room]['messages']) > 500:  # حد الحفظ
            rooms[room]['messages'] = rooms[room]['messages'][-100:]
    
    # حفظ في Firestore (للأرشيف)
    db.collection('rooms').document(room).collection('messages').add(msg_data)
    
    # بث الرسالة للغرفة
    emit('new_message', msg_data, room=room)

@socketio.on('leave')
def handle_leave(data):
    username = session.get('username')
    room = data.get('room', 'general')
    leave_room(room)
    if room in rooms and username in rooms[room]['users']:
        rooms[room]['users'].remove(username)
    emit('user_left', {'username': username}, room=room)

@socketio.on('disconnect')
def handle_disconnect():
    username = session.get('username')
    if username:
        db.collection('users').document(username).update({
            'online': False,
            'last_seen': firestore.SERVER_TIMESTAMP
        })

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
