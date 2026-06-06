from flask import Blueprint, render_template
from flask_login import login_required, current_user
from app.models import Book

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    books = Book.query.all()
    return render_template('index.html', books=books)
