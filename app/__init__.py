import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from apscheduler.schedulers.background import BackgroundScheduler
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = '请先登录'

scheduler = BackgroundScheduler(timezone='Asia/Shanghai')

def create_app(config_class=Config, seed_db=True):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    os.makedirs(app.config['BOOKS_DIR'], exist_ok=True)
    os.makedirs(app.config['ENCRYPTED_BOOKS_DIR'], exist_ok=True)
    
    db.init_app(app)
    login_manager.init_app(app)
    
    from app.models import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    from app.routes.auth import bp as auth_bp
    from app.routes.reader import bp as reader_bp
    from app.routes.admin import bp as admin_bp
    from app.routes.api import bp as api_bp
    from app.routes.main import bp as main_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(reader_bp, url_prefix='/reader')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(api_bp, url_prefix='/api')
    
    from app.scheduler import start_scheduler
    start_scheduler(app)
    
    with app.app_context():
        from app import models
        db.create_all()
        if seed_db:
            from app.seed import seed_database
            seed_database()
    
    return app
