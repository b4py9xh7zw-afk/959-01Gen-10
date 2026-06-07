from datetime import datetime, timedelta
from flask import current_app
from app import db
from app.models import Book, Borrow, License, User, Reservation
from app.drm import generate_drm_token, log_drm_action


class BorrowService:
    
    @staticmethod
    def can_borrow_book(reader_id, book_id):
        reader = User.query.get(reader_id)
        if not reader or not reader.is_reader:
            return False, "Invalid reader"
        
        if not reader.can_borrow():
            return False, f"Maximum {current_app.config['MAX_CONCURRENT_BORROWS']} concurrent borrows reached"
        
        active_borrow = Borrow.query.filter_by(
            reader_id=reader_id,
            book_id=book_id,
            status='active'
        ).first()
        if active_borrow:
            return False, "You already have this book borrowed"
        
        book = Book.query.get(book_id)
        if not book:
            return False, "Book not found"
        
        from app.models import Reservation
        available_reservation = Reservation.query.filter_by(
            reader_id=reader_id,
            book_id=book_id,
            status='available'
        ).first()
        
        if not available_reservation:
            pending_count = Reservation.query.filter_by(
                book_id=book_id,
                status='pending'
            ).count()
            available_count = Reservation.query.filter_by(
                book_id=book_id,
                status='available'
            ).count()
            if pending_count > 0 or available_count > 0:
                return False, "This book has a waiting list. Please make a reservation."
        
        if book.available_copies <= 0:
            return False, "No copies available for borrowing"
        
        return True, "Can borrow"
    
    @staticmethod
    def borrow_book(reader_id, book_id):
        can_borrow, message = BorrowService.can_borrow_book(reader_id, book_id)
        if not can_borrow:
            return None, message
        
        book = Book.query.get(book_id)
        
        available_license = None
        for license in book.licenses.filter_by(is_active=True).all():
            if license.expiry_date and license.expiry_date < datetime.utcnow():
                continue
            if license.available_copies > 0:
                available_license = license
                break
        
        if not available_license:
            return None, "No available license for this book"
        
        borrow = Borrow(
            reader_id=reader_id,
            book_id=book_id,
            license_id=available_license.id
        )
        borrow.set_due_date()
        
        borrow.drm_token = generate_drm_token(borrow.id)
        
        available_license.total_borrows += 1
        
        db.session.add(borrow)
        
        from app.services.reservation_service import ReservationService
        
        pending_reservations = Reservation.query.filter_by(
            book_id=book_id,
            reader_id=reader_id,
            status='pending'
        ).all()
        for r in pending_reservations:
            cancelled_position = r.queue_position
            r.mark_fulfilled()
            ReservationService._update_queue_positions(book_id, cancelled_position)
        
        available_reservations = Reservation.query.filter_by(
            book_id=book_id,
            reader_id=reader_id,
            status='available'
        ).all()
        for r in available_reservations:
            cancelled_position = r.queue_position
            r.mark_fulfilled()
            ReservationService._update_queue_positions(book_id, cancelled_position)
        
        db.session.commit()
        
        log_drm_action(borrow.id, 'book_borrowed', success=True)
        
        return borrow, "Book borrowed successfully"
    
    @staticmethod
    def return_book(borrow_id, reader_id=None):
        borrow = Borrow.query.get(borrow_id)
        if not borrow:
            return False, "Borrow record not found"
        
        if reader_id and borrow.reader_id != reader_id:
            return False, "This borrow does not belong to you"
        
        if borrow.status != 'active':
            return False, "This book is not currently borrowed"
        
        borrow.return_book()
        db.session.commit()
        
        log_drm_action(borrow_id, 'book_returned', success=True)
        
        from app.services.reservation_service import ReservationService
        ReservationService.process_available_book(borrow.book_id)
        
        return True, "Book returned successfully"
    
    @staticmethod
    def get_reader_borrows(reader_id, status=None):
        query = Borrow.query.filter_by(reader_id=reader_id)
        if status:
            query = query.filter_by(status=status)
        return query.order_by(Borrow.borrow_date.desc()).all()
    
    @staticmethod
    def get_book_borrows(book_id, status=None):
        query = Borrow.query.filter_by(book_id=book_id)
        if status:
            query = query.filter_by(status=status)
        return query.order_by(Borrow.borrow_date.desc()).all()
    
    @staticmethod
    def process_overdue_books():
        now = datetime.utcnow()
        overdue_borrows = Borrow.query.filter(
            Borrow.status == 'active',
            Borrow.due_date < now
        ).all()
        
        count = 0
        book_ids = set()
        for borrow in overdue_borrows:
            borrow.return_book()
            borrow.mark_overdue()
            log_drm_action(borrow.id, 'book_overdue', success=True)
            book_ids.add(borrow.book_id)
            count += 1
        
        db.session.commit()
        
        from app.services.reservation_service import ReservationService
        for book_id in book_ids:
            ReservationService.process_available_book(book_id)
        
        return count
    
    @staticmethod
    def get_borrow_details(borrow_id, reader_id=None):
        borrow = Borrow.query.get(borrow_id)
        if not borrow:
            return None, "Borrow record not found"
        
        if reader_id and borrow.reader_id != reader_id:
            return None, "Access denied"
        
        return borrow, None
    
    @staticmethod
    def extend_borrow(borrow_id, reader_id, days=7):
        borrow = Borrow.query.get(borrow_id)
        if not borrow:
            return False, "Borrow record not found"
        
        if borrow.reader_id != reader_id:
            return False, "This borrow does not belong to you"
        
        if borrow.status != 'active':
            return False, "Cannot extend a non-active borrow"
        
        if borrow.is_overdue:
            return False, "Cannot extend an overdue book"
        
        book = borrow.book
        if book.pending_reservations_count > 0:
            return False, "Cannot extend - there are reservations for this book"
        
        license = borrow.license
        max_extension = license.borrow_period_days
        if days > max_extension:
            days = max_extension
        
        borrow.due_date = borrow.due_date + timedelta(days=days)
        borrow.drm_token = generate_drm_token(borrow.id)
        db.session.commit()
        
        log_drm_action(borrow.id, 'borrow_extended', success=True, 
                       details=f"Extended by {days} days")
        
        return True, f"Borrow extended by {days} days"
