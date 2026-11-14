"""
models/user_model.py
====================
Tang truy cap CSDL cho nguoi dung he thong (Users), ho tro xac thuc
dang nhap, khoa tai khoan khi sai qua 5 lan, va doi mat khau.
Ket noi Microsoft SQL Server qua Database (models/db.py).
"""

from werkzeug.security import check_password_hash, generate_password_hash
from models.db import Database


class UserModel:
    @staticmethod
    def find_by_username(username):
        """
        Tim nguoi dung theo Username hoac UserCode (Student ID / Lecturer ID / Admin ID).
        Khong phan biet hoa thuong.
        """
        if not username:
            return None
        term = str(username).strip()
        sql = """
            SELECT * FROM dbo.Users
            WHERE LOWER(Username) = LOWER(?) OR UPPER(UserCode) = UPPER(?)
        """
        return Database.query_one(sql, (term, term))

    @staticmethod
    def find_by_id(user_id):
        """Tim nguoi dung theo ID khoa chinh."""
        if not user_id:
            return None
        sql = "SELECT * FROM dbo.Users WHERE Id = ?"
        return Database.query_one(sql, (user_id,))

    @staticmethod
    def increment_failed_login(user_id, current_fails):
        """Tang so lan dang nhap sai; khoa tai khoan (Status='Locked') neu dat >= 5 lan."""
        new_fails = (current_fails or 0) + 1
        if new_fails >= 5:
            sql = "UPDATE dbo.Users SET FailedLoginCount = ?, Status = 'Locked', UpdatedAt = SYSDATETIME() WHERE Id = ?"
        else:
            sql = "UPDATE dbo.Users SET FailedLoginCount = ?, UpdatedAt = SYSDATETIME() WHERE Id = ?"
        return Database.execute(sql, (new_fails, user_id))

    @staticmethod
    def reset_failed_login(user_id):
        """Reset so lan nhap sai ve 0 khi dang nhap thanh cong."""
        sql = "UPDATE dbo.Users SET FailedLoginCount = 0, UpdatedAt = SYSDATETIME() WHERE Id = ?"
        return Database.execute(sql, (user_id,))

    @staticmethod
    def update_password(user_id, new_password):
        """Cap nhat mat khau moi (tu dong bam bang werkzeug scrypt/pbkdf2 neu la plain text)."""
        if not str(new_password).startswith(('scrypt:', 'pbkdf2:')):
            pw_hash = generate_password_hash(new_password)
        else:
            pw_hash = new_password
        sql = "UPDATE dbo.Users SET PasswordHash = ?, FailedLoginCount = 0, UpdatedAt = SYSDATETIME() WHERE Id = ?"
        return Database.execute(sql, (pw_hash, user_id))

    @staticmethod
    def verify_password(stored_password, provided_password):
        """
        Kiem tra mat khau hop le.
        Ho tro chuoi bam Werkzeug (scrypt/pbkdf2), SHA-256 va plain-text fallback.
        """
        if not stored_password or not provided_password:
            return False

        # 1. Kiem tra theo chuan Werkzeug (scrypt / pbkdf2)
        try:
            if check_password_hash(stored_password, provided_password):
                return True
        except Exception:
            pass

        # 2. Kiem tra chuoi plain text
        if stored_password == provided_password:
            return True

        # 3. Kiem tra SHA-256 fallback
        try:
            import hashlib
            if stored_password == hashlib.sha256(provided_password.encode('utf-8')).hexdigest():
                return True
        except Exception:
            pass

        return False
