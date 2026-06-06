from datetime import datetime
from flask import current_app
from app import db
from app.models import Book, Reservation, Borrow, User


class ReservationService:
    
    @staticmethod
    def can_reserve_book(reader_id, book_id):
        reader = User.query.get(reader_id)
        if not reader or not reader.is_reader:
            return False, "Invalid reader"
        
        book = Book.query.get(book_id)
        if not book:
            return False, "Book not found"
        
        if book.available_copies > 0:
            return False, "Book is available for borrowing, no need to reserve"
        
        active_borrow = Borrow.query.filter_by(
            reader_id=reader_id,
            book_id=book_id,
            status='active'
        ).first()
        if active_borrow:
            return False, "You already have this book borrowed"
        
        existing_reservation = Reservation.query.filter_by(
            reader_id=reader_id,
            book_id=book_id
        ).filter(
            Reservation.status.in_(['pending', 'available'])
        ).first()
        if existing_reservation:
            return False, "You already have a reservation for this book"
        
        if not reader.can_borrow():
            return False, "You have reached maximum concurrent borrows"
        
        return True, "Can reserve"
    
    @staticmethod
    def reserve_book(reader_id, book_id):
        can_reserve, message = ReservationService.can_reserve_book(reader_id, book_id)
        if not can_reserve:
            return None, message
        
        pending_count = Reservation.query.filter_by(
            book_id=book_id,
            status='pending'
        ).count()
        
        reservation = Reservation(
            reader_id=reader_id,
            book_id=book_id,
            queue_position=pending_count + 1
        )
        
        db.session.add(reservation)
        db.session.commit()
        
        return reservation, "Reservation placed successfully"
    
    @staticmethod
    def cancel_reservation(reservation_id, reader_id=None):
        reservation = Reservation.query.get(reservation_id)
        if not reservation:
            return False, "Reservation not found"
        
        if reader_id and reservation.reader_id != reader_id:
            return False, "This reservation does not belong to you"
        
        if reservation.status not in ['pending', 'available']:
            return False, "Cannot cancel this reservation"
        
        book_id = reservation.book_id
        cancelled_position = reservation.queue_position
        
        reservation.cancel()
        db.session.commit()
        
        ReservationService._update_queue_positions(book_id, cancelled_position)
        
        return True, "Reservation cancelled successfully"
    
    @staticmethod
    def get_reader_reservations(reader_id, status=None):
        query = Reservation.query.filter_by(reader_id=reader_id)
        if status:
            query = query.filter_by(status=status)
        return query.order_by(Reservation.reservation_date.desc()).all()
    
    @staticmethod
    def get_book_reservations(book_id, status=None):
        query = Reservation.query.filter_by(book_id=book_id)
        if status:
            query = query.filter_by(status=status)
        return query.order_by(Reservation.queue_position.asc()).all()
    
    @staticmethod
    def process_available_book(book_id):
        book = Book.query.get(book_id)
        if not book or book.available_copies <= 0:
            return 0
        
        processed = 0
        pending_reservations = Reservation.query.filter_by(
            book_id=book_id,
            status='pending'
        ).order_by(Reservation.queue_position.asc()).all()
        
        for reservation in pending_reservations:
            if book.available_copies <= processed:
                break
            
            reader = User.query.get(reservation.reader_id)
            if reader and reader.can_borrow():
                reservation.mark_available()
                reservation.notified = True
                processed += 1
        
        db.session.commit()
        return processed
    
    @staticmethod
    def process_expired_reservations():
        now = datetime.utcnow()
        expired = Reservation.query.filter(
            Reservation.status == 'available',
            Reservation.expiry_date < now
        ).all()
        
        count = 0
        for reservation in expired:
            book_id = reservation.book_id
            cancelled_position = reservation.queue_position
            reservation.mark_expired()
            count += 1
            
            ReservationService._update_queue_positions(book_id, cancelled_position)
            ReservationService.process_available_book(book_id)
        
        db.session.commit()
        return count
    
    @staticmethod
    def _update_queue_positions(book_id, cancelled_position):
        affected = Reservation.query.filter(
            Reservation.book_id == book_id,
            Reservation.status == 'pending',
            Reservation.queue_position > cancelled_position
        ).all()
        
        for r in affected:
            r.queue_position -= 1
        
        db.session.commit()
    
    @staticmethod
    def get_queue_position(reader_id, book_id):
        reservation = Reservation.query.filter_by(
            reader_id=reader_id,
            book_id=book_id
        ).filter(
            Reservation.status.in_(['pending', 'available'])
        ).first()
        
        if not reservation:
            return None
        
        return {
            'status': reservation.status,
            'position': reservation.queue_position if reservation.status == 'pending' else 0,
            'total_pending': Reservation.query.filter_by(
                book_id=book_id,
                status='pending'
            ).count(),
            'expiry_date': reservation.expiry_date if reservation.status == 'available' else None
        }
    
    @staticmethod
    def claim_reservation(reservation_id, reader_id):
        reservation = Reservation.query.get(reservation_id)
        if not reservation:
            return False, "Reservation not found"
        
        if reservation.reader_id != reader_id:
            return False, "This reservation does not belong to you"
        
        if reservation.status != 'available':
            return False, "Reservation is not available for claiming"
        
        if reservation.is_expired:
            reservation.mark_expired()
            db.session.commit()
            return False, "Reservation has expired"
        
        from app.services.borrow_service import BorrowService
        borrow, message = BorrowService.borrow_book(reader_id, reservation.book_id)
        
        if borrow:
            reservation.mark_fulfilled()
            db.session.commit()
            return True, "Book borrowed successfully from reservation"
        
        return False, message
