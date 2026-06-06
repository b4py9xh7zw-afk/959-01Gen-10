from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app import db
from app.models import Book, Borrow, Reservation
from app.services.borrow_service import BorrowService
from app.services.reservation_service import ReservationService
from app.drm import get_secure_book_content, create_drm_watermark, validate_read_permission

bp = Blueprint('reader', __name__)


@bp.before_request
@login_required
def before_request():
    if not current_user.is_reader:
        abort(403)


@bp.route('/')
def dashboard():
    active_borrows = BorrowService.get_reader_borrows(current_user.id, status='active')
    pending_reservations = ReservationService.get_reader_reservations(current_user.id, status='pending')
    available_reservations = ReservationService.get_reader_reservations(current_user.id, status='available')
    history = BorrowService.get_reader_borrows(current_user.id)[:5]
    
    return render_template('reader/dashboard.html',
                           active_borrows=active_borrows,
                           pending_reservations=pending_reservations,
                           available_reservations=available_reservations,
                           history=history)


@bp.route('/books')
def books():
    books = Book.query.all()
    return render_template('reader/books.html', books=books)


@bp.route('/books/<int:book_id>')
def book_detail(book_id):
    book = Book.query.get_or_404(book_id)
    can_borrow, message = BorrowService.can_borrow_book(current_user.id, book_id)
    can_reserve, reserve_message = ReservationService.can_reserve_book(current_user.id, book_id)
    queue_info = ReservationService.get_queue_position(current_user.id, book_id)
    
    return render_template('reader/book_detail.html',
                           book=book,
                           can_borrow=can_borrow,
                           borrow_message=message,
                           can_reserve=can_reserve,
                           reserve_message=reserve_message,
                           queue_info=queue_info)


@bp.route('/borrow/<int:book_id>', methods=['POST'])
def borrow_book(book_id):
    borrow, message = BorrowService.borrow_book(current_user.id, book_id)
    if borrow:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('reader.book_detail', book_id=book_id))


@bp.route('/return/<int:borrow_id>', methods=['POST'])
def return_book(borrow_id):
    success, message = BorrowService.return_book(borrow_id, current_user.id)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('reader.dashboard'))


@bp.route('/extend/<int:borrow_id>', methods=['POST'])
def extend_borrow(borrow_id):
    days = int(request.form.get('days', 7))
    success, message = BorrowService.extend_borrow(borrow_id, current_user.id, days)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('reader.dashboard'))


@bp.route('/reserve/<int:book_id>', methods=['POST'])
def reserve_book(book_id):
    reservation, message = ReservationService.reserve_book(current_user.id, book_id)
    if reservation:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('reader.book_detail', book_id=book_id))


@bp.route('/cancel_reservation/<int:reservation_id>', methods=['POST'])
def cancel_reservation(reservation_id):
    success, message = ReservationService.cancel_reservation(reservation_id, current_user.id)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('reader.dashboard'))


@bp.route('/claim_reservation/<int:reservation_id>', methods=['POST'])
def claim_reservation(reservation_id):
    success, message = ReservationService.claim_reservation(reservation_id, current_user.id)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('reader.dashboard'))


@bp.route('/read/<int:borrow_id>')
def read_book(borrow_id):
    is_valid, result = validate_read_permission(borrow_id, current_user.id)
    if not is_valid:
        flash(result, 'error')
        return redirect(url_for('reader.dashboard'))
    
    borrow = result
    
    try:
        content = get_secure_book_content(borrow)
        content = create_drm_watermark(content, current_user.id, borrow_id)
        
        return render_template('reader/read_book.html',
                               book=borrow.book,
                               borrow=borrow,
                               content=content)
    except (PermissionError, FileNotFoundError) as e:
        flash(str(e), 'error')
        return redirect(url_for('reader.dashboard'))


@bp.route('/history')
def borrow_history():
    borrows = BorrowService.get_reader_borrows(current_user.id)
    reservations = ReservationService.get_reader_reservations(current_user.id)
    return render_template('reader/history.html',
                           borrows=borrows,
                           reservations=reservations)
