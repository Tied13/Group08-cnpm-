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
        flash('Vui lòng đăng nhập để tiếp tục.', 'warning')
        return redirect(url_for('auth.login'))

    role = session.get('role') # Ví dụ: 'Admin', 'Lecturer', 'Student'

    # Chặn sinh viên hoặc giảng viên cố tình truy cập đường dẫn của Admin
    if path.startswith('/admin') and role != 'Admin':
        flash('Bạn không có quyền truy cập trang quản trị Admin!', 'danger')
        return redirect(url_for('auth.dashboard'))

    # Chặn sinh viên truy cập đường dẫn của Giảng viên
    if path.startswith('/lecturer') and role not in ['Admin', 'Lecturer']:
        flash('Bạn không có quyền truy cập phân hệ Giảng viên!', 'danger')
        return redirect(url_for('auth.dashboard'))


# --- CONTROLLERS ---

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = UserModel.find_by_username(username)

        if not user:
            flash('Tên đăng nhập không tồn tại.', 'danger')
            return render_template('login.html')

        # Kiểm tra tài khoản đã bị khóa chưa
        if user['Status'] == 'Locked':
            flash('Tài khoản của bạn đã bị khóa do nhập sai mật khẩu quá 5 lần. Vui lòng liên hệ Admin.', 'danger')
            return render_template('login.html')

        # So khớp mật khẩu
        if UserModel.verify_password(user['PasswordHash'], password):
            # Đăng nhập đúng: Reset số lần sai và lưu session
            UserModel.reset_failed_login(user['Id'])
            session['user_id'] = user['Id']
            session['username'] = user['Username']
            session['role'] = user['Role'] # 'Admin', 'Student', 'Lecturer'
            
            flash('Đăng nhập thành công!', 'success')
            return redirect(url_for('auth.dashboard'))
        else:
            # Đăng nhập sai: Tăng FailedLoginCount
            UserModel.increment_failed_login(user['Id'], user['FailedLoginCount'])
            remaining = 5 - (user['FailedLoginCount'] + 1)
            
            if remaining <= 0:
                flash('Tài khoản của bạn đã bị khóa do nhập sai mật khẩu quá 5 lần.', 'danger')
            else:
                flash(f'Mật khẩu không chính xác. Bạn còn {remaining} lần thử.', 'warning')
            
            return render_template('login.html')

    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Đã đăng xuất thành công.', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    return render_template('dashboard.html', role=session.get('role'))

@auth_bp.route('/change-password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    old_password = request.form.get('old_password')
    new_password = request.form.get('new_password')
    
    user = UserModel.find_by_username(session['username'])
    if not UserModel.verify_password(user['PasswordHash'], old_password):
        flash('Mật khẩu cũ không chính xác.', 'danger')
        return redirect(url_for('auth.dashboard'))
    
    import hashlib
    new_hash = hashlib.sha256(new_password.encode()).hexdigest()
    UserModel.update_password(user['Id'], new_hash)
    flash('Đổi mật khẩu thành công!', 'success')
    return redirect(url_for('auth.dashboard'))