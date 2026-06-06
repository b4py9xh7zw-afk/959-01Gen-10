from flask import Blueprint, render_template, abort, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.models import Book, License, Borrow, Reservation, User, DRMLog
from datetime import datetime, timedelta
from sqlalchemy import func

bp = Blueprint('admin', __name__)


@bp.before_request
@login_required
def before_request():
    if not current_user.is_admin:
        abort(403)


@bp.route('/')
def dashboard():
    total_books = Book.query.count()
    total_licenses = License.query.count()
    total_users = User.query.filter_by(role='reader').count()
    active_borrows = Borrow.query.filter_by(status='active').count()
    pending_reservations = Reservation.query.filter_by(status='pending').count()
    total_borrows = Borrow.query.count()
    
    total_concurrent = db.session.query(func.sum(License.concurrent_copies)).scalar() or 0
    utilization_rate = (active_borrows / total_concurrent * 100) if total_concurrent > 0 else 0
    
    overdue_count = Borrow.query.filter(
        Borrow.status == 'active',
        Borrow.due_date < datetime.utcnow()
    ).count()
    
    recent_borrows = Borrow.query.order_by(Borrow.borrow_date.desc()).limit(10).all()
    popular_books = Book.query.join(Borrow).group_by(Book.id).order_by(
        func.count(Borrow.id).desc()
    ).limit(5).all()
    
    return render_template('admin/dashboard.html',
                           total_books=total_books,
                           total_licenses=total_licenses,
                           total_users=total_users,
                           active_borrows=active_borrows,
                           pending_reservations=pending_reservations,
                           total_borrows=total_borrows,
                           utilization_rate=utilization_rate,
                           overdue_count=overdue_count,
                           recent_borrows=recent_borrows,
                           popular_books=popular_books)


@bp.route('/books')
def books():
    books = Book.query.all()
    return render_template('admin/books.html', books=books)


@bp.route('/books/<int:book_id>')
def book_detail(book_id):
    book = Book.query.get_or_404(book_id)
    licenses = book.licenses.all()
    borrows = book.borrows.order_by(Borrow.borrow_date.desc()).limit(20).all()
    reservations = book.reservations.order_by(Reservation.queue_position.asc()).all()
    
    total_borrows = book.borrows.count()
    total_reservations = book.reservations.count()
    
    return render_template('admin/book_detail.html',
                           book=book,
                           licenses=licenses,
                           borrows=borrows,
                           reservations=reservations,
                           total_borrows=total_borrows,
                           total_reservations=total_reservations)


@bp.route('/books/new', methods=['GET', 'POST'])
def new_book():
    if request.method == 'POST':
        title = request.form.get('title')
        author = request.form.get('author')
        isbn = request.form.get('isbn')
        description = request.form.get('description')
        concurrent_copies = int(request.form.get('concurrent_copies', 1))
        borrow_days = int(request.form.get('borrow_days', 14))
        
        book = Book(
            title=title,
            author=author,
            isbn=isbn,
            description=description
        )
        book.generate_encryption_key()
        db.session.add(book)
        db.session.flush()
        
        license = License(
            book_id=book.id,
            concurrent_copies=concurrent_copies,
            borrow_period_days=borrow_days
        )
        db.session.add(license)
        
        content = f"""
{title}

{'=' * 50}

这是《{title}》的电子版内容。

本书受DRM版权保护，仅供借阅者在有效期内阅读。
未经授权的复制、传播或分享均属于违法行为。

第一章

    这是第一章的内容。

第二章

    这是第二章的内容。

...

{'=' * 50}

【版权声明】
本书由数字图书馆授权借阅
所有内容受版权法和DRM技术保护
"""
        
        import os
        from flask import current_app
        import hashlib
        from app.drm import encrypt_content
        
        books_dir = current_app.config['BOOKS_DIR']
        encrypted_dir = current_app.config['ENCRYPTED_BOOKS_DIR']
        
        content_path = os.path.join(books_dir, f"{book.id}.txt")
        with open(content_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        book.content_hash = content_hash
        
        encrypted = encrypt_content(content, book.encryption_key)
        encrypted_path = os.path.join(encrypted_dir, f"{book.id}.enc")
        with open(encrypted_path, 'wb') as f:
            f.write(encrypted)
        
        book.content_path = encrypted_path
        
        db.session.commit()
        flash('书籍添加成功', 'success')
        return redirect(url_for('admin.book_detail', book_id=book.id))
    
    return render_template('admin/new_book.html')


@bp.route('/licenses')
def licenses():
    licenses = License.query.all()
    return render_template('admin/licenses.html', licenses=licenses)


@bp.route('/licenses/new/<int:book_id>', methods=['GET', 'POST'])
def new_license(book_id):
    book = Book.query.get_or_404(book_id)
    
    if request.method == 'POST':
        concurrent_copies = int(request.form.get('concurrent_copies', 1))
        borrow_days = int(request.form.get('borrow_days', 14))
        expiry_days = int(request.form.get('expiry_days', 0))
        
        license = License(
            book_id=book_id,
            concurrent_copies=concurrent_copies,
            borrow_period_days=borrow_days
        )
        
        if expiry_days > 0:
            license.expiry_date = datetime.utcnow() + timedelta(days=expiry_days)
        
        db.session.add(license)
        db.session.commit()
        flash('版权添加成功', 'success')
        return redirect(url_for('admin.book_detail', book_id=book_id))
    
    return render_template('admin/new_license.html', book=book)


@bp.route('/borrows')
def borrows():
    status = request.args.get('status')
    query = Borrow.query
    
    if status:
        query = query.filter_by(status=status)
    
    borrows = query.order_by(Borrow.borrow_date.desc()).all()
    return render_template('admin/borrows.html', borrows=borrows, status=status)


@bp.route('/reservations')
def reservations():
    status = request.args.get('status')
    query = Reservation.query
    
    if status:
        query = query.filter_by(status=status)
    
    reservations = query.order_by(Reservation.reservation_date.desc()).all()
    return render_template('admin/reservations.html', reservations=reservations, status=status)


@bp.route('/users')
def users():
    users = User.query.filter_by(role='reader').all()
    return render_template('admin/users.html', users=users)


@bp.route('/users/<int:user_id>')
def user_detail(user_id):
    user = User.query.get_or_404(user_id)
    if not user.is_reader:
        abort(403)
    
    borrows = user.borrows.order_by(Borrow.borrow_date.desc()).all()
    reservations = user.reservations.order_by(Reservation.reservation_date.desc()).all()
    
    return render_template('admin/user_detail.html',
                           user=user,
                           borrows=borrows,
                           reservations=reservations)


@bp.route('/drm_logs')
def drm_logs():
    logs = DRMLog.query.order_by(DRMLog.timestamp.desc()).limit(100).all()
    return render_template('admin/drm_logs.html', logs=logs)


@bp.route('/reports')
def reports():
    stats = {}
    
    stats['total_books'] = Book.query.count()
    stats['total_licenses'] = License.query.count()
    stats['total_concurrent'] = db.session.query(func.sum(License.concurrent_copies)).scalar() or 0
    
    stats['total_borrows'] = Borrow.query.count()
    stats['active_borrows'] = Borrow.query.filter_by(status='active').count()
    stats['returned_borrows'] = Borrow.query.filter_by(status='returned').count()
    stats['overdue_borrows'] = Borrow.query.filter_by(status='overdue').count()
    
    stats['total_reservations'] = Reservation.query.count()
    stats['pending_reservations'] = Reservation.query.filter_by(status='pending').count()
    stats['fulfilled_reservations'] = Reservation.query.filter_by(status='fulfilled').count()
    stats['expired_reservations'] = Reservation.query.filter_by(status='expired').count()
    
    today = datetime.utcnow().date()
    stats['borrows_today'] = Borrow.query.filter(
        func.date(Borrow.borrow_date) == today
    ).count()
    
    stats['returns_today'] = Borrow.query.filter(
        func.date(Borrow.return_date) == today
    ).count()
    
    license_stats = []
    for license in License.query.all():
        license_stats.append({
            'license': license,
            'utilization_rate': license.utilization_rate,
            'total_borrows': license.total_borrows,
            'active_borrows': license.borrows.filter_by(status='active').count()
        })
    
    popular_books = Book.query.join(Borrow).group_by(Book.id).order_by(
        func.count(Borrow.id).desc()
    ).limit(10).all()
    
    book_borrow_counts = []
    for book in popular_books:
        count = book.borrows.count()
        book_borrow_counts.append((book, count))
    
    return render_template('admin/reports.html',
                           stats=stats,
                           license_stats=license_stats,
                           popular_books=book_borrow_counts)
