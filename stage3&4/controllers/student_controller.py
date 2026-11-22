"""
controllers/student_controller.py
==================================
Controller for the STUDENT PORTAL module.
Course Registration System.

Includes two route groups (prefix /student):
1. HTML template routes (studentView/*.html):
  - /student/courses, /student/courses.html (Course search & registration)
  - /student/course-details, /student/course-details.html (Class section details)
  - /student/timetable, /student/timetable.html (Weekly timetable)
  - /student/tuition, /student/tuition.html (Automated tuition statement)
  - /student/history, /student/history.html (Registration/drop transaction history)
  - /student/profile, /student/profile.html (Profile management & password change)
2. JSON API routes (/student/api/...):
  - Communicates data with static/js/student.js via Fetch API.

API response format:
  Success: {"success": true, "message": "...", "data": ...}
  Failure: {"success": false, "message": "..."} + HTTP 400/401/403/404/409/500
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
# MODULE ACCESS GUARD (RBAC Guard)
# Only accounts with role = 'Student' can access /student/*
# ==========================================================================
@student_bp.before_request
def ensure_student_role():
    if session.get('role') == 'Student':
        return None
    if request.path.startswith('/student/api/'):
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'Please log in to continue.'}), 401
        return jsonify({'success': False, 'message': 'You do not have permission to access Student Portal.'}), 403
    return redirect('/login')


# ==========================================================================
# SHARED HELPER FUNCTIONS
# ==========================================================================
def _jsonable(value):
    """Convert datetime / time / Decimal values to JSON-serializable types."""
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
    """Centralized error handling for APIs: business errors -> matching HTTP status (400, 404, 409...), other errors -> 500."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except StudentError as exc:
            return api_error(exc.message, exc.status_code)
        except Exception as exc:
            current_app.logger.exception('Student API error: %s', exc)
            return api_error(f'System error: {exc}', 500)
    return wrapper


def _student_id():
    return session.get('user_id')


def _semester_id_arg():
    """Get semester_id from query parameter; fallback to the current active semester."""
    sem_id = request.args.get('semester_id', type=int)
    if sem_id:
        return sem_id
    curr = StudentLookupModel.get_current_semester()
    if not curr:
        raise StudentValidationError("No active semester found in the system.")
    return curr['Id']


def _payload():
    """Extract JSON or Form data from the request."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return request.form.to_dict() if request.form else {}


# ==========================================================================
# 1. HTML TEMPLATE ROUTES (studentView/*.html)
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

# 2.1. Student info & Semesters
@student_bp.route('/api/me', methods=['GET'])
@api_endpoint
def api_me():
    """Get account and profile information for the currently logged-in student."""
    profile = StudentProfileModel.get_profile(_student_id())
    curr_sem = StudentLookupModel.get_current_semester()
    return api_success({
        'profile': profile,
        'current_semester': curr_sem,
    })


@student_bp.route('/api/semesters', methods=['GET'])
@api_endpoint
def api_semesters():
    """List semesters and the current active semester."""
    semesters = StudentLookupModel.get_semesters()
    curr_sem = StudentLookupModel.get_current_semester()
    return api_success({
        'semesters': semesters,
        'current_semester_id': curr_sem['Id'] if curr_sem else (semesters[0]['Id'] if semesters else None),
    })


# 2.2. Course catalog & Registration status
@student_bp.route('/api/courses', methods=['GET'])
@api_endpoint
def api_courses():
    """
    Display class sections open during the current registration period.
    Includes 4-condition validation info for each class and the list of registered classes.
    """
    student_id = _student_id()
    semester_id = _semester_id_arg()
    data = StudentCourseModel.get_available_classes(student_id, semester_id)
    return api_success(data)


@student_bp.route('/api/classes/<int:class_id>', methods=['GET'])
@api_endpoint
def api_class_detail(class_id):
    """Get detailed technical specifications of a class section."""
    student_id = _student_id()
    detail = StudentCourseModel.get_class_detail(student_id, class_id)
    return api_success(detail)


# 2.3. Course registration (Strict 4-condition check)
@student_bp.route('/api/register', methods=['POST'])
@api_endpoint
def api_register_course():
    student_id = _student_id()
    data = _payload()
    class_id = data.get('class_id')
    if not class_id:
        raise StudentValidationError("Please select a class section to register.")

    try:
        class_id = int(class_id)
    except (ValueError, TypeError):
        raise StudentValidationError("Invalid class ID.")

    result = StudentRegistrationModel.register_course(student_id, class_id)
    return api_success(data=result.get('data'), message=result.get('message'), status=201)


# 2.4. Drop course registration
@student_bp.route('/api/drop', methods=['POST'])
@api_endpoint
def api_drop_course():
    student_id = _student_id()
    data = _payload()
    class_id = data.get('class_id')
    if not class_id:
        raise StudentValidationError("Please select a class section to drop.")

    try:
        class_id = int(class_id)
    except (ValueError, TypeError):
        raise StudentValidationError("Invalid class ID.")

    result = StudentRegistrationModel.drop_course(student_id, class_id)
    return api_success(data=result.get('data'), message=result.get('message'))


# 2.5. Weekly grid timetable
@student_bp.route('/api/timetable', methods=['GET'])
@api_endpoint
def api_timetable():
    """
    Render timetable in a weekly grid format:
- Time slots and days of the week are displayed visually.
- Supports navigating across different weeks in the semester.
    """
    student_id = _student_id()
    semester_id = _semester_id_arg()
    week = request.args.get('week', type=int)
    grid = StudentScheduleModel.build_weekly_schedule(student_id, semester_id, week=week)
    return api_success(grid)


# 2.6. Automated tuition statement
@student_bp.route('/api/tuition', methods=['GET'])
@api_endpoint
def api_tuition():
    """
    Automatically calculate total tuition based on per-credit rate and registered credits:
- Returns summary statistics and a detailed list of billable courses.
    """
    student_id = _student_id()
    semester_id = _semester_id_arg()
    statement = StudentTuitionModel.get_tuition_statement(student_id, semester_id)
    return api_success(statement)


# 2.7. Registration / drop transaction history
@student_bp.route('/api/history', methods=['GET'])
@api_endpoint
def api_history():
    """Look up full course registration & drop history (Audit Log)."""
    student_id = _student_id()
    semester_id = request.args.get('semester_id', type=int)
    filter_type = request.args.get('filter', default='all')
    history = StudentHistoryModel.get_history(student_id, semester_id, filter_type=filter_type)
    return api_success(history)


# 2.8. Change account password
@student_bp.route('/api/change-password', methods=['POST'])
@api_endpoint
def api_change_password():
    """Change student account password."""
    student_id = _student_id()
    data = _payload()
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')
    confirm_password = data.get('confirm_password', '')

    StudentProfileModel.change_password(student_id, current_password, new_password, confirm_password)
    return api_success(message="Password changed successfully! Please remember your new password.")
