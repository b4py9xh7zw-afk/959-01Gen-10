from app import create_app, db
from app.seed import seed_database
import os

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not os.path.exists(app.config['BOOKS_DIR']):
            os.makedirs(app.config['BOOKS_DIR'])
        if not os.path.exists(app.config['ENCRYPTED_BOOKS_DIR']):
            os.makedirs(app.config['ENCRYPTED_BOOKS_DIR'])
        seed_database()
    app.run(debug=True, host='0.0.0.0', port=5001)
