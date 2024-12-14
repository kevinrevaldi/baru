from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from pymongo import MongoClient
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import os
import json
import boto3
from botocore.exceptions import BotoCoreError, ClientError

os.environ["AWS_PROFILE"] = "Kevin"

bedrock_client = boto3.client(
    service_name="bedrock-runtime",
    region_name="us-east-1"
)

# Function to get response from Bedrock
def get_bedrock_response(prompt):
    try:
        response = bedrock_client.invoke_model(
            modelId='anthropic.claude-v2',
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                "prompt": prompt,
                "max_tokens_to_sample": 1000,
                "temperature": 0.9
            })
        )
        response_body = response['body'].read().decode('utf-8')
        return json.loads(response_body).get('completion', "No response received.")
    except Exception as e:
        # Log the actual error to debug
        print("Error details:", str(e))
        return "There was an error connecting to the AI model. Please try again later."




app = Flask(__name__)
app.config['SECRET_KEY'] = 'whitebrim'
app.config.from_object('config.Config')

#konfigurasi MongoDB
mongo_client = MongoClient(app.config['MONGO_URI'])
db = mongo_client['melanoma_scan']
users_collection = db['users']
uploads_collection = db['uploads']
guest_usage_collection = db['guest_usage']

#buat direktori penyimpanan file
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def get_guest_usage():
    guest_usage = guest_usage_collection.find_one({'_id': 'guest_usage'})
    if guest_usage:
        return guest_usage.get('uploads', 0), guest_usage.get('chatbot_interactions', 0)
    return 0, 0

def update_guest_usage(uploads, interactions):
    guest_usage_collection.update_one(
        {'_id': 'guest_usage'},
        {'$set': {'uploads': uploads, 'chatbot_interactions': interactions}},
        upsert=True
    )

#Helper 
def get_guest_uploads_count():
    return session.get('guest_uploads', 0)

def get_guest_chatbot_interactions():
    return session.get('guest_chatbot_interactions', 0)

#deklarasi fungsi manggil data dari file chatbot.json
def load_chatbot_data():
    with open('chatbot.json', 'r', encoding='utf-8') as f:
        return json.load(f)

#ngambil data dari json
chatbot_data = load_chatbot_data()


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = users_collection.find_one({'username': username})
        if user and check_password_hash(user['password'], password):
            session['user_id'] = str(user['_id'])
            session['username'] = user['username']
            session['email'] = user['email']
            session.pop('guest_uploads', None) 
            flash('Logged in successfully!', 'success')
            return redirect(url_for('index'))

        flash('Invalid credentials!', 'danger')

    return render_template('login.html')

@app.route('/')
def index():
    user_logged_in = 'user_id' in session
    username = session.get('username', 'Pengunjung')
    email = session.get('email', 'Pengunjung')
    return render_template('index.html', user_logged_in=user_logged_in, username=username, email=email)

@app.route('/contact')
def contact():
    #Cek apakah pengguna sudah login
    user_logged_in = 'user_id' in session
    return render_template('contact.html', user_logged_in=user_logged_in)


@app.route('/chatbot', methods=['GET', 'POST'])
def chatbot():
    user_logged_in = 'user_id' in session
    guest_uploads, guest_chatbot_interactions = get_guest_usage()
   
    
    if request.method == 'POST':
        if not user_logged_in and guest_chatbot_interactions >= 3:
            return jsonify({'error': 'You have reached the usage limit for the Chatbot. Please log in or register to continue.'}), 403

        user_message = request.form['message'].strip()
        if user_message:
            # Get response from Bedrock
            response = get_bedrock_response(user_message)

            if not user_logged_in:
                guest_chatbot_interactions += 1
                update_guest_usage(guest_uploads, guest_chatbot_interactions)
            
            return jsonify({'response': response})

    return render_template('chatbot.html', user_logged_in=user_logged_in)


@app.route('/get_response/<message>')
def get_response(message):
    response = chatbot_data.get(message.lower(), "Bot tidak mengerti pertanyaan Anda.")
    return jsonify({'response': response})

@app.route('/about')
def about():
    #Cek apakah pengguna sudah login
    user_logged_in = 'user_id' in session
    return render_template('about.html', user_logged_in=user_logged_in)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        username = request.form['username']
        password = request.form['password']

        if users_collection.find_one({'email': email}):
            flash('Email is already in use!', 'danger')
            return redirect(url_for('register'))

        if users_collection.find_one({'username': username}):
            flash('Username is already taken!', 'danger')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)

        users_collection.insert_one({
            'email': email,
            'username': username,
            'password': hashed_password
        })

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/detection', methods=['GET', 'POST'])
def detection():
    user_logged_in = 'user_id' in session
    guest_uploads, _ = get_guest_usage()
    modal_open = False

    if request.method == 'POST':
        if not user_logged_in and guest_uploads >= 3:
            flash('Please login or register to upload more images.', 'warning')
            modal_open = True
        else:
            image = request.files['image']
            if image:
                filename = secure_filename(image.filename)
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                image.save(image_path)

                upload_data = {
                    'user_id': session.get('user_id'),
                    'filename': filename
                }
                uploads_collection.insert_one(upload_data)

                session['uploaded_image'] = filename

                if not user_logged_in:
                    guest_uploads += 1
                    update_guest_usage(guest_uploads, _)

                flash('Image uploaded successfully!', 'success')
                return redirect(url_for('detection_result', user_logged_in=user_logged_in))

    return render_template(
        'detection-1.html', 
        user_logged_in=user_logged_in, 
        modal_open=modal_open,
        guest_uploads=guest_uploads
    )
@app.route('/detection/result')
def detection_result():
    #Cek apakah pengguna sudah login
    user_logged_in = 'user_id' in session
    
    uploaded_image = session.get('uploaded_image')
    if not uploaded_image:
        flash('No image uploaded!', 'danger')
        return redirect(url_for('detection'))

    return render_template('detection-2.html', uploaded_image=uploaded_image, user_logged_in=user_logged_in)

@app.route('/delete-image/<filename>', methods=['DELETE'])
def delete_image(filename):
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return jsonify({'success': True, 'redirect_url': url_for('detection')}), 200
        else:
            return jsonify({'success': False, 'message': 'File not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


if __name__ == '__main__':
    app.run('0.0.0.0', port=5000, debug=True)
