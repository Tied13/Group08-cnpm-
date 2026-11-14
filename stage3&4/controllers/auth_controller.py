from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g
from models.user_model import UserModel

auth_bp = Blueprint('auth', __name__)

# --- RBAC MIDDLEWARE: Chặn chéo quyền Admin / GV / SV ---
@auth_bp.before_app_request
def rbac_middleware():
    path = request.path
    
    # Cho phép các route công khai truy cập tự do
    public_paths = ['/login', '/logout', '/static']
    if any(path.startswith(p) for p in public_paths) or path == '/':
        return

    # Kiểm tra xem người dùng đã đăng nhập chưa
    if 'user_id' not in session:
        flash('Please log in to continue.', 'warning')
        return redirect(url_for('auth.login'))

    role = session.get('role')  # 'Admin', 'Lecturer', 'Student'

    # Chặn sinh viên hoặc giảng viên cố tình truy cập đường dẫn của Admin
    if path.startswith('/admin') and role != 'Admin':
        flash('Access denied: You do not have permission to access Admin Portal.', 'danger')
        return redirect(url_for('auth.dashboard'))

    # Chặn sinh viên truy cập đường dẫn của Giảng viên
    if path.startswith('/lecturer') and role not in ['Admin', 'Lecturer']:
        flash('Access denied: You do not have permission to access Lecturer Portal.', 'danger')
        return redirect(url_for('auth.dashboard'))


# --- CONTROLLERS ---

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Nếu đã đăng nhập thì chuyển hướng ngay về đúng phân hệ
    if request.method == 'GET' and 'user_id' in session and session.get('role'):
        return redirect(url_for('auth.dashboard'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '').strip()

        if not username or not password:
            flash('Please enter both User ID / Username and Password.', 'warning')
            return render_template('login.html')

        user = UserModel.find_by_username(username)

        if not user:
            flash('Invalid Username or User ID.', 'danger')
            return render_template('login.html')

        # Kiểm tra tài khoản đã bị khóa chưa
        if user['Status'] == 'Locked':
            flash('Your account has been locked due to exceeding 5 failed login attempts. Please contact Administrator.', 'danger')
            return render_template('login.html')

        # So khớp mật khẩu
        if UserModel.verify_password(user['PasswordHash'], password):
            # Đăng nhập đúng: Reset số lần sai và lưu session
            UserModel.reset_failed_login(user['Id'])
            session['user_id'] = user['Id']
            session['username'] = user['Username']
            session['user_code'] = user['UserCode']
            session['full_name'] = user['FullName']
            session['role'] = user['Role']  # 'Admin', 'Student', 'Lecturer'
            
            # Chuyển hướng trực tiếp vào phân hệ phù hợp
            if user['Role'] == 'Admin':
                return redirect(url_for('admin_bp.admin_home'))
            elif user['Role'] == 'Lecturer':
                return redirect(url_for('lecturer_bp.lecturer_home'))
            elif user['Role'] == 'Student':
                return redirect(url_for('student_bp.student_home'))
            return redirect(url_for('auth.dashboard'))
        else:
            # Đăng nhập sai: Tăng FailedLoginCount
            UserModel.increment_failed_login(user['Id'], user['FailedLoginCount'])
            remaining = 5 - (user['FailedLoginCount'] + 1)
            
            if remaining <= 0:
                flash('Your account has been locked due to exceeding 5 failed login attempts.', 'danger')
            else:
                flash(f'Incorrect password. You have {remaining} attempt(s) remaining.', 'warning')
            
            return render_template('login.html')

    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


@auth_bp.route('/dashboard')
def dashboard():
    """Điều hướng người dùng về đúng phân hệ theo vai trò (Role-based Routing)."""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    role = session.get('role')
    if role == 'Admin':
        return redirect(url_for('admin_bp.admin_home'))
    elif role == 'Lecturer':
        return redirect(url_for('lecturer_bp.lecturer_home'))
    elif role == 'Student':
        return redirect(url_for('student_bp.student_home'))
    
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    old_password = request.form.get('old_password')
    new_password = request.form.get('new_password')
    
    user = UserModel.find_by_id(session['user_id'])
    if not user or not UserModel.verify_password(user['PasswordHash'], old_password):
        flash('Current password is incorrect.', 'danger')
        return redirect(url_for('auth.dashboard'))
    
    if not new_password or len(new_password) < 6:
        flash('New password must be at least 6 characters.', 'danger')
        return redirect(url_for('auth.dashboard'))

    UserModel.update_password(user['Id'], new_password)
    flash('Password updated successfully!', 'success')
    return redirect(url_for('auth.dashboard'))
