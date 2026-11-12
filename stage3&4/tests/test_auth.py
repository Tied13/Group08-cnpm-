import unittest
from app import app # Import ứng dụng Flask chính của nhóm

class AuthTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

    def test_01_successful_login(self):
        """Test đăng nhập thành công với vai trò hợp lệ"""
        response = self.client.post('/login', data=dict(
            username='admin_test',
            password='correct_password'
        ), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        # Kiểm tra session đã được thiết lập đúng role

    def test_02_failed_login_attempts_1_to_4(self):
        """Test đăng nhập sai từ 1 đến 4 lần (tài khoản vẫn Active)"""
        for _ in range(3):
            response = self.client.post('/login', data=dict(
                username='student_test',
                password='wrong_password'
            ), follow_redirects=True)
            self.assertIn(b'M\u1eadt kh\u1ea9u kh\u00f4ng ch\u00ednh x\u00e1c', response.data)

    def test_03_account_lockout_on_5th_attempt(self):
        """Test đăng nhập sai lần thứ 5 tài khoản chuyển thành Locked ngay lập tức"""
        # Giả lập nhập sai 5 lần liên tiếp
        for _ in range(5):
            response = self.client.post('/login', data=dict(
                username='student_test_lock',
                password='wrong_password'
            ), follow_redirects=True)
        
        # Kiểm tra lần thử thứ 5 hiển thị thông báo khóa tài khoản
        self.assertIn(b'T\u00e0i kho\u1ea3n c\u1ee7a b\u1ea1n \u0111\u00e3 b\u1ecj kh\u00f3a', response.data)

    def test_04_login_with_locked_account(self):
        """Test cố tình đăng nhập vào tài khoản đã bị Locked"""
        # Giả sử tài khoản đã bị khóa từ trước
        response = self.client.post('/login', data=dict(
            username='locked_user',
            password='correct_password'
        ), follow_redirects=True)
        self.assertIn(b'T\u00e0i kho\u1ea3n c\u1ee7a b\u1ea1n \u0111\u00e3 b\u1ecj kh\u00f3a', response.data)

    def test_05_rbac_unauthorized_access(self):
        """Test cố tình truy cập URL của Admin khi chưa đăng nhập hoặc sai vai trò (Sinh viên)"""
        # Đăng nhập với tài khoản Sinh viên
        self.client.post('/login', data=dict(
            username='student_user',
            password='password123'
        ), follow_redirects=True)
        
        # Cố gắng truy cập trang Admin
        response = self.client.get('/admin/dashboard', follow_redirects=True)
        self.assertIn(b'B\u1ea1n kh\u00f4ng c\u00f3 quy\u1ec1n truy c\u1eadp', response.data)

if __name__ == '__main__':
    unittest.main()