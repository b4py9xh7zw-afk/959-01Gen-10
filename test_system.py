import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import User, Book, License, Borrow, Reservation, DRMLog
from app.drm import encrypt_content, decrypt_content, generate_book_key, \
    generate_drm_token, verify_drm_token, validate_read_permission, \
    get_secure_book_content, create_drm_watermark, check_content_integrity
from app.services.borrow_service import BorrowService
from app.services.reservation_service import ReservationService
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    BOOKS_DIR = tempfile.mkdtemp()
    ENCRYPTED_BOOKS_DIR = tempfile.mkdtemp()


class DRMTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, seed_db=False)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self._create_test_data()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _create_test_data(self):
        self.admin = User(username='admin', email='admin@test.com', role='admin')
        self.admin.set_password('admin123')

        self.reader1 = User(username='reader1', email='reader1@test.com', role='reader')
        self.reader1.set_password('pass123')

        self.reader2 = User(username='reader2', email='reader2@test.com', role='reader')
        self.reader2.set_password('pass123')

        db.session.add_all([self.admin, self.reader1, self.reader2])
        db.session.flush()

        self.book = Book(
            title='测试书籍',
            author='测试作者',
            isbn='9781234567890',
            description='测试描述'
        )
        self.book.generate_encryption_key()
        db.session.add(self.book)
        db.session.flush()

        self.license = License(
            book_id=self.book.id,
            concurrent_copies=2,
            borrow_period_days=14
        )
        db.session.add(self.license)
        db.session.flush()

        test_content = "这是测试书籍的内容。\n第一章：测试内容。"
        self.test_content = test_content
        content_path = os.path.join(TestConfig.BOOKS_DIR, f"{self.book.id}.txt")
        with open(content_path, 'w', encoding='utf-8') as f:
            f.write(test_content)

        import hashlib
        content_hash = hashlib.sha256(test_content.encode('utf-8')).hexdigest()
        self.book.content_hash = content_hash

        encrypted = encrypt_content(test_content, self.book.encryption_key)
        encrypted_path = os.path.join(TestConfig.ENCRYPTED_BOOKS_DIR, f"{self.book.id}.enc")
        with open(encrypted_path, 'wb') as f:
            f.write(encrypted)
        self.book.content_path = encrypted_path

        db.session.commit()

    def test_01_encryption_decryption(self):
        print("\n=== 测试1: DRM加密解密 ===")
        encrypted = encrypt_content(self.test_content, self.book.encryption_key)
        self.assertIsInstance(encrypted, bytes)
        self.assertNotEqual(encrypted, self.test_content.encode('utf-8'))

        decrypted = decrypt_content(encrypted, self.book.encryption_key)
        self.assertEqual(decrypted, self.test_content)
        print("✓ 加密解密正常工作")

    def test_02_wrong_key_decryption(self):
        print("\n=== 测试2: 错误密钥解密 ===")
        encrypted = encrypt_content(self.test_content, self.book.encryption_key)
        wrong_key = generate_book_key(999)

        with self.assertRaises(ValueError):
            decrypt_content(encrypted, wrong_key)
        print("✓ 错误密钥无法解密")

    def test_03_book_key_generation(self):
        print("\n=== 测试3: 书籍密钥生成 ===")
        key1 = generate_book_key(1)
        key2 = generate_book_key(2)
        self.assertNotEqual(key1, key2)
        self.assertEqual(len(key1), 32)
        print("✓ 每本书生成唯一密钥")

    def test_04_drm_token(self):
        print("\n=== 测试4: DRM令牌 ===")
        token = generate_drm_token(1)
        self.assertIsInstance(token, str)

        borrow_id = verify_drm_token(token)
        self.assertEqual(borrow_id, 1)
        print("✓ DRM令牌生成和验证正常")

    def test_05_drm_token_expired(self):
        print("\n=== 测试5: DRM令牌过期 ===")
        token = generate_drm_token(1)
        import time
        time.sleep(2)
        borrow_id = verify_drm_token(token, max_age=1)
        self.assertIsNone(borrow_id)
        print("✓ 过期令牌验证失败")

    def test_06_content_integrity(self):
        print("\n=== 测试6: 内容完整性校验 ===")
        is_valid = check_content_integrity(self.book)
        self.assertTrue(is_valid)
        print("✓ 内容完整性校验通过")

    def test_07_watermark_creation(self):
        print("\n=== 测试7: DRM水印 ===")
        watermarked = create_drm_watermark(self.test_content, 1, 1)
        self.assertIn('DRM Protected', watermarked)
        self.assertIn('Unauthorized distribution', watermarked)
        print("✓ DRM水印添加成功")

    def test_08_borrow_book(self):
        print("\n=== 测试8: 借阅书籍 ===")
        borrow, message = BorrowService.borrow_book(self.reader1.id, self.book.id)
        self.assertIsNotNone(borrow)
        self.assertEqual(borrow.reader_id, self.reader1.id)
        self.assertEqual(borrow.book_id, self.book.id)
        self.assertEqual(borrow.status, 'active')
        self.assertIsNotNone(borrow.drm_token)
        print(f"✓ 借阅成功: {message}")

    def test_09_duplicate_borrow(self):
        print("\n=== 测试9: 重复借阅检查 ===")
        BorrowService.borrow_book(self.reader1.id, self.book.id)

        borrow, message = BorrowService.borrow_book(self.reader1.id, self.book.id)
        self.assertIsNone(borrow)
        self.assertIn('already have this book borrowed', message)
        print(f"✓ 重复借阅被拒绝: {message}")

    def test_10_concurrent_limit(self):
        print("\n=== 测试10: 并发借阅限制 ===")
        BorrowService.borrow_book(self.reader1.id, self.book.id)
        BorrowService.borrow_book(self.reader2.id, self.book.id)

        reader3 = User(username='reader3', email='reader3@test.com', role='reader')
        reader3.set_password('pass123')
        db.session.add(reader3)
        db.session.commit()

        borrow, message = BorrowService.borrow_book(reader3.id, self.book.id)
        self.assertIsNone(borrow)
        self.assertIn('No copies available', message)
        print(f"✓ 并发限制生效: {message}")

    def test_11_return_book(self):
        print("\n=== 测试11: 归还书籍 ===")
        borrow, _ = BorrowService.borrow_book(self.reader1.id, self.book.id)
        self.assertEqual(borrow.status, 'active')

        success, message = BorrowService.return_book(borrow.id, self.reader1.id)
        self.assertTrue(success)
        self.assertEqual(borrow.status, 'returned')
        self.assertIsNotNone(borrow.return_date)
        print(f"✓ 归还成功: {message}")

    def test_12_read_permission(self):
        print("\n=== 测试12: 阅读权限验证 ===")
        borrow, _ = BorrowService.borrow_book(self.reader1.id, self.book.id)

        is_valid, result = validate_read_permission(borrow.id, self.reader1.id)
        self.assertTrue(is_valid)
        self.assertEqual(result.id, borrow.id)
        print("✓ 有效借阅者可以访问")

        is_valid, message = validate_read_permission(borrow.id, self.reader2.id)
        self.assertFalse(is_valid)
        self.assertIn('not borrowed by you', message)
        print("✓ 非借阅者被拒绝访问")

    def test_13_expired_access(self):
        print("\n=== 测试13: 过期借阅访问 ===")
        borrow, _ = BorrowService.borrow_book(self.reader1.id, self.book.id)
        borrow.due_date = datetime.utcnow() - timedelta(days=1)
        db.session.commit()

        is_valid, message = validate_read_permission(borrow.id, self.reader1.id)
        self.assertFalse(is_valid)
        self.assertIn('expired', message)
        print(f"✓ 过期借阅被拒绝: {message}")

    def test_14_secure_content_access(self):
        print("\n=== 测试14: 安全内容访问 ===")
        borrow, _ = BorrowService.borrow_book(self.reader1.id, self.book.id)

        content = get_secure_book_content(borrow)
        self.assertIn('测试书籍', content)
        self.assertEqual(borrow.access_count, 1)
        self.assertIsNotNone(borrow.last_access_time)
        print("✓ 安全内容访问成功，访问记录已更新")

    def test_15_reservation_system(self):
        print("\n=== 测试15: 预约系统 ===")
        BorrowService.borrow_book(self.reader1.id, self.book.id)
        BorrowService.borrow_book(self.reader2.id, self.book.id)

        reader3 = User(username='reader3', email='reader3@test.com', role='reader')
        reader3.set_password('pass123')
        db.session.add(reader3)
        db.session.commit()

        reservation, message = ReservationService.reserve_book(reader3.id, self.book.id)
        self.assertIsNotNone(reservation)
        self.assertEqual(reservation.queue_position, 1)
        self.assertEqual(reservation.status, 'pending')
        print(f"✓ 预约成功: {message}, 队列位置: {reservation.queue_position}")

    def test_16_reservation_queue_order(self):
        print("\n=== 测试16: 预约队列顺序 ===")
        BorrowService.borrow_book(self.reader1.id, self.book.id)
        BorrowService.borrow_book(self.reader2.id, self.book.id)

        for i in range(3, 6):
            reader = User(username=f'reader{i}', email=f'reader{i}@test.com', role='reader')
            reader.set_password('pass123')
            db.session.add(reader)
            db.session.commit()

            reservation, _ = ReservationService.reserve_book(reader.id, self.book.id)
            self.assertEqual(reservation.queue_position, i - 2)
            print(f"  ✓ reader{i} 预约位置: {reservation.queue_position}")

        print("✓ 预约队列顺序正确")

    def test_17_process_available_book(self):
        print("\n=== 测试17: 归还后通知预约 ===")
        borrow1, _ = BorrowService.borrow_book(self.reader1.id, self.book.id)
        BorrowService.borrow_book(self.reader2.id, self.book.id)

        reader3 = User(username='reader3', email='reader3@test.com', role='reader')
        reader3.set_password('pass123')
        db.session.add(reader3)
        db.session.commit()

        reservation, _ = ReservationService.reserve_book(reader3.id, self.book.id)
        self.assertEqual(reservation.status, 'pending')

        BorrowService.return_book(borrow1.id, self.reader1.id)

        reservation = Reservation.query.get(reservation.id)
        self.assertEqual(reservation.status, 'available')
        self.assertIsNotNone(reservation.available_date)
        print("✓ 图书归还后自动通知预约读者")

    def test_18_cancel_reservation(self):
        print("\n=== 测试18: 取消预约 ===")
        BorrowService.borrow_book(self.reader1.id, self.book.id)
        BorrowService.borrow_book(self.reader2.id, self.book.id)

        reader3 = User(username='reader3', email='reader3@test.com', role='reader')
        reader3.set_password('pass123')
        reader4 = User(username='reader4', email='reader4@test.com', role='reader')
        reader4.set_password('pass123')
        db.session.add_all([reader3, reader4])
        db.session.commit()

        res3, _ = ReservationService.reserve_book(reader3.id, self.book.id)
        res4, _ = ReservationService.reserve_book(reader4.id, self.book.id)

        self.assertEqual(res3.queue_position, 1)
        self.assertEqual(res4.queue_position, 2)

        success, message = ReservationService.cancel_reservation(res3.id, reader3.id)
        self.assertTrue(success)

        res4 = Reservation.query.get(res4.id)
        self.assertEqual(res4.queue_position, 1)
        print(f"✓ 取消预约后队列位置自动更新: {message}")

    def test_19_max_concurrent_borrows_per_user(self):
        print("\n=== 测试19: 用户最大并发借阅限制 ===")
        for i in range(2, 5):
            book = Book(
                title=f'书籍{i}',
                author=f'作者{i}',
                isbn=f'97812345678{i:02d}',
                description=f'描述{i}'
            )
            book.generate_encryption_key()
            db.session.add(book)
            db.session.flush()

            lic = License(book_id=book.id, concurrent_copies=1, borrow_period_days=14)
            db.session.add(lic)

            content = f"书籍{i}内容"
            encrypted = encrypt_content(content, book.encryption_key)
            encrypted_path = os.path.join(TestConfig.ENCRYPTED_BOOKS_DIR, f"{book.id}.enc")
            with open(encrypted_path, 'wb') as f:
                f.write(encrypted)
            book.content_path = encrypted_path

        db.session.commit()

        for i in range(1, 4):
            book = Book.query.get(i)
            borrow, message = BorrowService.borrow_book(self.reader1.id, book.id)
            self.assertIsNotNone(borrow)
            print(f"  ✓ 借阅第{i}本书成功")

        book4 = Book.query.get(4)
        borrow, message = BorrowService.borrow_book(self.reader1.id, book4.id)
        self.assertIsNone(borrow)
        self.assertIn('Maximum', message)
        print(f"✓ 超过最大借阅限制被拒绝: {message}")

    def test_20_admin_cannot_read_content(self):
        print("\n=== 测试20: 管理员无法访问阅读内容 ===")
        borrow, _ = BorrowService.borrow_book(self.reader1.id, self.book.id)

        is_valid, message = validate_read_permission(borrow.id, self.admin.id)
        self.assertFalse(is_valid)
        self.assertIn('not borrowed by you', message)

        with self.assertRaises(PermissionError):
            borrow.reader_id = self.admin.id
            db.session.commit()
            borrow.due_date = datetime.utcnow() - timedelta(days=1)
            db.session.commit()
            get_secure_book_content(borrow)

        print("✓ 管理员无法访问读者的阅读内容")

    def test_21_process_overdue_books(self):
        print("\n=== 测试21: 自动处理过期借阅 ===")
        borrow, _ = BorrowService.borrow_book(self.reader1.id, self.book.id)
        borrow.due_date = datetime.utcnow() - timedelta(days=1)
        db.session.commit()

        count = BorrowService.process_overdue_books()
        self.assertEqual(count, 1)

        borrow = Borrow.query.get(borrow.id)
        self.assertEqual(borrow.status, 'overdue')
        print(f"✓ 自动处理过期借阅，标记为逾期: {count} 本")

    def test_22_extend_borrow(self):
        print("\n=== 测试22: 续借功能 ===")
        borrow, _ = BorrowService.borrow_book(self.reader1.id, self.book.id)
        original_due = borrow.due_date

        success, message = BorrowService.extend_borrow(borrow.id, self.reader1.id, days=7)
        self.assertTrue(success)
        self.assertGreater(borrow.due_date, original_due)
        print(f"✓ 续借成功: {message}")

    def test_23_drm_logging(self):
        print("\n=== 测试23: DRM访问日志 ===")
        borrow, _ = BorrowService.borrow_book(self.reader1.id, self.book.id)
        get_secure_book_content(borrow)

        logs = DRMLog.query.filter_by(borrow_id=borrow.id).all()
        self.assertGreater(len(logs), 0)

        content_log = [l for l in logs if l.action == 'content_accessed']
        self.assertEqual(len(content_log), 1)
        self.assertTrue(content_log[0].success)
        print(f"✓ DRM日志记录正常，共 {len(logs)} 条记录")

    def test_24_license_utilization_rate(self):
        print("\n=== 测试24: 版权利用率计算 ===")
        test_book = Book(
            title='利用率测试书',
            author='测试作者',
            isbn='9781111111111',
            description='测试'
        )
        test_book.generate_encryption_key()
        db.session.add(test_book)
        db.session.flush()

        test_license = License(
            book_id=test_book.id,
            concurrent_copies=2,
            borrow_period_days=14
        )
        db.session.add(test_license)

        test_content = "测试内容"
        import hashlib
        content_hash = hashlib.sha256(test_content.encode('utf-8')).hexdigest()
        test_book.content_hash = content_hash
        encrypted = encrypt_content(test_content, test_book.encryption_key)
        encrypted_path = os.path.join(TestConfig.ENCRYPTED_BOOKS_DIR, f"{test_book.id}.enc")
        with open(encrypted_path, 'wb') as f:
            f.write(encrypted)
        test_book.content_path = encrypted_path
        db.session.commit()

        license = License.query.get(test_license.id)
        self.assertEqual(license.utilization_rate, 0)
        self.assertEqual(license.available_copies, 2)
        book = Book.query.get(test_book.id)
        self.assertEqual(book.available_copies, 2)

        borrow1, msg1 = BorrowService.borrow_book(self.reader1.id, test_book.id)
        self.assertIsNotNone(borrow1, msg1)
        self.assertEqual(borrow1.license_id, test_license.id)
        db.session.refresh(license)
        self.assertEqual(license.available_copies, 1)
        self.assertEqual(license.utilization_rate, 50)
        db.session.refresh(book)
        self.assertEqual(book.available_copies, 1)

        borrow2, msg2 = BorrowService.borrow_book(self.reader2.id, test_book.id)
        self.assertIsNotNone(borrow2, f"msg={msg2}, available={book.available_copies}")
        self.assertEqual(borrow2.license_id, test_license.id)
        db.session.refresh(license)
        self.assertEqual(license.available_copies, 0)
        self.assertEqual(license.utilization_rate, 100)
        print(f"✓ 版权利用率计算正确: {license.utilization_rate}%")

    def test_25_user_can_borrow_check(self):
        print("\n=== 测试25: 用户借阅资格检查 ===")
        self.assertTrue(self.reader1.can_borrow())

        for i in range(2, 5):
            book = Book(
                title=f'书籍{i}',
                author=f'作者{i}',
                isbn=f'97898765432{i:02d}',
                description=f'描述{i}'
            )
            book.generate_encryption_key()
            db.session.add(book)
            db.session.flush()

            lic = License(book_id=book.id, concurrent_copies=1, borrow_period_days=14)
            db.session.add(lic)

            content = f"书籍{i}内容"
            encrypted = encrypt_content(content, book.encryption_key)
            encrypted_path = os.path.join(TestConfig.ENCRYPTED_BOOKS_DIR, f"{book.id}.enc")
            with open(encrypted_path, 'wb') as f:
                f.write(encrypted)
            book.content_path = encrypted_path

        db.session.commit()

        for i in range(1, 4):
            book = Book.query.get(i)
            BorrowService.borrow_book(self.reader1.id, book.id)

        self.assertFalse(self.reader1.can_borrow())
        print("✓ 用户借阅资格检查正确")

    def test_26_expired_reservations(self):
        print("\n=== 测试26: 过期预约处理 ===")
        BorrowService.borrow_book(self.reader1.id, self.book.id)
        BorrowService.borrow_book(self.reader2.id, self.book.id)

        reader3 = User(username='reader3', email='reader3@test.com', role='reader')
        reader3.set_password('pass123')
        db.session.add(reader3)
        db.session.commit()

        reservation, _ = ReservationService.reserve_book(reader3.id, self.book.id)

        reservation.mark_available(expire_hours=0)
        db.session.commit()

        count = ReservationService.process_expired_reservations()
        self.assertEqual(count, 1)

        reservation = Reservation.query.get(reservation.id)
        self.assertEqual(reservation.status, 'expired')
        print(f"✓ 过期预约处理正常: {count} 个")

    def test_27_api_routes(self):
        print("\n=== 测试27: API接口 ===")
        client = self.app.test_client()

        response = client.get('/api/books')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        print(f"✓ GET /api/books 正常，返回 {len(data)} 本书")

        book_id = data[0]['id']
        response = client.get(f'/api/books/{book_id}')
        self.assertEqual(response.status_code, 200)
        book_data = response.get_json()
        self.assertEqual(book_data['id'], book_id)
        print(f"✓ GET /api/books/<id> 正常")

        client.post('/auth/login', data={
            'username': 'reader1',
            'password': 'pass123'
        })

        response = client.get('/api/reader/borrows')
        self.assertEqual(response.status_code, 200)
        print("✓ GET /api/reader/borrows 正常")

        print("✓ 所有API接口正常")

    def test_28_admin_routes_protected(self):
        print("\n=== 测试28: 管理员路由保护 ===")
        client = self.app.test_client()

        response = client.get('/admin/', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        print("✓ 未登录用户被重定向到登录页")

        client.post('/auth/login', data={
            'username': 'reader1',
            'password': 'pass123'
        })

        response = client.get('/admin/', follow_redirects=False)
        self.assertEqual(response.status_code, 403)
        print("✓ 读者角色无法访问管理员页面")

        client.get('/auth/logout')

        client.post('/auth/login', data={
            'username': 'admin',
            'password': 'admin123'
        })

        response = client.get('/admin/', follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        print("✓ 管理员可以访问管理面板")

    def test_29_overdue_auto_returns_book(self):
        print("\n=== 测试29: 到期自动归还电子书并释放名额 ===")
        test_book = Book.query.first()
        test_license = test_book.licenses.first()
        
        reader1 = User.query.filter_by(username='reader1').first()
        if not reader1:
            reader1 = User(username='reader1', email='reader1@test.com', role='reader')
            reader1.set_password('pass123')
            db.session.add(reader1)
            db.session.commit()
        
        initial_available = test_license.available_copies
        
        borrow, msg = BorrowService.borrow_book(reader1.id, test_book.id)
        self.assertIsNotNone(borrow)
        self.assertEqual(test_license.available_copies, initial_available - 1)
        
        borrow.due_date = datetime.utcnow() - timedelta(days=1)
        db.session.commit()
        
        count = BorrowService.process_overdue_books()
        self.assertEqual(count, 1)
        
        db.session.refresh(borrow)
        self.assertEqual(borrow.status, 'overdue')
        self.assertIsNotNone(borrow.return_date)
        
        db.session.refresh(test_license)
        self.assertEqual(test_license.available_copies, initial_available)
        print(f"✓ 到期自动归还，名额已释放: {initial_available} 个可用")

    def test_30_no_queue_jumping(self):
        print("\n=== 测试30: 热门书预约排队不能被后来者插队 ===")
        test_book = Book.query.first()
        test_license = License.query.filter_by(book_id=test_book.id).first()
        test_license.concurrent_copies = 1
        db.session.commit()
        
        reader1 = User.query.filter_by(username='reader1').first()
        if not reader1:
            reader1 = User(username='reader1', email='reader1@test.com', role='reader')
            reader1.set_password('pass123')
            db.session.add(reader1)
        
        reader2 = User.query.filter_by(username='reader2').first()
        if not reader2:
            reader2 = User(username='reader2', email='reader2@test.com', role='reader')
            reader2.set_password('pass223')
            db.session.add(reader2)
        
        reader3 = User.query.filter_by(username='reader3').first()
        if not reader3:
            reader3 = User(username='reader3', email='reader3@test.com', role='reader')
            reader3.set_password('pass323')
            db.session.add(reader3)
        
        db.session.commit()
        
        borrow1, msg = BorrowService.borrow_book(reader1.id, test_book.id)
        self.assertIsNotNone(borrow1)
        print("✓ reader1 借走唯一副本")
        
        res2, msg = ReservationService.reserve_book(reader2.id, test_book.id)
        self.assertIsNotNone(res2)
        self.assertEqual(res2.queue_position, 1)
        print("✓ reader2 预约，队列位置 1")
        
        res3, msg = ReservationService.reserve_book(reader3.id, test_book.id)
        self.assertIsNotNone(res3)
        self.assertEqual(res3.queue_position, 2)
        print("✓ reader3 预约，队列位置 2")
        
        can_borrow, msg = BorrowService.can_borrow_book(reader3.id, test_book.id)
        self.assertFalse(can_borrow)
        self.assertIn("waiting list", msg)
        print(f"✓ reader3 不能直接借阅（需要排队）: {msg}")
        
        BorrowService.return_book(borrow1.id, reader1.id)
        db.session.refresh(res2)
        self.assertEqual(res2.status, 'available')
        print("✓ reader1 还书后，reader2 收到领取通知（status=available）")
        
        can_borrow, msg = BorrowService.can_borrow_book(reader3.id, test_book.id)
        self.assertFalse(can_borrow)
        self.assertIn("waiting list", msg)
        print(f"✓ reader3 仍然不能直接借阅（reader2 在等待领取）: {msg}")
        
        can_borrow, msg = BorrowService.can_borrow_book(reader2.id, test_book.id)
        self.assertTrue(can_borrow)
        print("✓ reader2 可以领取预约的图书")
        print("✓ 预约排队机制正常，无人能插队")

    def test_31_overdue_notifies_waiting_list(self):
        print("\n=== 测试31: 借阅到期释放名额自动通知排队者 ===")
        test_book = Book.query.first()
        test_license = License.query.filter_by(book_id=test_book.id).first()
        test_license.concurrent_copies = 1
        db.session.commit()
        
        reader1 = User.query.filter_by(username='reader1').first()
        if not reader1:
            reader1 = User(username='reader1', email='reader1@test.com', role='reader')
            reader1.set_password('pass123')
            db.session.add(reader1)
        
        reader2 = User.query.filter_by(username='reader2').first()
        if not reader2:
            reader2 = User(username='reader2', email='reader2@test.com', role='reader')
            reader2.set_password('pass223')
            db.session.add(reader2)
        
        db.session.commit()
        
        borrow1, msg = BorrowService.borrow_book(reader1.id, test_book.id)
        self.assertIsNotNone(borrow1)
        print("✓ reader1 借走唯一副本")
        
        res2, msg = ReservationService.reserve_book(reader2.id, test_book.id)
        self.assertIsNotNone(res2)
        self.assertEqual(res2.status, 'pending')
        print("✓ reader2 预约排队，状态 pending")
        
        borrow1.due_date = datetime.utcnow() - timedelta(days=1)
        db.session.commit()
        
        count = BorrowService.process_overdue_books()
        self.assertEqual(count, 1)
        print(f"✓ 处理了 {count} 本过期图书")
        
        db.session.refresh(res2)
        self.assertEqual(res2.status, 'available')
        self.assertTrue(res2.notified)
        self.assertIsNotNone(res2.available_date)
        print("✓ reader2 自动收到通知，状态变为 available")
        print("✓ 借阅到期释放名额自动通知排队者")


def run_tests():
    print("=" * 70)
    print("电子书DRM借阅系统 - 功能测试套件")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(DRMTestCase)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    if result.wasSuccessful():
        print("✓ 所有测试通过！")
        print(f"  运行测试: {result.testsRun}")
        print(f"  成功: {result.testsRun - len(result.failures) - len(result.errors)}")
        print(f"  失败: {len(result.failures)}")
        print(f"  错误: {len(result.errors)}")
    else:
        print("✗ 部分测试失败")
        if result.failures:
            print("\n失败的测试:")
            for test, traceback in result.failures:
                print(f"  - {test}: {traceback[:100]}...")
        if result.errors:
            print("\n错误的测试:")
            for test, traceback in result.errors:
                print(f"  - {test}: {traceback[:100]}...")
    print("=" * 70)

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
