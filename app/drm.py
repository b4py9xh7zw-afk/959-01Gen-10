import os
import hashlib
import base64
import secrets
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import current_app, request
from app import db
from app.models import Borrow, DRMLog, Book


def _get_fernet_key():
    key = current_app.config['DRM_ENCRYPTION_KEY']
    if isinstance(key, str):
        key = key.encode('utf-8')
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'library-drm-salt',
        iterations=100000,
    )
    derived = kdf.derive(key)
    return base64.urlsafe_b64encode(derived)


def _get_fernet():
    return Fernet(_get_fernet_key())


def generate_book_key(book_id):
    return secrets.token_hex(16)


def encrypt_content(content, book_key):
    fernet = _get_fernet()
    combined = f"{book_key}|{content}".encode('utf-8')
    return fernet.encrypt(combined)


def decrypt_content(encrypted_data, book_key):
    try:
        fernet = _get_fernet()
        decrypted = fernet.decrypt(encrypted_data).decode('utf-8')
        stored_key, content = decrypted.split('|', 1)
        if stored_key != book_key:
            raise ValueError("Invalid book decryption key")
        return content
    except Exception as e:
        raise ValueError(f"Decryption failed: {str(e)}")


def encrypt_book_file(book_id, input_path, output_path=None):
    book = Book.query.get(book_id)
    if not book:
        raise ValueError("Book not found")
    
    if not book.encryption_key:
        book.encryption_key = generate_book_key(book_id)
        db.session.commit()
    
    with open(input_path, 'rb') as f:
        content = f.read()
    
    content_hash = hashlib.sha256(content).hexdigest()
    book.content_hash = content_hash
    
    encrypted = encrypt_content(content.decode('utf-8', errors='replace'), book.encryption_key)
    
    if output_path is None:
        output_path = os.path.join(
            current_app.config['ENCRYPTED_BOOKS_DIR'],
            f"{book_id}.enc"
        )
    
    with open(output_path, 'wb') as f:
        f.write(encrypted)
    
    book.content_path = output_path
    db.session.commit()
    
    return output_path


def generate_drm_token(borrow_id):
    s = URLSafeTimedSerializer(
        current_app.config['SECRET_KEY'],
        salt='drm-token'
    )
    return s.dumps({'borrow_id': borrow_id})


def verify_drm_token(token, max_age=None):
    if max_age is None:
        max_age = 3600
    
    s = URLSafeTimedSerializer(
        current_app.config['SECRET_KEY'],
        salt='drm-token'
    )
    try:
        data = s.loads(token, max_age=max_age)
        return data.get('borrow_id')
    except (BadSignature, SignatureExpired):
        return None


def get_secure_book_content(borrow):
    if not borrow.can_access:
        log_drm_action(borrow.id, 'access_denied_expired', success=False)
        raise PermissionError("Borrow period has expired")
    
    book = borrow.book
    if not book.content_path or not os.path.exists(book.content_path):
        raise FileNotFoundError("Book content not available")
    
    with open(book.content_path, 'rb') as f:
        encrypted = f.read()
    
    try:
        content = decrypt_content(encrypted, book.encryption_key)
        borrow.record_access()
        db.session.commit()
        log_drm_action(borrow.id, 'content_accessed', success=True)
        return content
    except Exception as e:
        log_drm_action(borrow.id, 'decryption_failed', success=False, details=str(e))
        raise PermissionError("Unable to access book content")


def log_drm_action(borrow_id, action, success=True, details=None):
    log = DRMLog(
        borrow_id=borrow_id,
        action=action,
        ip_address=request.remote_addr if request else None,
        user_agent=request.user_agent.string if request else None,
        success=success,
        details=details
    )
    db.session.add(log)
    db.session.commit()
    return log


def validate_read_permission(borrow_id, user_id):
    borrow = Borrow.query.get(borrow_id)
    if not borrow:
        return False, "Borrow record not found"
    
    if borrow.reader_id != user_id:
        return False, "This book is not borrowed by you"
    
    if not borrow.can_access:
        if borrow.is_overdue:
            return False, "Borrow period has expired"
        return False, "Book is not available for reading"
    
    return True, borrow


def create_drm_watermark(content, user_id, borrow_id):
    watermark = f"\n\n--- DRM Protected ---\n"
    watermark += f"Reader ID: {hashlib.sha256(str(user_id).encode()).hexdigest()[:16]}\n"
    watermark += f"Borrow ID: {hashlib.sha256(str(borrow_id).encode()).hexdigest()[:16]}\n"
    watermark += f"Access Time: {datetime.utcnow().isoformat()}\n"
    watermark += "Unauthorized distribution is prohibited.\n"
    return content + watermark


def check_content_integrity(book):
    if not book.content_path or not os.path.exists(book.content_path):
        return False
    
    if not book.content_hash:
        return False
    
    with open(book.content_path, 'rb') as f:
        encrypted = f.read()
    
    try:
        content = decrypt_content(encrypted, book.encryption_key)
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        return content_hash == book.content_hash
    except:
        return False


def revoke_borrow_access(borrow_id):
    borrow = Borrow.query.get(borrow_id)
    if borrow and borrow.status == 'active':
        borrow.return_book()
        db.session.commit()
        log_drm_action(borrow_id, 'access_revoked', success=True)
        return True
    return False
