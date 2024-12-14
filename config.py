import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'static/uploads')
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/default_db')
