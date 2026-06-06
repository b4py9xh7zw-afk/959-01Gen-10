from datetime import datetime, timedelta
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='reader')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    borrows = db.relationship('Borrow', backref='reader', lazy='dynamic',
                              foreign_keys='Borrow.reader_id')
    reservations = db.relationship('Reservation', backref='reader', lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @property
    def is_admin(self):
        return self.role == 'admin'
    
    @property
    def is_reader(self):
        return self.role == 'reader'
    
    @property
    def active_borrows_count(self):
        return self.borrows.filter_by(status='active').count()
    
    def can_borrow(self):
        if self.active_borrows_count >= current_app.config['MAX_CONCURRENT_BORROWS']:
            return False
        return True
    
    def __repr__(self):
        return f'<User {self.username}>'


class Book(db.Model):
    __tablename__ = 'books'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    author = db.Column(db.String(100), nullable=False, index=True)
    isbn = db.Column(db.String(20), unique=True, nullable=False)
    description = db.Column(db.Text)
    cover_image = db.Column(db.String(200))
    content_path = db.Column(db.String(200))
    content_hash = db.Column(db.String(64))
    encryption_key = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    licenses = db.relationship('License', backref='book', lazy='dynamic')
    borrows = db.relationship('Borrow', backref='book', lazy='dynamic')
    reservations = db.relationship('Reservation', backref='book', lazy='dynamic')
    
    @property
    def available_copies(self):
        return sum(l.available_copies for l in self.licenses.all())
    
    @property
    def total_licensed_copies(self):
        return sum(l.concurrent_copies for l in self.licenses.all())
    
    @property
    def active_borrows(self):
        return self.borrows.filter_by(status='active').count()
    
    @property
    def pending_reservations_count(self):
        return self.reservations.filter_by(status='pending').count()
    
    def generate_encryption_key(self):
        from app.drm import generate_book_key
        self.encryption_key = generate_book_key(self.id)
    
    def __repr__(self):
        return f'<Book {self.title}>'


class License(db.Model):
    __tablename__ = 'licenses'
    
    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    concurrent_copies = db.Column(db.Integer, nullable=False, default=1)
    borrow_period_days = db.Column(db.Integer, nullable=False, default=14)
    purchased_date = db.Column(db.DateTime, default=datetime.utcnow)
    expiry_date = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    total_borrows = db.Column(db.Integer, default=0)
    
    borrows = db.relationship('Borrow', backref='license', lazy='dynamic')
    
    @property
    def available_copies(self):
        if not self.is_active:
            return 0
        if self.expiry_date and self.expiry_date < datetime.utcnow():
            return 0
        active_borrows = self.borrows.filter_by(status='active').count()
        return max(0, self.concurrent_copies - active_borrows)
    
    @property
    def utilization_rate(self):
        if self.concurrent_copies == 0:
            return 0
        active = self.borrows.filter_by(status='active').count()
        return (active / self.concurrent_copies) * 100
    
    def __repr__(self):
        return f'<License Book:{self.book_id} Copies:{self.concurrent_copies}>'


class Borrow(db.Model):
    __tablename__ = 'borrows'
    
    id = db.Column(db.Integer, primary_key=True)
    reader_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    license_id = db.Column(db.Integer, db.ForeignKey('licenses.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='active')
    borrow_date = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=False)
    return_date = db.Column(db.DateTime)
    drm_token = db.Column(db.String(128))
    last_access_time = db.Column(db.DateTime)
    access_count = db.Column(db.Integer, default=0)
    
    @property
    def is_overdue(self):
        if self.status != 'active':
            return False
        return datetime.utcnow() > self.due_date
    
    @property
    def remaining_days(self):
        if self.status != 'active':
            return 0
        delta = self.due_date - datetime.utcnow()
        return max(0, delta.days + 1)
    
    @property
    def can_access(self):
        if self.status != 'active':
            return False
        if datetime.utcnow() > self.due_date:
            return False
        return True
    
    def set_due_date(self, days=None):
        if days is None:
            license = License.query.get(self.license_id)
            days = license.borrow_period_days if license else 14
        self.due_date = datetime.utcnow() + timedelta(days=days)
    
    def return_book(self):
        self.status = 'returned'
        self.return_date = datetime.utcnow()
    
    def mark_overdue(self):
        self.status = 'overdue'
    
    def record_access(self):
        self.last_access_time = datetime.utcnow()
        self.access_count += 1
    
    def __repr__(self):
        return f'<Borrow User:{self.reader_id} Book:{self.book_id} Status:{self.status}>'


class Reservation(db.Model):
    __tablename__ = 'reservations'
    
    id = db.Column(db.Integer, primary_key=True)
    reader_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    queue_position = db.Column(db.Integer, nullable=False, default=1)
    reservation_date = db.Column(db.DateTime, default=datetime.utcnow)
    available_date = db.Column(db.DateTime)
    expiry_date = db.Column(db.DateTime)
    notified = db.Column(db.Boolean, default=False)
    
    @property
    def is_expired(self):
        if self.status != 'available':
            return False
        if self.expiry_date and datetime.utcnow() > self.expiry_date:
            return True
        return False
    
    def mark_available(self, expire_hours=None):
        if expire_hours is None:
            from flask import current_app
            expire_hours = current_app.config['RESERVATION_EXPIRE_HOURS']
        self.status = 'available'
        self.available_date = datetime.utcnow()
        self.expiry_date = datetime.utcnow() + timedelta(hours=expire_hours)
    
    def mark_fulfilled(self):
        self.status = 'fulfilled'
    
    def mark_expired(self):
        self.status = 'expired'
    
    def cancel(self):
        self.status = 'cancelled'
    
    def __repr__(self):
        return f'<Reservation User:{self.reader_id} Book:{self.book_id} Pos:{self.queue_position}>'


class DRMLog(db.Model):
    __tablename__ = 'drm_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    borrow_id = db.Column(db.Integer, db.ForeignKey('borrows.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    success = db.Column(db.Boolean, default=True)
    details = db.Column(db.Text)
    
    borrow = db.relationship('Borrow', backref='drm_logs')
    
    def __repr__(self):
        return f'<DRMLog Borrow:{self.borrow_id} Action:{self.action}>'
