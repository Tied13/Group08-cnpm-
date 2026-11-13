"""
controllers/lecturer_controller.py
==================================
Controller cho PHAN HE GIANG VIEN.
Nguoi phu trach: Thanh vien 5 - Luu Quynh (Backend Developer: Lecturer & QA Lead).

Gom 2 nhom route (tien to /lecturer):
  1. Route render giao dien HTML (lecturerView/*.html). Ho tro ca dang ngan
     (/lecturer/classes) va dang ten file (/lecturer/lecturer-classes.html) vi sidebar
     trong template dang dung link tuong doi "lecturer-classes.html".
  2. Route API JSON (/lecturer/api/...) duoc static/js/lecturer.js goi bang fetch,
     va endpoint xuat CSV (/lecturer/api/classes/<id>/export).

Dinh dang phan hoi API (thong nhat voi admin_controller):
  Thanh cong: {"success": true,  "message": "...", "data": ...}
  That bai  : {"success": false, "message": "..."}  + HTTP 400/401/403/404/500
"""

from datetime import date, datetime, time
from decimal import Decimal
from functools import wraps

from flask import (
    Blueprint, Response, current_app, jsonify, redirect,
    render_template, request, session, url_for,
)

from models.lecturer_model import (
    LecturerClassModel,
    LecturerError,
    LecturerExportModel,
    LecturerProfileModel,
    LecturerScheduleModel,
)

lecturer_bp = Blueprint('lecturer_bp', __name__, url_prefix='/lecturer')


# ==========================================================================
# BAO VE PHAN HE: chi tai khoan co role = 'Lecturer' moi duoc truy cap /lecturer/*
# (lop bao ve bo sung, ben canh middleware RBAC chung cua module Auth)
# ==========================================================================
@lecturer_bp.before_request
def ensure_lecturer_role():
    if session.get('role') == 'Lecturer':
        return None
    if request.path.startswith('/lecturer/api/'):
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'Vui lòng đăng nhập để tiếp tục.'}), 401
        return jsonify({'success': False, 'message': 'Bạn không có quyền truy cập chức năng Giảng viên.'}), 403
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
        except LecturerError as exc:
            return api_error(exc.message, exc.status_code)
        except Exception as exc:  # pragma: no cover - phong khi loi CSDL ngoai du kien
            current_app.logger.exception('Lecturer API error: %s', exc)
            return api_error(f'Lỗi máy chủ: {exc}', 500)
    return wrapper


def _lecturer_id():
    return session.get('user_id')


def _semester_id_arg():
    """semester_id tu query string; neu khong co thi dung hoc ky hien hanh."""
    semester_id = request.args.get('semester_id', type=int)
    if semester_id:
        return semester_id
    return LecturerClassModel.get_current_semester_id()


# ==========================================================================
# 1. ROUTE RENDER GIAO DIEN
# ==========================================================================
@lecturer_bp.route('/')
def lecturer_home():
    return redirect(url_for('lecturer_bp.classes_page'))


@lecturer_bp.route('/classes')
@lecturer_bp.route('/lecturer-classes.html')
def classes_page():
    return render_template('lecturerView/lecturer-classes.html')


@lecturer_bp.route('/schedule')
@lecturer_bp.route('/lecturer-schedule.html')
def schedule_page():
    return render_template('lecturerView/lecturer-schedule.html')


@lecturer_bp.route('/students')
@lecturer_bp.route('/lecturer-students.html')
def students_page():
    return render_template('lecturerView/lecturer-students.html')


@lecturer_bp.route('/profile')
@lecturer_bp.route('/lecturer-profile.html')
def profile_page():
    return render_template('lecturerView/lecturer-profile.html')


@lecturer_bp.route('/lecturer-login.html')
def logout_link():
    """Nut 'Log Out' trong template tro toi lecturer-login.html -> chuyen sang /logout cua Auth."""
    return redirect('/logout')


# ==========================================================================
# 2. API JSON
# ==========================================================================
@lecturer_bp.route('/api/me')
@api_endpoint
def api_me():
    return api_success(LecturerProfileModel.get_profile(_lecturer_id()))


@lecturer_bp.route('/api/semesters')
@api_endpoint
def api_semesters():
    semesters = LecturerClassModel.list_semesters()
    return api_success({
        'semesters': semesters,
        'current_semester_id': LecturerClassModel.get_current_semester_id(),
    })


@lecturer_bp.route('/api/classes')
@api_endpoint
def api_classes():
    """Danh sach lop phu trach (kem si so thuc te) + thong ke tai giang day."""
    semester_id = _semester_id_arg()
    if not semester_id:
        return api_success({'classes': [], 'summary': LecturerClassModel.summarize([])})
    classes = LecturerClassModel.list_assigned_classes(_lecturer_id(), semester_id)
    return api_success({
        'semester_id': semester_id,
        'classes': classes,
        'summary': LecturerClassModel.summarize(classes),
    })


@lecturer_bp.route('/api/schedule')
@api_endpoint
def api_schedule():
    """Lich giang day theo tuan: ?semester_id=&week= (khong co week -> tuan hien tai)."""
    semester_id = _semester_id_arg()
    if not semester_id:
        return api_error('Chưa có học kỳ nào trong hệ thống.', 404)
    week = request.args.get('week')
    data = LecturerScheduleModel.build_weekly_schedule(_lecturer_id(), semester_id, week)
    return api_success(data)


@lecturer_bp.route('/api/classes/<int:class_id>/students')
@api_endpoint
def api_class_students(class_id):
    cls, students = LecturerClassModel.list_students(_lecturer_id(), class_id)
    return api_success({'class': cls, 'students': students, 'total': len(students)})


@lecturer_bp.route('/api/classes/<int:class_id>/export')
@api_endpoint
def api_export_students(class_id):
    """Xuat danh sach SV cua lop ra .csv ma hoa UTF-8 (co BOM de Excel doc dung tieng Viet)."""
    filename, content = LecturerExportModel.build_students_csv(_lecturer_id(), class_id)
    payload = content.encode('utf-8-sig')
    return Response(
        payload,
        mimetype='text/csv',
        headers={
            'Content-Type': 'text/csv; charset=utf-8',
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Cache-Control': 'no-store',
        },
    )


@lecturer_bp.route('/api/change-password', methods=['POST'])
@api_endpoint
def api_change_password():
    data = request.get_json(silent=True) or {}
    LecturerProfileModel.change_password(
        _lecturer_id(),
        data.get('current_password', ''),
        data.get('new_password', ''),
        data.get('confirm_password', ''),
    )
    return api_success(message='Đổi mật khẩu thành công.')
