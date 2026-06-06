import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'library.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    DRM_ENCRYPTION_KEY = os.environ.get('DRM_KEY') or 'drm-encryption-key-32bytes-long!!!'
    
    MAX_BORROW_DAYS = 14
    MAX_CONCURRENT_BORROWS = 3
    RESERVATION_EXPIRE_HOURS = 24
    
    BOOKS_DIR = os.path.join(basedir, 'books')
    ENCRYPTED_BOOKS_DIR = os.path.join(basedir, 'encrypted_books')
    
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
