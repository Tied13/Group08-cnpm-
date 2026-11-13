"""
controllers/student_controller.py
==================================
Controller cho PHÂN HỆ SINH VIÊN (Student Portal).
Hệ thống Đăng ký Môn học (Course Registration System).

Gồm 2 nhóm route (tiền tố /student):
  1. Route render giao diện HTML (studentView/*.html):
     - /student/courses, /student/courses.html (Tra cứu & Đăng ký môn học)
     - /student/course-details, /student/course-details.html (Chi tiết lớp học phần)
     - /student/timetable, /student/timetable.html (Thời khóa biểu theo tuần)
     - /student/tuition, /student/tuition.html (Bảng kê học phí tự động)
     - /student/history, /student/history.html (Lịch sử giao dịch đăng ký/hủy)
     - /student/profile, /student/profile.html (Quản lý hồ sơ cá nhân & đổi mật khẩu)
  2. Route API JSON (/student/api/...):
     - Giao tiếp dữ liệu với static/js/student.js bằng Fetch API.

Định dạng phản hồi API:
  Thành công: {"success": true, "message": "...", "data": ...}
  Thất bại  : {"success": false, "message": "..."} + HTTP 400/401/403/404/409/500
"""

from datetime import date, datetime, time
from decimal import Decimal
from functools import wraps

from flask import (
    Blueprint, current_app, jsonify, redirect,
    render_template, request, session, url_for,
)

from models.student_model import (
    StudentCourseModel,
    StudentError,
    StudentHistoryModel,
    StudentLookupModel,
    StudentNotFoundError,
    StudentProfileModel,
    StudentRegistrationModel,
    StudentScheduleModel,
    StudentTuitionModel,
    StudentValidationError,
)

student_bp = Blueprint('student_bp', __name__, url_prefix='/student')


# ==========================================================================
# BẢO VỆ PHÂN HỆ (RBAC Guard)
# Chỉ tài khoản có role = 'Student' mới được truy cập /student/*
# ==========================================================================
@student_bp.before_request
def ensure_student_role():
    if session.get('role') == 'Student':
        return None
    if request.path.startswith('/student/api/'):
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'Vui lòng đăng nhập để tiếp tục.'}), 401
        return jsonify({'success': False, 'message': 'Bạn không có quyền truy cập chức năng Sinh viên.'}), 403
    return redirect('/login')


# ==========================================================================
# HÀM TRỢ GIÚP DÙNG CHUNG
# ==========================================================================
def _jsonable(value):
    """Chuyển đổi kiểu dữ liệu datetime / time / Decimal về JSON hợp lệ."""
    if isinstance(value, dict):
        return {key: _jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat(timespec='seconds')
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime('%H:%M')
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='ignore')
    return value


def api_success(data=None, message=None, status=200):
    return jsonify({'success': True, 'message': message, 'data': _jsonable(data)}), status


def api_error(message, status=400):
    return jsonify({'success': False, 'message': message}), status


def api_endpoint(func):
    """Bắt lỗi tập trung cho API: lỗi nghiệp vụ -> HTTP tương ứng (400, 404, 409...), lỗi khác -> 500."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except StudentError as exc:
            return api_error(exc.message, exc.status_code)
        except Exception as exc:
            current_app.logger.exception('Student API error: %s', exc)
            return api_error(f'Lỗi hệ thống: {exc}', 500)
    return wrapper


def _student_id():
    return session.get('user_id')


def _semester_id_arg():
    """Lấy semester_id từ query parameter, nếu không có lấy học kỳ hiện hành."""
    sem_id = request.args.get('semester_id', type=int)
    if sem_id:
        return sem_id
    curr = StudentLookupModel.get_current_semester()
    if not curr:
        raise StudentValidationError("Chưa có học kỳ nào được kích hoạt trong hệ thống.")
    return curr['Id']


def _payload():
    """Lấy dữ liệu JSON hoặc Form từ request."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return request.form.to_dict() if request.form else {}


# ==========================================================================
# 1. ROUTE RENDER GIAO DIỆN HTML (studentView/*.html)
# ==========================================================================
@student_bp.route('/')
def student_home():
    return redirect(url_for('student_bp.courses_page'))


@student_bp.route('/courses')
@student_bp.route('/courses.html')
def courses_page():
    return render_template('studentView/courses.html')


@student_bp.route('/course-details')
@student_bp.route('/course-details.html')
def course_details_page():
    return render_template('studentView/course-details.html')


@student_bp.route('/timetable')
@student_bp.route('/timetable.html')
def timetable_page():
    return render_template('studentView/timetable.html')


@student_bp.route('/tuition')
@student_bp.route('/tuition.html')
def tuition_page():
    return render_template('studentView/tuition.html')


@student_bp.route('/history')
@student_bp.route('/history.html')
def history_page():
    return render_template('studentView/history.html')


@student_bp.route('/profile')
@student_bp.route('/profile.html')
def profile_page():
    return render_template('studentView/profile.html')


@student_bp.route('/login.html')
@student_bp.route('/logout')
def student_logout():
    return redirect('/logout')


# ==========================================================================
# 2. API ENDPOINTS (/student/api/...)
# ==========================================================================

# 2.1. Thông tin sinh viên & Học kỳ
@student_bp.route('/api/me', methods=['GET'])
@api_endpoint
def api_me():
    """Lấy thông tin tài khoản và hồ sơ sinh viên đang đăng nhập."""
    profile = StudentProfileModel.get_profile(_student_id())
    curr_sem = StudentLookupModel.get_current_semester()
    return api_success({
        'profile': profile,
        'current_semester': curr_sem,
    })


@student_bp.route('/api/semesters', methods=['GET'])
@api_endpoint
def api_semesters():
    """Danh mục học kỳ và học kỳ hiện hành."""
    semesters = StudentLookupModel.get_semesters()
    curr_sem = StudentLookupModel.get_current_semester()
    return api_success({
        'semesters': semesters,
        'current_semester_id': curr_sem['Id'] if curr_sem else (semesters[0]['Id'] if semesters else None),
    })


# 2.2. Danh mục lớp học phần & Trạng thái đăng ký
@student_bp.route('/api/courses', methods=['GET'])
@api_endpoint
def api_courses():
    """
    Hiển thị danh mục các lớp học phần đang mở trong đợt đăng ký hiện hành.
    Bao gồm thông tin kiểm tra 4 điều kiện của từng lớp và danh sách lớp đã đăng ký.
    """
    student_id = _student_id()
    semester_id = _semester_id_arg()
    data = StudentCourseModel.get_available_classes(student_id, semester_id)
    return api_success(data)


@student_bp.route('/api/classes/<int:class_id>', methods=['GET'])
@api_endpoint
def api_class_detail(class_id):
    """Lấy thông số kỹ thuật chi tiết của một lớp học phần."""
    student_id = _student_id()
    detail = StudentCourseModel.get_class_detail(student_id, class_id)
    return api_success(detail)


# 2.3. Đăng ký môn học (Kiểm tra 4 điều kiện nghiêm ngặt)
@student_bp.route('/api/register', methods=['POST'])
@api_endpoint
def api_register_course():
    """
    Thuật toán Đăng ký môn học:
      1. Lớp còn chỗ trống (CurrentEnrollment < MaxCapacity).
      2. Môn tiên quyết đã được hoàn thành (kiểm tra lịch sử học tập).
      3. Lớp đăng ký không trùng ngày học và ca học với bất kỳ lớp nào đã đăng ký trong kỳ.
      4. Tổng tín chỉ sau khi đăng ký không vượt quá 25 tín chỉ (và đạt tối thiểu 12 tín chỉ khi kết thúc đợt).
      - Tăng CurrentEnrollment lên 1 khi đăng ký thành công.
      - Ghi log RegistrationHistory.
      - Tự động cập nhật Tuitions.
    """
    student_id = _student_id()
    data = _payload()
    class_id = data.get('class_id')
    if not class_id:
        raise StudentValidationError("Vui lòng chọn lớp học phần cần đăng ký.")

    try:
        class_id = int(class_id)
    except (ValueError, TypeError):
        raise StudentValidationError("Mã lớp học phần (class_id) không hợp lệ.")

    result = StudentRegistrationModel.register_course(student_id, class_id)
    return api_success(data=result.get('data'), message=result.get('message'), status=201)


# 2.4. Hủy đăng ký môn học
@student_bp.route('/api/drop', methods=['POST'])
@api_endpoint
def api_drop_course():
    """
    Hủy đăng ký môn học:
      - Cho phép sinh viên hủy môn trong thời gian mở cổng đăng ký.
      - Giảm CurrentEnrollment của lớp đi 1.
      - Cập nhật bản ghi ghi danh sang Cancelled.
      - Ghi log RegistrationHistory.
      - Tự động cập nhật lại Tuitions.
    """
    student_id = _student_id()
    data = _payload()
    class_id = data.get('class_id')
    if not class_id:
        raise StudentValidationError("Vui lòng chọn lớp học phần cần hủy.")

    try:
        class_id = int(class_id)
    except (ValueError, TypeError):
        raise StudentValidationError("Mã lớp học phần không hợp lệ.")

    result = StudentRegistrationModel.drop_course(student_id, class_id)
    return api_success(data=result.get('data'), message=result.get('message'))


# 2.5. Thời khóa biểu theo dạng lưới tuần
@student_bp.route('/api/timetable', methods=['GET'])
@api_endpoint
def api_timetable():
    """
    Render thời khóa biểu theo dạng lưới tuần:
      - Các ca học và ngày học trong tuần được hiển thị trực quan.
      - Cho phép điều hướng xem các tuần khác nhau trong học kỳ.
    """
    student_id = _student_id()
    semester_id = _semester_id_arg()
    week = request.args.get('week', type=int)
    grid = StudentScheduleModel.build_weekly_schedule(student_id, semester_id, week=week)
    return api_success(grid)


# 2.6. Bảng kê học phí tự động
@student_bp.route('/api/tuition', methods=['GET'])
@api_endpoint
def api_tuition():
    """
    Tự động tính toán tổng học phí dựa trên đơn giá tín chỉ và số tín chỉ đăng ký:
      - Trả về thống kê tổng hợp và danh sách chi tiết các môn học tính phí.
    """
    student_id = _student_id()
    semester_id = _semester_id_arg()
    statement = StudentTuitionModel.get_tuition_statement(student_id, semester_id)
    return api_success(statement)


# 2.7. Lịch sử giao dịch đăng ký / hủy môn
@student_bp.route('/api/history', methods=['GET'])
@api_endpoint
def api_history():
    """Tra cứu toàn bộ lịch sử đăng ký & hủy môn học (Audit Log)."""
    student_id = _student_id()
    semester_id = request.args.get('semester_id', type=int)
    filter_type = request.args.get('filter', default='all')
    history = StudentHistoryModel.get_history(student_id, semester_id, filter_type=filter_type)
    return api_success(history)


# 2.8. Đổi mật khẩu tài khoản
@student_bp.route('/api/change-password', methods=['POST'])
@api_endpoint
def api_change_password():
    """Đổi mật khẩu tài khoản sinh viên."""
    student_id = _student_id()
    data = _payload()
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')
    confirm_password = data.get('confirm_password', '')

    StudentProfileModel.change_password(student_id, current_password, new_password, confirm_password)
    return api_success(message="Đổi mật khẩu thành công! Vui lòng ghi nhớ mật khẩu mới.")
