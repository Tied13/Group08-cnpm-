"""
controllers/admin_controller.py
===============================
Controller for the ADMIN PORTAL (System Administration).

Contains 2 route groups (prefix /admin):
  1. HTML view rendering routes (adminView/*.html).
     Supports both short paths (/admin/users) and file-based paths (/admin/admin-users.html)
     since the sidebar in templates uses relative links like "admin-users.html".
  2. JSON API routes (/admin/api/...) called by static/js/admin.js via fetch.

API response format:
  Success: {"success": true,  "message": "...", "data": ...}
  Failure: {"success": false, "message": "..."}  + HTTP 400/401/403/404/409/500
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
from models.user_model import UserModel

admin_bp = Blueprint('admin_bp', __name__, url_prefix='/admin')


# ==========================================================================
# PORTAL PROTECTION: only accounts with role = 'Admin' can access /admin/*
# (additional guard layer alongside the global Auth RBAC middleware)
# ==========================================================================
@admin_bp.before_request
def ensure_admin_role():
    if session.get('role') == 'Admin':
        return None
    if request.path.startswith('/admin/api/'):
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'Please log in to continue.'}), 401
        return jsonify({'success': False, 'message': 'You do not have permission to access Admin Portal.'}), 403
    return redirect('/login')


# ==========================================================================
# HELPER FUNCTIONS
# ==========================================================================
def _jsonable(value):
    """Convert datetime / time / Decimal / bytes into JSON-serializable types."""
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
    """Centralized error handler for all APIs: business errors -> 4xx, system errors -> 500."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AdminError as exc:
            return api_error(exc.message, exc.status_code)
        except Exception as exc:  # pragma: no cover - fallback for unexpected DB errors
            if type(exc).__name__ == 'IntegrityError':
                return api_error('Database constraint violation (duplicate or foreign key error).', 409)
            current_app.logger.exception('Admin API error: %s', exc)
            return api_error(f'Server error: {exc}', 500)
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
        raise AdminValidationError('No semester found in the system.')
    return semester_id


# ==========================================================================
# 1. HTML VIEW RENDERING ROUTES
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
    """Sidebar 'Log Out' button -> redirect to the shared Auth logout route."""
    return redirect('/logout')


# ==========================================================================
# 2. API: GENERAL INFO & LOOKUPS
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
# 3. API: USER ACCOUNT MANAGEMENT
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
    return api_success(user, f"Successfully created {user['Role']} account {user['UserCode']}.", 201)


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
    return api_success(user, 'Account information updated successfully.')


@admin_bp.route('/api/users/<int:user_id>/status', methods=['POST'])
@api_endpoint
def api_set_user_status(user_id):
    result = AdminUserModel.set_user_status(user_id, _payload().get('status'))
    action = 'unlocked' if result['Status'] == 'Active' else 'locked'
    return api_success(result, f"Account {result['UserCode']} has been {action}.")


@admin_bp.route('/api/users/<int:user_id>/toggle-status', methods=['POST'])
@api_endpoint
def api_toggle_user_status(user_id):
    result = AdminUserModel.toggle_user_status(user_id)
    action = 'unlocked' if result['Status'] == 'Active' else 'locked'
    return api_success(result, f"Account {result['UserCode']} has been {action}.")


# ==========================================================================
# 4. API: COURSE MANAGEMENT & MANUAL ENROLLMENT OVERRIDE
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
    return api_success(course, f"Course {course['CourseCode']} created successfully.", 201)


@admin_bp.route('/api/courses/<int:course_id>', methods=['GET'])
@api_endpoint
def api_get_course(course_id):
    return api_success(AdminCourseModel.get_course(course_id))


@admin_bp.route('/api/courses/<int:course_id>', methods=['PUT'])
@api_endpoint
def api_update_course(course_id):
    course = AdminCourseModel.update_course(course_id, **_course_kwargs(_payload()))
    return api_success(course, f"Course {course['CourseCode']} updated successfully.")


@admin_bp.route('/api/courses/<int:course_id>', methods=['DELETE'])
@api_endpoint
def api_delete_course(course_id):
    result = AdminCourseModel.delete_course(course_id)
    note = ' (hidden from catalog, history retained)' if result['DeleteMode'] == 'soft' else ''
    return api_success(result, f"Course {result['CourseCode']} deleted{note}.")


@admin_bp.route('/api/courses/<int:course_id>/toggle-status', methods=['POST'])
@api_endpoint
def api_toggle_course_status(course_id):
    result = AdminCourseModel.toggle_course_status(course_id)
    state = 'Active' if result['IsActive'] else 'Locked'
    return api_success(result, f"Course {result['CourseCode']} status changed to {state}.")


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
    verb = 'added to' if result['Action'] == 'ADD' else 'removed from'
    return api_success(result, f"Student {result['StudentCode']} successfully {verb} class {result['ClassCode']}.")


# ==========================================================================
# 5. API: CLASS SECTIONS
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
    return api_success(created, f"Class {created['ClassCode']} opened and assigned to {created['LecturerName']}.", 201)


@admin_bp.route('/api/classes/<int:class_id>/cancel', methods=['POST'])
@api_endpoint
def api_cancel_class(class_id):
    result = AdminClassModel.cancel_class(class_id, _current_admin_id())
    return api_success(
        result,
        f"Class {result['ClassCode']} cancelled. {result['AffectedStudents']} student enrollments changed to Cancelled.",
    )


# ==========================================================================
# 6. API: REGISTRATION PERIODS
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
    return api_success(period, 'Registration period configuration saved.', 201)


@admin_bp.route('/api/periods/<int:period_id>/active', methods=['POST'])
@api_endpoint
def api_set_period_active(period_id):
    result = AdminPeriodModel.set_period_active(period_id, _payload().get('is_active', True))
    return api_success(result, 'Registration period opened.' if result['IsActive'] else 'Registration period closed.')


# ==========================================================================
# 7. API: REGISTRATION STATISTICS & REPORTS
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


# ==========================================================================
# 8. API: ADMIN ACCOUNT PASSWORD CHANGE
# ==========================================================================
@admin_bp.route('/api/change-password', methods=['POST'])
@api_endpoint
def api_change_password():
    """Change the password for the currently logged-in Admin account."""
    data = request.get_json(silent=True) or request.form or {}
    cur_pwd = data.get('current_password', '')
    new_pwd = data.get('new_password', '')
    cfm_pwd = data.get('confirm_password', '')

    if not cur_pwd or not new_pwd or not cfm_pwd:
        raise AdminValidationError("Please enter all required password fields.")
    if len(new_pwd) < 6:
        raise AdminValidationError("New password must be at least 6 characters.")
    if new_pwd != cfm_pwd:
        raise AdminValidationError("Password confirmation does not match.")
    if new_pwd == cur_pwd:
        raise AdminValidationError("New password must be different from current password.")

    user_id = session.get('user_id')
    user = UserModel.find_by_id(user_id)
    if not user:
        return api_error("Admin account not found.", 404)

    if not UserModel.verify_password(user['PasswordHash'], cur_pwd):
        raise AdminValidationError("Current password is incorrect.")

    UserModel.update_password(user_id, new_pwd)
    return api_success(message="Admin password changed successfully! Please remember your new password.")
