from app import scheduler
from app.services.borrow_service import BorrowService
from app.services.reservation_service import ReservationService


def start_scheduler(app):
    if not scheduler.running:
        scheduler.add_job(
            func=process_overdue_books_job,
            args=[app],
            trigger='cron',
            hour=0,
            minute=0,
            id='process_overdue_books',
            replace_existing=True
        )
        
        scheduler.add_job(
            func=process_expired_reservations_job,
            args=[app],
            trigger='interval',
            hours=1,
            id='process_expired_reservations',
            replace_existing=True
        )
        
        scheduler.start()


def process_overdue_books_job(app):
    with app.app_context():
        count = BorrowService.process_overdue_books()
        app.logger.info(f"Processed {count} overdue books")


def process_expired_reservations_job(app):
    with app.app_context():
        count = ReservationService.process_expired_reservations()
        app.logger.info(f"Processed {count} expired reservations")
