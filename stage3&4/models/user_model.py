import sqlite3
import hashlib

def get_db_connection():
    conn = sqlite3.connect('database.db') # Hoặc cấu hình kết nối từ models/db.py
    conn.row_factory = sqlite3.Row
    return conn

class UserModel:
    @staticmethod
    def find_by_username(username):
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM Users WHERE Username = ?', (username,)).fetchone()
        conn.close()
        return user

    @staticmethod
    def increment_failed_login(user_id, current_fails):
        new_fails = current_fails + 1
        conn = get_db_connection()
        if new_fails >= 5:
            conn.execute("UPDATE Users SET FailedLoginCount = ?, Status = 'Locked' WHERE Id = ?", (new_fails, user_id))
        else:
            conn.execute("UPDATE Users SET FailedLoginCount = ? WHERE Id = ?", (new_fails, user_id))
        conn.commit()
        conn.close()

    @staticmethod
    def reset_failed_login(user_id):
        conn = get_db_connection()
        conn.execute("UPDATE Users SET FailedLoginCount = 0 WHERE Id = ?", (user_id,))
        conn.commit()
        conn.close()

    @staticmethod
    def update_password(user_id, new_password_hash):
        conn = get_db_connection()
        conn.execute("UPDATE Users SET PasswordHash = ? WHERE Id = ?", (new_password_hash, user_id))
        conn.commit()
        conn.close()

    @staticmethod
    def verify_password(stored_password, provided_password):
        hashed_provided = hashlib.sha256(provided_password.encode()).hexdigest()
        return stored_password == hashed_provided