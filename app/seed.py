import os
from datetime import datetime, timedelta
from app import db
from app.models import User, Book, License
from app.drm import encrypt_content


books_data = [
    {
        'title': '三体',
        'author': '刘慈欣',
        'isbn': '9787536692930',
        'description': '文化大革命如火如荼进行的同时，军方探寻外星文明的绝秘计划"红岸工程"取得了突破性进展。',
        'concurrent_copies': 3,
        'borrow_days': 14,
    },
    {
        'title': '人类简史',
        'author': '尤瓦尔·赫拉利',
        'isbn': '9787508647357',
        'description': '从十万年前有生命迹象开始到21世纪资本、科技交织的人类发展史。',
        'concurrent_copies': 2,
        'borrow_days': 14,
    },
    {
        'title': '活着',
        'author': '余华',
        'isbn': '9787506365437',
        'description': '讲述了农村人福贵悲惨的人生遭遇。',
        'concurrent_copies': 1,
        'borrow_days': 7,
    },
    {
        'title': '百年孤独',
        'author': '加西亚·马尔克斯',
        'isbn': '9787544253994',
        'description': '魔幻现实主义文学的代表作，描写了布恩迪亚家族七代人的传奇故事。',
        'concurrent_copies': 2,
        'borrow_days': 21,
    },
    {
        'title': '小王子',
        'author': '圣埃克苏佩里',
        'isbn': '9787020042494',
        'description': '一个来自B-612星球的小王子的星际旅行故事。',
        'concurrent_copies': 5,
        'borrow_days': 7,
    },
]


def create_sample_book_content(title):
    content = f"""
{title}

{'=' * 50}

这是《{title}》的电子版内容。

本书受DRM版权保护，仅供借阅者在有效期内阅读。
未经授权的复制、传播或分享均属于违法行为。

第一章

    这是第一章的内容。书中讲述了一个引人入胜的故事，
    让读者沉浸在作者创造的世界中。每一个角色都栩栩如生，
    每一个情节都扣人心弦。

第二章

    故事在第二章继续发展。主人公面临着新的挑战和抉择，
    他的命运将何去何从？一切都还是未知数。

第三章

    随着剧情的深入，真相逐渐浮出水面。原来一切都不是
    表面看起来的那样。隐藏在背后的秘密，将彻底改变
    所有人的命运。

...

{'=' * 50}

【版权声明】
本书由数字图书馆授权借阅
所有内容受版权法和DRM技术保护
借阅期限到期后自动失效
禁止复制、传播、转售
违者将承担法律责任

借阅编号: DRM-{abs(hash(title + str(datetime.now())))} % 1000000
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    return content


def seed_database():
    if User.query.count() > 0:
        return
    
    admin = User(
        username='admin',
        email='admin@library.com',
        role='admin'
    )
    admin.set_password('admin123')
    db.session.add(admin)
    
    readers = []
    for i in range(1, 6):
        reader = User(
            username=f'reader{i}',
            email=f'reader{i}@example.com',
            role='reader'
        )
        reader.set_password(f'pass{i}23')
        readers.append(reader)
        db.session.add(reader)
    
    db.session.flush()
    
    from flask import current_app
    books_dir = current_app.config['BOOKS_DIR']
    encrypted_dir = current_app.config['ENCRYPTED_BOOKS_DIR']
    
    for idx, book_info in enumerate(books_data):
        book = Book(
            title=book_info['title'],
            author=book_info['author'],
            isbn=book_info['isbn'],
            description=book_info['description'],
        )
        book.generate_encryption_key()
        db.session.add(book)
        db.session.flush()
        
        content = create_sample_book_content(book_info['title'])
        content_path = os.path.join(books_dir, f"{book.id}.txt")
        with open(content_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        import hashlib
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        book.content_hash = content_hash
        
        encrypted = encrypt_content(content, book.encryption_key)
        encrypted_path = os.path.join(encrypted_dir, f"{book.id}.enc")
        with open(encrypted_path, 'wb') as f:
            f.write(encrypted)
        
        book.content_path = encrypted_path
        
        license = License(
            book_id=book.id,
            concurrent_copies=book_info['concurrent_copies'],
            borrow_period_days=book_info['borrow_days'],
            purchased_date=datetime.utcnow() - timedelta(days=30),
        )
        db.session.add(license)
    
    db.session.commit()
