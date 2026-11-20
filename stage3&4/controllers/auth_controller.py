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

    # Kiểm tra xem tài khoản có bị khóa không
    try:
        current_user = UserModel.find_by_id(session['user_id'])
        if current_user and current_user.get('Status') == 'Locked':
            session.clear()
            flash('Your account has been locked. Please contact the administrator.', 'danger')
            return redirect(url_for('auth.login'))
    except Exception:
        pass

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

        try:
            user = UserModel.find_by_username(username)
        except Exception as db_err:
            flash(
                "Database connection error: Could not connect to SQL Server or 'CourseRegistrationDB' not found. "
                f"Please ensure SQL Server is running and run 'init_database.sql' in SSMS first. (Details: {db_err})",
                'danger',
            )
            return render_template('login.html')

        if not user:
            flash(f"Account '{username}' not found in the system! Please try sample accounts: admin, admin_daotao, gv_nam, sv_nam, sv_an", 'danger')
            return render_template('login.html')

        # Kiểm tra xem tài khoản có bị khóa không
        if user.get('Status') == 'Locked':
            flash(f"Account '{username}' is locked. Please contact the administrator for assistance.", 'danger')
            return render_template('login.html')

        # So khớp mật khẩu
        if UserModel.verify_password(user.get('PasswordHash'), password):
            # Đăng nhập đúng: Reset số lần sai và lưu session
            try:
                UserModel.reset_failed_login(user['Id'])
            except Exception:
                pass

            session['user_id'] = user['Id']
            session['username'] = user['Username']
            session['user_code'] = user.get('UserCode', '')
            session['full_name'] = user.get('FullName', user['Username'])
            session['role'] = str(user.get('Role') or 'Admin').strip()

            # Chuyển hướng trực tiếp vào phân hệ phù hợp
            if session['role'] == 'Admin':
                return redirect(url_for('admin_bp.admin_home'))
            elif session['role'] == 'Lecturer':
                return redirect(url_for('lecturer_bp.lecturer_home'))
            elif session['role'] == 'Student':
                return redirect(url_for('student_bp.student_home'))
            return redirect(url_for('auth.dashboard'))
        else:
            remaining = 5 - ((user.get('FailedLoginCount') or 0) + 1)
            try:
                UserModel.increment_failed_login(user['Id'], user.get('FailedLoginCount') or 0)
            except Exception:
                pass
            flash(f"Incorrect password for account '{username}'! Default password for all sample accounts is 123456.", 'danger')
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
    
    data = request.get_json(silent=True) or request.form or {}
    old_password = data.get('old_password') or data.get('current_password')
    new_password = data.get('new_password')
    
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
