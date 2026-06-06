from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User
from app import db

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user is None or not user.check_password(password):
            flash('用户名或密码错误', 'error')
            return redirect(url_for('auth.login'))
        
        login_user(user, remember=True)
        
        if user.is_admin:
            return redirect(url_for('admin.dashboard'))
        else:
            return redirect(url_for('reader.dashboard'))
    
    return render_template('auth/login.html')


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已成功退出登录', 'success')
    return redirect(url_for('main.index'))
