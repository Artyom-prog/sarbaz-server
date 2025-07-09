from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)
users = []

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name')
    phone = data.get('phone')
    time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    users.append({'name': name, 'phone': phone, 'time': time})

    print(f"[{time}] {name} - {phone}")
    return jsonify({'status': 'ok'}), 200

@app.route('/users', methods=['GET'])
def get_users():
    return jsonify(users)

if __name__ == '__main__':
    app.run()
