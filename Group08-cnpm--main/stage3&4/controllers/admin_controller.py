"""
controllers/admin_controller.py
===============================
Controller cho PHAN HE ADMIN (Quan tri he thong).

Gom 2 nhom route (tien to /admin):
  1. Route render giao dien HTML (adminView/*.html).
     Ho tro ca dang ngan (/admin/users) va dang ten file (/admin/admin-users.html)
     vi sidebar trong template dang dung link tuong doi "admin-users.html".
  2. Route API JSON (/admin/api/...) duoc static/js/admin.js goi bang fetch.

Dinh dang phan hoi API:
  Thanh cong: {"success": true,  "message": "...", "data": ...}
  That bai  : {"success": false, "message": "..."}  + HTTP 400/401/403/404/409/500
"""

from datetime import date, datetime, time
from decimal import Decimal
from functools import wraps

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

from models.admin_model import (
    AdminClassModel,
    AdminCourseModel,
    AdminEnrollmentModel,
    AdminError,
    AdminLookupModel,
    AdminPeriodModel,
    AdminReportModel,
    AdminUserModel,
    AdminValidationError,
    MIN_CLASS_ENROLLMENT,
)

admin_bp = Blueprint('admin_bp', __name__, url_prefix='/admin')


# ==========================================================================
# BAO VE PHAN HE: chi tai khoan co role = 'Admin' moi duoc truy cap /admin/*
# (lop bao ve bo sung, ben canh middleware RBAC chung cua module Auth)
# ==========================================================================
@admin_bp.before_request
def ensure_admin_role():
    if session.get('role') == 'Admin':
        return None
    if request.path.startswith('/admin/api/'):
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'Vui lòng đăng nhập để tiếp tục.'}), 401
        return jsonify({'success': False, 'message': 'Bạn không có quyền truy cập chức năng Admin.'}), 403
    return redirect('/login')


# ==========================================================================
# HAM TRO GIUP
# ==========================================================================
def _jsonable(value):
    """Chuyen datetime / time / Decimal ... ve kieu JSON hop le."""
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
    """Bat loi tap trung cho moi API: loi nghiep vu -> 4xx, loi he thong -> 500."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AdminError as exc:
            return api_error(exc.message, exc.status_code)
        except Exception as exc:  # pragma: no cover - phong khi loi CSDL ngoai du kien
            if type(exc).__name__ == 'IntegrityError':
                return api_error('Dữ liệu vi phạm ràng buộc CSDL (trùng lặp hoặc khóa ngoại).', 409)
            current_app.logger.exception('Admin API error: %s', exc)
            return api_error(f'Lỗi máy chủ: {exc}', 500)
    return wrapper


def _payload():
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return request.form.to_dict() if request.form else {}


def _current_admin_id():
    return session.get('user_id')


def _semester_id_arg():
    semester_id = request.args.get('semester_id', type=int)
    if semester_id:
        return semester_id
    semester_id = AdminPeriodModel.get_current_semester_id()
    if not semester_id:
        raise AdminValidationError('Chưa có học kỳ nào trong hệ thống.')
    return semester_id


# ==========================================================================
# 1. ROUTE RENDER GIAO DIEN
# ==========================================================================
@admin_bp.route('/')
def admin_home():
    return redirect(url_for('admin_bp.users_page'))


@admin_bp.route('/users')
@admin_bp.route('/admin-users.html')
def users_page():
    return render_template('adminView/admin-users.html')


@admin_bp.route('/period')
@admin_bp.route('/admin-period.html')
def period_page():
    return render_template('adminView/admin-period.html')


@admin_bp.route('/courses')
@admin_bp.route('/admin-courses.html')
def courses_page():
    return render_template('adminView/admin-courses.html')


@admin_bp.route('/classes')
@admin_bp.route('/admin-classes.html')
def classes_page():
    return render_template('adminView/admin-classes.html')


@admin_bp.route('/reports')
@admin_bp.route('/admin-reports.html')
def reports_page():
    return render_template('adminView/admin-reports.html')


@admin_bp.route('/logout')
@admin_bp.route('/admin-login.html')
def admin_logout():
    """Nut 'Log Out' tren sidebar -> chuyen sang route dang xuat chung cua module Auth."""
    return redirect('/logout')


# ==========================================================================
# 2. API: THONG TIN CHUNG & TRA CUU
# ==========================================================================
@admin_bp.route('/api/me', methods=['GET'])
@api_endpoint
def api_me():
    return api_success({
        'UserId': session.get('user_id'),
        'Username': session.get('username'),
        'Role': session.get('role'),
        'MinClassEnrollment': MIN_CLASS_ENROLLMENT,
    })


@admin_bp.route('/api/semesters', methods=['GET'])
@api_endpoint
def api_semesters():
    return api_success(AdminPeriodModel.list_semesters())


@admin_bp.route('/api/timeslots', methods=['GET'])
@api_endpoint
def api_timeslots():
    return api_success(AdminLookupModel.list_timeslots())


@admin_bp.route('/api/lecturers', methods=['GET'])
@api_endpoint
def api_lecturers():
    return api_success(AdminLookupModel.list_lecturers())


@admin_bp.route('/api/classrooms', methods=['GET'])
@api_endpoint
def api_classrooms():
    return api_success(AdminLookupModel.list_classrooms())


# ==========================================================================
# 3. API: QUAN LY TAI KHOAN
# ==========================================================================
@admin_bp.route('/api/users', methods=['GET'])
@api_endpoint
def api_list_users():
    users = AdminUserModel.list_users(
        role=request.args.get('role'),
        status=request.args.get('status'),
        keyword=request.args.get('q'),
    )
    return api_success(users)


@admin_bp.route('/api/users', methods=['POST'])
@api_endpoint
def api_create_user():
    data = _payload()
    user = AdminUserModel.create_user(
        role=data.get('role'),
        user_code=data.get('user_code'),
        full_name=data.get('full_name'),
        email=data.get('email'),
        department=data.get('department'),
        password=data.get('password'),
        username=data.get('username'),
        phone=data.get('phone'),
        administrative_class=data.get('administrative_class'),
        enrollment_year=data.get('enrollment_year'),
        academic_degree=data.get('academic_degree'),
    )
    return api_success(user, f"Đã tạo tài khoản {user['Role']} {user['UserCode']} thành công.", 201)


@admin_bp.route('/api/users/<int:user_id>', methods=['GET'])
@api_endpoint
def api_get_user(user_id):
    return api_success(AdminUserModel.get_user(user_id))


@admin_bp.route('/api/users/<int:user_id>', methods=['PUT'])
@api_endpoint
def api_update_user(user_id):
    data = _payload()
    user = AdminUserModel.update_user(
        user_id,
        full_name=data.get('full_name'),
        email=data.get('email'),
        department=data.get('department'),
        phone=data.get('phone'),
        role=data.get('role'),
    )
    return api_success(user, 'Đã cập nhật thông tin tài khoản.')


@admin_bp.route('/api/users/<int:user_id>/status', methods=['POST'])
@api_endpoint
def api_set_user_status(user_id):
    result = AdminUserModel.set_user_status(user_id, _payload().get('status'))
    action = 'mở khóa' if result['Status'] == 'Active' else 'khóa'
    return api_success(result, f"Đã {action} tài khoản {result['UserCode']}.")


@admin_bp.route('/api/users/<int:user_id>/toggle-status', methods=['POST'])
@api_endpoint
def api_toggle_user_status(user_id):
    result = AdminUserModel.toggle_user_status(user_id)
    action = 'mở khóa' if result['Status'] == 'Active' else 'khóa'
    return api_success(result, f"Đã {action} tài khoản {result['UserCode']}.")


# ==========================================================================
# 4. API: QUAN LY MON HOC & GHI DANH THU CONG
# ==========================================================================
def _course_kwargs(data):
    return dict(
        course_code=data.get('course_code'),
        course_name=data.get('course_name'),
        credits=data.get('credits'),
        prerequisite_course_id=data.get('prerequisite_course_id'),
        theory_hours=data.get('theory_hours'),
        practice_hours=data.get('practice_hours'),
        department=data.get('department'),
    )


@admin_bp.route('/api/courses', methods=['GET'])
@api_endpoint
def api_list_courses():
    return api_success(AdminCourseModel.list_courses())


@admin_bp.route('/api/courses', methods=['POST'])
@api_endpoint
def api_create_course():
    course = AdminCourseModel.create_course(**_course_kwargs(_payload()))
    return api_success(course, f"Đã tạo môn học {course['CourseCode']}.", 201)


@admin_bp.route('/api/courses/<int:course_id>', methods=['GET'])
@api_endpoint
def api_get_course(course_id):
    return api_success(AdminCourseModel.get_course(course_id))


@admin_bp.route('/api/courses/<int:course_id>', methods=['PUT'])
@api_endpoint
def api_update_course(course_id):
    course = AdminCourseModel.update_course(course_id, **_course_kwargs(_payload()))
    return api_success(course, f"Đã cập nhật môn học {course['CourseCode']}.")


@admin_bp.route('/api/courses/<int:course_id>', methods=['DELETE'])
@api_endpoint
def api_delete_course(course_id):
    result = AdminCourseModel.delete_course(course_id)
    note = ' (ẩn khỏi danh mục, giữ lại lịch sử)' if result['DeleteMode'] == 'soft' else ''
    return api_success(result, f"Đã xóa môn học {result['CourseCode']}{note}.")


@admin_bp.route('/api/enrollments/override', methods=['POST'])
@api_endpoint
def api_manual_override():
    data = _payload()
    result = AdminEnrollmentModel.manual_override(
        student_code=data.get('student_code'),
        class_code=data.get('class_code'),
        action=data.get('action'),
        admin_user_id=_current_admin_id(),
    )
    verb = 'thêm' if result['Action'] == 'ADD' else 'xóa'
    preposition = 'vào' if result['Action'] == 'ADD' else 'khỏi'
    return api_success(result, f"Đã {verb} sinh viên {result['StudentCode']} {preposition} lớp {result['ClassCode']}.")


# ==========================================================================
# 5. API: LOP HOC PHAN
# ==========================================================================
@admin_bp.route('/api/classes', methods=['GET'])
@api_endpoint
def api_list_classes():
    return api_success(AdminClassModel.list_classes(_semester_id_arg()))


@admin_bp.route('/api/classes', methods=['POST'])
@api_endpoint
def api_create_class():
    data = _payload()
    created = AdminClassModel.create_class(
        course_id=data.get('course_id'),
        class_code=data.get('class_code'),
        semester_id=data.get('semester_id') or AdminPeriodModel.get_current_semester_id(),
        room=data.get('room'),
        day_of_week=data.get('day_of_week'),
        time_slot_id=data.get('time_slot_id'),
        max_capacity=data.get('max_capacity'),
        lecturer_id=data.get('lecturer_id'),
        lecturer_ref=data.get('lecturer'),
    )
    return api_success(created, f"Đã mở lớp {created['ClassCode']} và phân công {created['LecturerName']}.", 201)


@admin_bp.route('/api/classes/<int:class_id>/cancel', methods=['POST'])
@api_endpoint
def api_cancel_class(class_id):
    result = AdminClassModel.cancel_class(class_id, _current_admin_id())
    return api_success(
        result,
        f"Đã hủy lớp {result['ClassCode']}. {result['AffectedStudents']} đăng ký của sinh viên đã chuyển sang Cancelled.",
    )


# ==========================================================================
# 6. API: DOT DANG KY
# ==========================================================================
@admin_bp.route('/api/periods', methods=['GET'])
@api_endpoint
def api_list_periods():
    return api_success(AdminPeriodModel.list_periods(request.args.get('semester_id', type=int)))


@admin_bp.route('/api/periods/current', methods=['GET'])
@api_endpoint
def api_current_period():
    semester_id = _semester_id_arg()
    return api_success({'SemesterId': semester_id, 'Period': AdminPeriodModel.get_active_period(semester_id)})


@admin_bp.route('/api/periods', methods=['POST'])
@api_endpoint
def api_save_period():
    data = _payload()
    period = AdminPeriodModel.save_period(
        semester_id=data.get('semester_id') or AdminPeriodModel.get_current_semester_id(),
        start_date=data.get('start_date'),
        end_date=data.get('end_date'),
        period_name=data.get('period_name'),
        min_credits=data.get('min_credits'),
        max_credits=data.get('max_credits'),
    )
    return api_success(period, 'Đã lưu cấu hình đợt đăng ký.', 201)


@admin_bp.route('/api/periods/<int:period_id>/active', methods=['POST'])
@api_endpoint
def api_set_period_active(period_id):
    result = AdminPeriodModel.set_period_active(period_id, _payload().get('is_active', True))
    return api_success(result, 'Đã mở đợt đăng ký.' if result['IsActive'] else 'Đã đóng đợt đăng ký.')


# ==========================================================================
# 7. API: BAO CAO THONG KE
# ==========================================================================
@admin_bp.route('/api/reports', methods=['GET'])
@api_endpoint
def api_full_report():
    return api_success(AdminReportModel.full_report(_semester_id_arg()))


@admin_bp.route('/api/reports/sections', methods=['GET'])
@api_endpoint
def api_section_report():
    return api_success(AdminReportModel.section_report(_semester_id_arg()))


@admin_bp.route('/api/reports/students', methods=['GET'])
@api_endpoint
def api_student_report():
    return api_success(AdminReportModel.student_report(_semester_id_arg()))
