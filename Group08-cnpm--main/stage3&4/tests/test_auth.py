"""
tests/test_auth.py
==================
Unit tests cho UserModel và AuthController (xac thuc, mat khau, tu dong mo khoa, placeholder hash).
"""

import unittest
from werkzeug.security import generate_password_hash
from models.user_model import UserModel

class TestUserModelPassword(unittest.TestCase):
    def test_verify_password_with_scrypt_hash(self):
        pw_hash = generate_password_hash('123456')
        self.assertTrue(UserModel.verify_password(pw_hash, '123456'))
        self.assertFalse(UserModel.verify_password(pw_hash, 'wrongpass'))

    def test_verify_password_with_placeholder_seed_hash(self):
        # Hash placeholder loi N'scrypt:32768:8:1' trong seed cu cua init_database.sql
        placeholder = 'scrypt:32768:8:1'
        self.assertTrue(UserModel.verify_password(placeholder, '123456'))
        self.assertFalse(UserModel.verify_password(placeholder, 'wrongpass'))

    def test_verify_password_with_plaintext(self):
        self.assertTrue(UserModel.verify_password('123456', '123456'))
        self.assertFalse(UserModel.verify_password('123456', 'wrongpass'))

    def test_verify_password_empty(self):
        self.assertFalse(UserModel.verify_password('', '123456'))
        self.assertFalse(UserModel.verify_password(None, '123456'))
        self.assertFalse(UserModel.verify_password('scrypt:32768:8:1', ''))
        self.assertFalse(UserModel.verify_password('scrypt:32768:8:1', None))

if __name__ == '__main__':
    unittest.main()
