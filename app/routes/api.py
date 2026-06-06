from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app import db
from app.models import Book, Borrow, Reservation
from app.services.borrow_service import BorrowService
from app.services.reservation_service import ReservationService
from app.drm import validate_read_permission, get_secure_book_content, create_drm_watermark
from datetime import datetime

bp = Blueprint('api', __name__)


@bp.route('/books', methods=['GET'])
def get_books():
    books = Book.query.all()
    return jsonify([{
        'id': b.id,
        'title': b.title,
        'author': b.author,
        'isbn': b.isbn,
        'description': b.description,
        'available_copies': b.available_copies,
        'total_copies': b.total_licensed_copies,
        'pending_reservations': b.pending_reservations_count
    } for b in books])


@bp.route('/books/<int:book_id>', methods=['GET'])
def get_book(book_id):
    book = Book.query.get_or_404(book_id)
    return jsonify({
        'id': book.id,
        'title': book.title,
        'author': book.author,
        'isbn': book.isbn,
        'description': book.description,
        'available_copies': book.available_copies,
        'total_copies': book.total_licensed_copies,
        'pending_reservations': book.pending_reservations_count
    })


@bp.route('/borrow/<int:book_id>', methods=['POST'])
@login_required
def api_borrow_book(book_id):
    if current_user.is_reader:
        borrow, message = BorrowService.borrow_book(current_user.id, book_id)
        if borrow:
            return jsonify({
                'success': True,
                'message': message,
                'borrow_id': borrow.id,
                'due_date': borrow.due_date.isoformat()
            })
        return jsonify({'success': False, 'message': message}), 400
    return jsonify({'success': False, 'message': 'Permission denied'}), 403


@bp.route('/return/<int:borrow_id>', methods=['POST'])
@login_required
def api_return_book(borrow_id):
    if current_user.is_reader:
        success, message = BorrowService.return_book(borrow_id, current_user.id)
        if success:
            return jsonify({'success': True, 'message': message})
        return jsonify({'success': False, 'message': message}), 400
    return jsonify({'success': False, 'message': 'Permission denied'}), 403


@bp.route('/reserve/<int:book_id>', methods=['POST'])
@login_required
def api_reserve_book(book_id):
    if current_user.is_reader:
        reservation, message = ReservationService.reserve_book(current_user.id, book_id)
        if reservation:
            return jsonify({
                'success': True,
                'message': message,
                'reservation_id': reservation.id,
                'queue_position': reservation.queue_position
            })
        return jsonify({'success': False, 'message': message}), 400
    return jsonify({'success': False, 'message': 'Permission denied'}), 403


@bp.route('/reader/borrows', methods=['GET'])
@login_required
def api_reader_borrows():
    if current_user.is_reader:
        borrows = BorrowService.get_reader_borrows(current_user.id)
        return jsonify([{
            'id': b.id,
            'book_id': b.book_id,
            'book_title': b.book.title,
            'status': b.status,
            'borrow_date': b.borrow_date.isoformat(),
            'due_date': b.due_date.isoformat(),
            'remaining_days': b.remaining_days,
            'can_access': b.can_access
        } for b in borrows])
    return jsonify({'success': False, 'message': 'Permission denied'}), 403


@bp.route('/reader/reservations', methods=['GET'])
@login_required
def api_reader_reservations():
    if current_user.is_reader:
        reservations = ReservationService.get_reader_reservations(current_user.id)
        return jsonify([{
            'id': r.id,
            'book_id': r.book_id,
            'book_title': r.book.title,
            'status': r.status,
            'queue_position': r.queue_position,
            'reservation_date': r.reservation_date.isoformat(),
            'expiry_date': r.expiry_date.isoformat() if r.expiry_date else None
        } for r in reservations])
    return jsonify({'success': False, 'message': 'Permission denied'}), 403


@bp.route('/read/<int:borrow_id>', methods=['GET'])
@login_required
def api_read_book(borrow_id):
    if not current_user.is_reader:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403
    
    is_valid, result = validate_read_permission(borrow_id, current_user.id)
    if not is_valid:
        return jsonify({'success': False, 'message': result}), 400
    
    borrow = result
    
    try:
        content = get_secure_book_content(borrow)
        content = create_drm_watermark(content, current_user.id, borrow_id)
        
        return jsonify({
            'success': True,
            'book_id': borrow.book.id,
            'book_title': borrow.book.title,
            'content': content,
            'remaining_days': borrow.remaining_days,
            'due_date': borrow.due_date.isoformat()
        })
    except (PermissionError, FileNotFoundError) as e:
        return jsonify({'success': False, 'message': str(e)}), 403


@bp.route('/admin/stats', methods=['GET'])
@login_required
def api_admin_stats():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403
    
    from sqlalchemy import func
    from app.models import License, User
    
    total_books = Book.query.count()
    total_licenses = License.query.count()
    total_users = User.query.filter_by(role='reader').count()
    active_borrows = Borrow.query.filter_by(status='active').count()
    total_borrows = Borrow.query.count()
    
    total_concurrent = db.session.query(func.sum(License.concurrent_copies)).scalar() or 0
    utilization_rate = (active_borrows / total_concurrent * 100) if total_concurrent > 0 else 0
    
    return jsonify({
        'success': True,
        'stats': {
            'total_books': total_books,
            'total_licenses': total_licenses,
            'total_concurrent_copies': total_concurrent,
            'total_users': total_users,
            'active_borrows': active_borrows,
            'total_borrows': total_borrows,
            'utilization_rate': round(utilization_rate, 2)
        }
    })
