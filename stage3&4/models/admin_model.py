"""
models/admin_model.py
=====================
Tang du lieu (Model) cho PHAN HE ADMIN.

Chuc nang:
    1. AdminUserModel      - Quan ly tai khoan SV/GV (them moi, sua, khoa / mo khoa).
    2. AdminCourseModel    - Quan ly mon hoc (them/sua/xoa, chon mon tien quyet).
    3. AdminEnrollmentModel- Them/xoa thu cong sinh vien vao lop (truong hop dac biet).
    4. AdminClassModel     - Mo lop hoc phan (kiem tra trung phong / trung lich GV)
                             va HUY LOP HOC PHAN < 15 SV bang transaction.
    5. AdminPeriodModel    - Cau hinh dot dang ky (RegistrationPeriods).
    6. AdminReportModel    - Bao cao ty le lap day lop & tin chi theo sinh vien.
    7. AdminLookupModel    - Du lieu tra cuu (ca hoc, giang vien, phong hoc).

Moi truy van deu dung tham so '?' (chong SQL Injection) thong qua models/db.py.
Cac thao tac ghi nhieu bang duoc boc trong MOT transaction bang
`Database.get_cursor()` (tu commit khi thanh cong, tu rollback khi co loi).

Ghi chu: moi cau SQL co mot comment dang /* q:ten_truy_van */ de de doc log
va de Unit Test (tests/test_admin.py) nhan dien truy van. Comment nay khong
anh huong toi SQL Server.
"""

import re
from datetime import datetime
from decimal import Decimal

from werkzeug.security import generate_password_hash

from models.db import Database


# ==========================================================================
# HANG SO NGHIEP VU
# ==========================================================================
MIN_CLASS_ENROLLMENT = 15          # Lop co si so < 15 thi duoc phep huy
DEFAULT_MIN_CREDITS = 12
DEFAULT_MAX_CREDITS = 25
MIN_PASSWORD_LENGTH = 6
MAX_CLASS_CAPACITY = 500

MANAGEABLE_ROLES = ('Student', 'Lecturer')
USER_STATUSES = ('Active', 'Locked')
OVERRIDE_ACTIONS = ('ADD', 'REMOVE')
N_ADD_NOTE = 'Admin manual override: student added to class'
N_REMOVE_NOTE = 'Admin manual override: student removed from class'

DAY_NAMES = {
    2: 'Monday', 3: 'Tuesday', 4: 'Wednesday', 5: 'Thursday',
    6: 'Friday', 7: 'Saturday', 8: 'Sunday',
}
DAY_VALUES = {name.lower(): value for value, name in DAY_NAMES.items()}

EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
CODE_PATTERN = re.compile(r'^[A-Za-z0-9_.\-]+$')


# ==========================================================================
# EXCEPTIONS - Controller dua vao status_code de tra ve HTTP code tuong ung
# ==========================================================================
class AdminError(Exception):
    """Loi nghiep vu chung cua phan he Admin."""
    status_code = 400

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class AdminValidationError(AdminError):
    """Du lieu dau vao khong hop le (HTTP 400)."""
    status_code = 400


class AdminNotFoundError(AdminError):
    """Khong tim thay ban ghi (HTTP 404)."""
    status_code = 404


class AdminConflictError(AdminError):
    """Trung lap / xung dot du lieu (HTTP 409)."""
    status_code = 409


# ==========================================================================
# HAM TRO GIUP (dung chung trong file)
# ==========================================================================
def _execute(cursor, sql, params=None):
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)


def _fetch_one(cursor, sql, params=None):
    """Chay SELECT trong transaction hien tai va tra ve 1 dict (hoac None)."""
    _execute(cursor, sql, params)
    if not cursor.description:
        return None
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


def _fetch_all(cursor, sql, params=None):
    """Chay SELECT trong transaction hien tai va tra ve list dict."""
    _execute(cursor, sql, params)
    if not cursor.description:
        return []
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _clean(value):
    if isinstance(value, str):
        value = value.strip()
        return value if value != '' else None
    return value


def _require_text(value, label, max_len=None):
    value = _clean(value)
    if value is None:
        raise AdminValidationError(f'{label} không được để trống.')
    value = str(value)
    if max_len and len(value) > max_len:
        raise AdminValidationError(f'{label} không được vượt quá {max_len} ký tự.')
    return value


def _optional_text(value, label, max_len=None):
    value = _clean(value)
    if value is None:
        return None
    value = str(value)
    if max_len and len(value) > max_len:
        raise AdminValidationError(f'{label} không được vượt quá {max_len} ký tự.')
    return value


def _to_int(value, label, min_value=None, max_value=None, allow_none=False):
    value = _clean(value)
    if value is None or (isinstance(value, str) and value.lower() in ('none', 'null')):
        if allow_none:
            return None
        raise AdminValidationError(f'{label} không được để trống.')
    if isinstance(value, bool):
        raise AdminValidationError(f'{label} phải là số nguyên.')
    try:
        if isinstance(value, float) and not value.is_integer():
            raise ValueError
        number = int(value)
    except (TypeError, ValueError):
        raise AdminValidationError(f'{label} phải là số nguyên.')
    if min_value is not None and number < min_value:
        raise AdminValidationError(f'{label} phải lớn hơn hoặc bằng {min_value}.')
    if max_value is not None and number > max_value:
        raise AdminValidationError(f'{label} phải nhỏ hơn hoặc bằng {max_value}.')
    return number


def _parse_code(value, label, max_len):
    code = _require_text(value, label, max_len).upper()
    if not CODE_PATTERN.match(code):
        raise AdminValidationError(
            f'{label} chỉ được chứa chữ, số và các ký tự "_", ".", "-" (không có khoảng trắng).'
        )
    return code


def _parse_datetime(value, label):
    if isinstance(value, datetime):
        return value
    text = _require_text(value, label)
    try:
        # Ho tro dinh dang input datetime-local: 2026-11-13T09:30
        return datetime.fromisoformat(text.replace('Z', ''))
    except ValueError:
        raise AdminValidationError(f'{label} không đúng định dạng ngày giờ (YYYY-MM-DDTHH:MM).')


def _parse_day_of_week(value):
    """Nhan 2..8 hoac ten thu tieng Anh (Monday..Sunday)."""
    cleaned = _clean(value)
    if isinstance(cleaned, str) and cleaned.lower() in DAY_VALUES:
        return DAY_VALUES[cleaned.lower()]
    return _to_int(cleaned, 'Thứ trong tuần', 2, 8)


def _normalize_room(value):
    room = _require_text(value, 'Phòng học', 30)
    room = re.sub(r'^(room|phong|phòng)\s+', '', room, flags=re.IGNORECASE)
    return room.strip().upper()


def _period_status(period, now=None):
    now = now or datetime.now()
    if not period.get('IsActive'):
        return 'Inactive'
    start, end = period.get('StartDate'), period.get('EndDate')
    if start and now < start:
        return 'Upcoming'
    if end and now > end:
        return 'Ended'
    return 'Open'


def _to_number(value):
    if isinstance(value, Decimal):
        return float(value)
    return value or 0


# ==========================================================================
# 1. QUAN LY TAI KHOAN (Users / Students / Lecturers)
# ==========================================================================
class AdminUserModel:

    @staticmethod
    def list_users(role=None, status=None, keyword=None):
        """Danh sach tai khoan SV/GV (khong tra ve full password hash)."""
        sql = """/* q:list_users */
            SELECT u.Id, u.UserCode, u.Username, u.FullName, u.Email, u.Phone,
                   u.Role, u.Status, u.FailedLoginCount, u.PasswordHash, u.CreatedAt,
                   COALESCE(s.Major, l.Department) AS Department,
                   s.AdministrativeClass, s.EnrollmentYear, l.AcademicDegree
            FROM dbo.Users u
            LEFT JOIN dbo.Students s ON s.UserId = u.Id
            LEFT JOIN dbo.Lecturers l ON l.UserId = u.Id
            WHERE u.Role IN ('Student', 'Lecturer')"""
        params = []
        role = _clean(role)
        if role:
            if role not in MANAGEABLE_ROLES:
                raise AdminValidationError('Vai trò lọc không hợp lệ.')
            sql += " AND u.Role = ?"
            params.append(role)
        status = _clean(status)
        if status:
            if status not in USER_STATUSES:
                raise AdminValidationError('Trạng thái lọc không hợp lệ.')
            sql += " AND u.Status = ?"
            params.append(status)
        keyword = _clean(keyword)
        if keyword:
            like = f'%{keyword}%'
            sql += " AND (u.UserCode LIKE ? OR u.FullName LIKE ? OR u.Email LIKE ? OR u.Username LIKE ?)"
            params.extend([like, like, like, like])
        sql += " ORDER BY u.Role DESC, u.UserCode"

        users = Database.query_all(sql, params or None)
        for user in users:
            full_hash = user.pop('PasswordHash', None) or ''
            # Chi hien thi mot phan hash de minh hoa viec ma hoa mat khau
            user['PasswordHashPreview'] = (full_hash[:18] + '…') if full_hash else ''
        return users

    @staticmethod
    def get_user(user_id):
        user_id = _to_int(user_id, 'Mã người dùng', 1)
        user = Database.query_one(
            """/* q:user_by_id */
            SELECT u.Id, u.UserCode, u.Username, u.FullName, u.Email, u.Phone,
                   u.Role, u.Status, u.FailedLoginCount,
                   COALESCE(s.Major, l.Department) AS Department
            FROM dbo.Users u
            LEFT JOIN dbo.Students s ON s.UserId = u.Id
            LEFT JOIN dbo.Lecturers l ON l.UserId = u.Id
            WHERE u.Id = ?""",
            (user_id,),
        )
        if not user:
            raise AdminNotFoundError('Không tìm thấy tài khoản.')
        return user

    @staticmethod
    def create_user(role, user_code, full_name, email, department, password,
                    username=None, phone=None, administrative_class=None,
                    enrollment_year=None, academic_degree=None):
        """Them moi tai khoan Sinh vien hoac Giang vien (mat khau duoc bam)."""
        role = _require_text(role, 'Vai trò')
        if role not in MANAGEABLE_ROLES:
            raise AdminValidationError('Chỉ được tạo tài khoản Sinh viên (Student) hoặc Giảng viên (Lecturer).')
        user_code = _parse_code(user_code, 'Mã SV/GV', 20)
        full_name = _require_text(full_name, 'Họ tên', 100)
        email = _require_text(email, 'Email', 100).lower()
        if not EMAIL_PATTERN.match(email):
            raise AdminValidationError('Email không đúng định dạng.')
        department = _require_text(department, 'Khoa / Chuyên ngành', 100)
        password = password if isinstance(password, str) else ''
        if len(password) < MIN_PASSWORD_LENGTH:
            raise AdminValidationError(f'Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự.')
        username = _optional_text(username, 'Tên đăng nhập', 50) or user_code
        phone = _optional_text(phone, 'Số điện thoại', 20)
        administrative_class = _optional_text(administrative_class, 'Lớp sinh hoạt', 30) or 'UNASSIGNED'
        enrollment_year = _to_int(enrollment_year, 'Năm nhập học', 1990, 2100, allow_none=True) \
            or datetime.now().year
        academic_degree = _optional_text(academic_degree, 'Học vị', 50) or 'Master'

        password_hash = generate_password_hash(password)

        with Database.get_cursor() as cursor:
            duplicate = _fetch_one(
                cursor,
                """/* q:user_duplicate */
                SELECT TOP 1 UserCode, Username, Email
                FROM dbo.Users WITH (UPDLOCK, HOLDLOCK)
                WHERE UserCode = ? OR Username = ? OR Email = ?""",
                (user_code, username, email),
            )
            if duplicate:
                if (duplicate.get('UserCode') or '').upper() == user_code:
                    raise AdminConflictError(f"Mã người dùng '{user_code}' đã tồn tại.")
                if (duplicate.get('Email') or '').lower() == email:
                    raise AdminConflictError(f"Email '{email}' đã được sử dụng.")
                raise AdminConflictError(f"Tên đăng nhập '{username}' đã tồn tại.")

            inserted = _fetch_one(
                cursor,
                """/* q:insert_user */
                INSERT INTO dbo.Users (UserCode, Username, PasswordHash, FullName, Email, Phone,
                                       Role, Status, FailedLoginCount)
                OUTPUT INSERTED.Id
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Active', 0)""",
                (user_code, username, password_hash, full_name, email, phone, role),
            )
            new_id = inserted['Id']

            if role == 'Student':
                _execute(
                    cursor,
                    """/* q:insert_student */
                    INSERT INTO dbo.Students (UserId, StudentCode, AdministrativeClass, Major, EnrollmentYear)
                    VALUES (?, ?, ?, ?, ?)""",
                    (new_id, user_code, administrative_class, department, enrollment_year),
                )
            else:
                _execute(
                    cursor,
                    """/* q:insert_lecturer */
                    INSERT INTO dbo.Lecturers (UserId, LecturerCode, Department, AcademicDegree)
                    VALUES (?, ?, ?, ?)""",
                    (new_id, user_code, department, academic_degree),
                )

        return {
            'Id': new_id, 'UserCode': user_code, 'Username': username, 'FullName': full_name,
            'Email': email, 'Role': role, 'Department': department, 'Status': 'Active',
        }

    @staticmethod
    def update_user(user_id, full_name, email, department, phone=None, role=None):
        """Cap nhat thong tin co ban (khong cho phep doi vai tro)."""
        user_id = _to_int(user_id, 'Mã người dùng', 1)
        full_name = _require_text(full_name, 'Họ tên', 100)
        email = _require_text(email, 'Email', 100).lower()
        if not EMAIL_PATTERN.match(email):
            raise AdminValidationError('Email không đúng định dạng.')
        department = _require_text(department, 'Khoa / Chuyên ngành', 100)
        phone = _optional_text(phone, 'Số điện thoại', 20)

        with Database.get_cursor() as cursor:
            user = _fetch_one(
                cursor,
                "/* q:user_for_update */ SELECT Id, Role FROM dbo.Users WITH (UPDLOCK) WHERE Id = ?",
                (user_id,),
            )
            if not user:
                raise AdminNotFoundError('Không tìm thấy tài khoản.')
            if user['Role'] not in MANAGEABLE_ROLES:
                raise AdminValidationError('Không thể chỉnh sửa tài khoản Admin tại màn hình này.')
            if _clean(role) and _clean(role) != user['Role']:
                raise AdminValidationError('Không thể thay đổi vai trò của tài khoản đã tạo.')

            duplicate = _fetch_one(
                cursor,
                "/* q:email_duplicate */ SELECT TOP 1 Id FROM dbo.Users WHERE Email = ? AND Id <> ?",
                (email, user_id),
            )
            if duplicate:
                raise AdminConflictError(f"Email '{email}' đã được sử dụng bởi tài khoản khác.")

            _execute(
                cursor,
                """/* q:update_user */
                UPDATE dbo.Users
                SET FullName = ?, Email = ?, Phone = COALESCE(?, Phone), UpdatedAt = SYSDATETIME()
                WHERE Id = ?""",
                (full_name, email, phone, user_id),
            )
            if user['Role'] == 'Student':
                _execute(cursor, "/* q:update_student */ UPDATE dbo.Students SET Major = ? WHERE UserId = ?",
                         (department, user_id))
            else:
                _execute(cursor, "/* q:update_lecturer */ UPDATE dbo.Lecturers SET Department = ? WHERE UserId = ?",
                         (department, user_id))

        return {'Id': user_id, 'FullName': full_name, 'Email': email,
                'Department': department, 'Role': user['Role']}

    @staticmethod
    def set_user_status(user_id, status):
        """Doi trang thai thu cong Active <-> Locked. Mo khoa se reset FailedLoginCount = 0."""
        user_id = _to_int(user_id, 'Mã người dùng', 1)
        status = _require_text(status, 'Trạng thái')
        if status not in USER_STATUSES:
            raise AdminValidationError("Trạng thái chỉ có thể là 'Active' hoặc 'Locked'.")

        with Database.get_cursor() as cursor:
            user = _fetch_one(
                cursor,
                """/* q:user_for_status */
                SELECT Id, UserCode, FullName, Role, Status
                FROM dbo.Users WITH (UPDLOCK) WHERE Id = ?""",
                (user_id,),
            )
            if not user:
                raise AdminNotFoundError('Không tìm thấy tài khoản.')
            if user['Role'] not in MANAGEABLE_ROLES:
                raise AdminValidationError('Không thể khóa / mở khóa tài khoản Admin.')

            if status == 'Active':
                _execute(
                    cursor,
                    """/* q:unlock_user */
                    UPDATE dbo.Users
                    SET Status = 'Active', FailedLoginCount = 0, UpdatedAt = SYSDATETIME()
                    WHERE Id = ?""",
                    (user_id,),
                )
            else:
                _execute(
                    cursor,
                    """/* q:lock_user */
                    UPDATE dbo.Users SET Status = 'Locked', UpdatedAt = SYSDATETIME()
                    WHERE Id = ?""",
                    (user_id,),
                )

        return {'Id': user_id, 'UserCode': user['UserCode'], 'FullName': user['FullName'],
                'PreviousStatus': user['Status'], 'Status': status}

    @staticmethod
    def toggle_user_status(user_id):
        user = AdminUserModel.get_user(user_id)
        new_status = 'Active' if user['Status'] == 'Locked' else 'Locked'
        return AdminUserModel.set_user_status(user['Id'], new_status)


# ==========================================================================
# 2. QUAN LY MON HOC (Courses / CoursePrerequisites)
# ==========================================================================
class AdminCourseModel:

    @staticmethod
    def list_courses():
        return Database.query_all(
            """/* q:list_courses */
            SELECT c.Id, c.CourseCode, c.CourseName, c.Credits, c.TheoryHours, c.PracticeHours,
                   c.Department, c.PrerequisiteCourseId, c.IsActive,
                   p.CourseCode AS PrerequisiteCode, p.CourseName AS PrerequisiteName,
                   (SELECT COUNT(*) FROM dbo.Classes cl
                     WHERE cl.CourseId = c.Id AND cl.Status <> 'Cancelled') AS ActiveSections,
                   (SELECT ISNULL(SUM(cl.CurrentEnrollment), 0) FROM dbo.Classes cl
                     WHERE cl.CourseId = c.Id AND cl.Status <> 'Cancelled') AS RegisteredStudents
            FROM dbo.Courses c
            LEFT JOIN dbo.Courses p ON p.Id = c.PrerequisiteCourseId
            WHERE c.IsActive = 1
            ORDER BY c.CourseCode"""
        )

    @staticmethod
    def get_course(course_id):
        course_id = _to_int(course_id, 'Mã môn học', 1)
        course = Database.query_one(
            """/* q:course_detail */
            SELECT c.Id, c.CourseCode, c.CourseName, c.Credits, c.TheoryHours, c.PracticeHours,
                   c.Department, c.PrerequisiteCourseId, c.IsActive
            FROM dbo.Courses c WHERE c.Id = ?""",
            (course_id,),
        )
        if not course:
            raise AdminNotFoundError('Không tìm thấy môn học.')
        return course

    @staticmethod
    def _validate_payload(course_code, course_name, credits, prerequisite_course_id,
                          theory_hours, practice_hours, department):
        return {
            'code': _parse_code(course_code, 'Mã môn học', 20),
            'name': _require_text(course_name, 'Tên môn học', 150),
            'credits': _to_int(credits, 'Số tín chỉ', 1, 10),
            'prereq': _to_int(prerequisite_course_id, 'Môn tiên quyết', 1, allow_none=True),
            'theory': _to_int(theory_hours, 'Số tiết lý thuyết', 0, 500, allow_none=True),
            'practice': _to_int(practice_hours, 'Số tiết thực hành', 0, 500, allow_none=True),
            'department': _optional_text(department, 'Khoa / Bộ môn', 100),
        }

    @staticmethod
    def _ensure_prerequisite_exists(cursor, prereq_id):
        prereq = _fetch_one(
            cursor,
            "/* q:course_by_id */ SELECT Id, CourseCode, IsActive FROM dbo.Courses WHERE Id = ?",
            (prereq_id,),
        )
        if not prereq or not prereq.get('IsActive'):
            raise AdminValidationError('Môn tiên quyết không tồn tại trong danh sách môn hiện có.')
        return prereq

    @staticmethod
    def _sync_prerequisite_table(cursor, course_id, prereq_id):
        """Dong bo bang CoursePrerequisites voi cot Courses.PrerequisiteCourseId."""
        _execute(cursor, "/* q:delete_course_prereq */ DELETE FROM dbo.CoursePrerequisites WHERE CourseId = ?",
                 (course_id,))
        if prereq_id:
            _execute(
                cursor,
                """/* q:insert_course_prereq */
                INSERT INTO dbo.CoursePrerequisites (CourseId, PrerequisiteCourseId, IsMandatory)
                VALUES (?, ?, 1)""",
                (course_id, prereq_id),
            )

    @staticmethod
    def create_course(course_code, course_name, credits, prerequisite_course_id=None,
                      theory_hours=None, practice_hours=None, department=None):
        data = AdminCourseModel._validate_payload(course_code, course_name, credits,
                                                  prerequisite_course_id, theory_hours,
                                                  practice_hours, department)
        with Database.get_cursor() as cursor:
            duplicate = _fetch_one(
                cursor,
                """/* q:course_by_code */
                SELECT Id, CourseCode, IsActive FROM dbo.Courses WITH (UPDLOCK, HOLDLOCK)
                WHERE CourseCode = ?""",
                (data['code'],),
            )
            if duplicate:
                raise AdminConflictError(f"Mã môn học '{data['code']}' đã tồn tại. Vui lòng chọn mã khác.")

            if data['prereq']:
                AdminCourseModel._ensure_prerequisite_exists(cursor, data['prereq'])

            inserted = _fetch_one(
                cursor,
                """/* q:insert_course */
                INSERT INTO dbo.Courses (CourseCode, CourseName, Credits, TheoryHours, PracticeHours,
                                         Department, PrerequisiteCourseId, IsActive)
                OUTPUT INSERTED.Id
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                (data['code'], data['name'], data['credits'],
                 data['theory'] if data['theory'] is not None else 30,
                 data['practice'] if data['practice'] is not None else 15,
                 data['department'], data['prereq']),
            )
            course_id = inserted['Id']
            AdminCourseModel._sync_prerequisite_table(cursor, course_id, data['prereq'])

        return {'Id': course_id, 'CourseCode': data['code'], 'CourseName': data['name'],
                'Credits': data['credits'], 'PrerequisiteCourseId': data['prereq']}

    @staticmethod
    def update_course(course_id, course_code, course_name, credits, prerequisite_course_id=None,
                      theory_hours=None, practice_hours=None, department=None):
        course_id = _to_int(course_id, 'Mã môn học', 1)
        data = AdminCourseModel._validate_payload(course_code, course_name, credits,
                                                  prerequisite_course_id, theory_hours,
                                                  practice_hours, department)
        with Database.get_cursor() as cursor:
            current = _fetch_one(
                cursor,
                """/* q:course_for_update */
                SELECT Id, CourseCode, TheoryHours, PracticeHours, Department, IsActive
                FROM dbo.Courses WITH (UPDLOCK) WHERE Id = ?""",
                (course_id,),
            )
            if not current or not current.get('IsActive'):
                raise AdminNotFoundError('Không tìm thấy môn học.')

            duplicate = _fetch_one(
                cursor,
                "/* q:course_code_duplicate */ SELECT TOP 1 Id FROM dbo.Courses WHERE CourseCode = ? AND Id <> ?",
                (data['code'], course_id),
            )
            if duplicate:
                raise AdminConflictError(f"Mã môn học '{data['code']}' đã tồn tại. Vui lòng chọn mã khác.")

            if data['prereq']:
                if data['prereq'] == course_id:
                    raise AdminValidationError('Môn học không thể là môn tiên quyết của chính nó.')
                AdminCourseModel._ensure_prerequisite_exists(cursor, data['prereq'])
                # Chong vong lap tien quyet: A -> B -> ... -> A
                visited = set()
                pointer = data['prereq']
                while pointer and pointer not in visited:
                    if pointer == course_id:
                        raise AdminValidationError('Không thể chọn môn tiên quyết này vì tạo thành vòng lặp tiên quyết.')
                    visited.add(pointer)
                    row = _fetch_one(
                        cursor,
                        "/* q:course_prereq_of */ SELECT PrerequisiteCourseId FROM dbo.Courses WHERE Id = ?",
                        (pointer,),
                    )
                    pointer = row.get('PrerequisiteCourseId') if row else None

            theory = data['theory'] if data['theory'] is not None else current.get('TheoryHours')
            practice = data['practice'] if data['practice'] is not None else current.get('PracticeHours')
            department = data['department'] if data['department'] is not None else current.get('Department')

            _execute(
                cursor,
                """/* q:update_course */
                UPDATE dbo.Courses
                SET CourseCode = ?, CourseName = ?, Credits = ?, TheoryHours = ?, PracticeHours = ?,
                    Department = ?, PrerequisiteCourseId = ?
                WHERE Id = ?""",
                (data['code'], data['name'], data['credits'], theory, practice,
                 department, data['prereq'], course_id),
            )
            AdminCourseModel._sync_prerequisite_table(cursor, course_id, data['prereq'])

        return {'Id': course_id, 'CourseCode': data['code'], 'CourseName': data['name'],
                'Credits': data['credits'], 'PrerequisiteCourseId': data['prereq']}

    @staticmethod
    def delete_course(course_id):
        """
        Xoa mon hoc:
          - Chan neu con lop hoc phan chua bi huy hoac dang la tien quyet cua mon khac.
          - Neu mon da tung co lop (da huy) -> xoa mem (IsActive = 0) de giu lich su.
          - Nguoc lai -> xoa han.
        """
        course_id = _to_int(course_id, 'Mã môn học', 1)
        with Database.get_cursor() as cursor:
            course = _fetch_one(
                cursor,
                "/* q:course_for_delete */ SELECT Id, CourseCode, IsActive FROM dbo.Courses WITH (UPDLOCK) WHERE Id = ?",
                (course_id,),
            )
            if not course or not course.get('IsActive'):
                raise AdminNotFoundError('Không tìm thấy môn học.')

            usage = _fetch_one(
                cursor,
                """/* q:course_usage */
                SELECT
                  (SELECT COUNT(*) FROM dbo.Classes WHERE CourseId = ? AND Status <> 'Cancelled') AS OpenClasses,
                  (SELECT COUNT(*) FROM dbo.Classes WHERE CourseId = ?) AS AllClasses,
                  (SELECT COUNT(*) FROM dbo.Courses WHERE PrerequisiteCourseId = ? AND IsActive = 1) AS ActiveDependents,
                  (SELECT COUNT(*) FROM dbo.Courses WHERE PrerequisiteCourseId = ?) AS AllDependents,
                  (SELECT COUNT(*) FROM dbo.CoursePrerequisites WHERE PrerequisiteCourseId = ?) AS PrereqLinks""",
                (course_id, course_id, course_id, course_id, course_id),
            ) or {}

            if usage.get('OpenClasses', 0) > 0:
                raise AdminConflictError(
                    f"Không thể xóa môn {course['CourseCode']} vì đang có lớp học phần chưa bị hủy."
                )
            if usage.get('ActiveDependents', 0) > 0:
                raise AdminConflictError(
                    f"Không thể xóa môn {course['CourseCode']} vì đang là môn tiên quyết của môn khác."
                )

            if usage.get('AllClasses', 0) > 0 or usage.get('AllDependents', 0) > 0 \
                    or usage.get('PrereqLinks', 0) > 0:
                _execute(cursor, "/* q:soft_delete_course */ UPDATE dbo.Courses SET IsActive = 0 WHERE Id = ?",
                         (course_id,))
                mode = 'soft'
            else:
                _execute(cursor, "/* q:delete_course_prereq */ DELETE FROM dbo.CoursePrerequisites WHERE CourseId = ?",
                         (course_id,))
                _execute(cursor, "/* q:hard_delete_course */ DELETE FROM dbo.Courses WHERE Id = ?", (course_id,))
                mode = 'hard'

        return {'Id': course_id, 'CourseCode': course['CourseCode'], 'DeleteMode': mode}


# ==========================================================================
# 3. THEM / XOA SINH VIEN THU CONG VAO LOP (truong hop dac biet)
# ==========================================================================
class AdminEnrollmentModel:

    @staticmethod
    def manual_override(student_code, class_code, action, admin_user_id=None):
        """
        Admin them / xoa sinh vien khoi lop hoc phan (bo qua dieu kien thoi gian dang ky
        va mon tien quyet) nhung van dam bao: lop chua bi huy, con cho trong,
        khong dang ky trung mon trong cung hoc ky.
        """
        student_code = _require_text(student_code, 'Mã sinh viên', 20).upper()
        class_code = _require_text(class_code, 'Mã lớp học phần', 30).upper()
        action = (_require_text(action, 'Hành động') or '').upper()
        if action not in OVERRIDE_ACTIONS:
            raise AdminValidationError("Hành động chỉ có thể là 'ADD' hoặc 'REMOVE'.")

        with Database.get_cursor() as cursor:
            student = _fetch_one(
                cursor,
                """/* q:student_by_code */
                SELECT u.Id, u.UserCode, u.FullName, u.Status
                FROM dbo.Users u
                INNER JOIN dbo.Students s ON s.UserId = u.Id
                WHERE u.UserCode = ? OR s.StudentCode = ?""",
                (student_code, student_code),
            )
            if not student:
                raise AdminNotFoundError(f"Không tìm thấy sinh viên '{student_code}'.")

            course_class = _fetch_one(
                cursor,
                """/* q:class_by_code_for_override */
                SELECT Id, ClassCode, CourseId, SemesterId, Status, CurrentEnrollment, MaxCapacity
                FROM dbo.Classes WITH (UPDLOCK, ROWLOCK)
                WHERE ClassCode = ?""",
                (class_code,),
            )
            if not course_class:
                raise AdminNotFoundError(f"Không tìm thấy lớp học phần '{class_code}'.")

            enrollment = _fetch_one(
                cursor,
                """/* q:enrollment_by_pair */
                SELECT Id, Status FROM dbo.Enrollments WITH (UPDLOCK)
                WHERE StudentId = ? AND ClassId = ?""",
                (student['Id'], course_class['Id']),
            )

            if action == 'ADD':
                if course_class['Status'] == 'Cancelled':
                    raise AdminConflictError('Lớp học phần đã bị hủy, không thể thêm sinh viên.')
                if enrollment and enrollment['Status'] == 'Enrolled':
                    raise AdminConflictError('Sinh viên đã có trong lớp học phần này.')
                if course_class['CurrentEnrollment'] >= course_class['MaxCapacity']:
                    raise AdminConflictError('Lớp học phần đã đủ sĩ số tối đa.')
                same_course = _fetch_one(
                    cursor,
                    """/* q:same_course_enrolled */
                    SELECT TOP 1 cl.ClassCode
                    FROM dbo.Enrollments e
                    INNER JOIN dbo.Classes cl ON cl.Id = e.ClassId
                    WHERE e.StudentId = ? AND e.Status = 'Enrolled'
                      AND cl.CourseId = ? AND cl.SemesterId = ? AND cl.Id <> ?""",
                    (student['Id'], course_class['CourseId'], course_class['SemesterId'], course_class['Id']),
                )
                if same_course:
                    raise AdminConflictError(
                        f"Sinh viên đã đăng ký môn này ở lớp {same_course['ClassCode']} trong cùng học kỳ."
                    )

                if enrollment:
                    _execute(
                        cursor,
                        """/* q:reactivate_enrollment */
                        UPDATE dbo.Enrollments
                        SET Status = 'Enrolled', EnrolledAt = SYSDATETIME(), CancelledAt = NULL
                        WHERE Id = ?""",
                        (enrollment['Id'],),
                    )
                else:
                    _execute(
                        cursor,
                        """/* q:insert_enrollment */
                        INSERT INTO dbo.Enrollments (StudentId, ClassId, Status) VALUES (?, ?, 'Enrolled')""",
                        (student['Id'], course_class['Id']),
                    )
                _execute(
                    cursor,
                    """/* q:increment_enrollment */
                    UPDATE dbo.Classes
                    SET CurrentEnrollment = CurrentEnrollment + 1,
                        Status = CASE WHEN CurrentEnrollment + 1 >= MaxCapacity THEN 'Closed' ELSE Status END
                    WHERE Id = ?""",
                    (course_class['Id'],),
                )
                history_action, note = 'Register', N_ADD_NOTE
            else:
                if not enrollment or enrollment['Status'] != 'Enrolled':
                    raise AdminConflictError('Sinh viên hiện không có trong lớp học phần này.')
                _execute(
                    cursor,
                    """/* q:cancel_single_enrollment */
                    UPDATE dbo.Enrollments
                    SET Status = 'Cancelled', CancelledAt = SYSDATETIME()
                    WHERE Id = ?""",
                    (enrollment['Id'],),
                )
                _execute(
                    cursor,
                    """/* q:decrement_enrollment */
                    UPDATE dbo.Classes
                    SET CurrentEnrollment = CASE WHEN CurrentEnrollment > 0 THEN CurrentEnrollment - 1 ELSE 0 END,
                        Status = CASE WHEN Status = 'Closed' THEN 'Open' ELSE Status END
                    WHERE Id = ?""",
                    (course_class['Id'],),
                )
                history_action, note = 'Drop', N_REMOVE_NOTE

            _execute(
                cursor,
                """/* q:insert_history */
                INSERT INTO dbo.RegistrationHistory (StudentId, ClassId, ActionType, PerformedByUserId, Note)
                VALUES (?, ?, ?, ?, ?)""",
                (student['Id'], course_class['Id'], history_action, admin_user_id, note),
            )
            _execute(
                cursor,
                "/* q:recalc_tuition */ EXEC dbo.sp_RecalculateStudentTuition @StudentId = ?, @SemesterId = ?",
                (student['Id'], course_class['SemesterId']),
            )

        return {'StudentCode': student['UserCode'], 'StudentName': student['FullName'],
                'ClassCode': course_class['ClassCode'], 'Action': action}


# ==========================================================================
# 4. MO LOP HOC PHAN & HUY LOP < 15 SINH VIEN
# ==========================================================================
class AdminClassModel:

    @staticmethod
    def list_classes(semester_id=None):
        sql = """/* q:list_classes */
            SELECT cl.Id, cl.ClassCode, cl.CourseId, co.CourseCode, co.CourseName, co.Credits,
                   cl.SemesterId, se.SemesterCode, se.SemesterName,
                   cl.LecturerId, lu.UserCode AS LecturerCode, lu.FullName AS LecturerName,
                   cl.ClassroomId, cl.Room, cl.TimeSlotId, ts.SlotNumber, ts.SlotName,
                   ts.StartTime, ts.EndTime, cl.DayOfWeek,
                   cl.MinCapacity, cl.MaxCapacity, cl.CurrentEnrollment, cl.Status, cl.CreatedAt
            FROM dbo.Classes cl
            INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
            INNER JOIN dbo.Semesters se ON se.Id = cl.SemesterId
            INNER JOIN dbo.TimeSlots ts ON ts.Id = cl.TimeSlotId
            LEFT JOIN dbo.Users lu ON lu.Id = cl.LecturerId"""
        params = None
        if semester_id:
            sql += " WHERE cl.SemesterId = ?"
            params = (_to_int(semester_id, 'Học kỳ', 1),)
        sql += " ORDER BY cl.DayOfWeek, ts.SlotNumber, cl.ClassCode"

        classes = Database.query_all(sql, params)
        for item in classes:
            item['DayName'] = DAY_NAMES.get(item.get('DayOfWeek'), str(item.get('DayOfWeek')))
            item['CanCancel'] = item.get('Status') != 'Cancelled' \
                and (item.get('CurrentEnrollment') or 0) < MIN_CLASS_ENROLLMENT
        return classes

    @staticmethod
    def _resolve_lecturer(cursor, lecturer_id=None, lecturer_ref=None):
        """Tim giang vien theo Id, hoac theo chuoi 'GV001 - Ho Ten' / 'GV001' / 'Ho Ten'."""
        lecturer_id = _to_int(lecturer_id, 'Giảng viên', 1, allow_none=True)
        base_sql = """/* q:lecturer_lookup */
            SELECT u.Id, u.UserCode, u.FullName, u.Status
            FROM dbo.Users u
            INNER JOIN dbo.Lecturers l ON l.UserId = u.Id
            WHERE u.Role = 'Lecturer' AND """
        if lecturer_id:
            lecturer = _fetch_one(cursor, base_sql + "u.Id = ?", (lecturer_id,))
        else:
            ref = _require_text(lecturer_ref, 'Giảng viên phụ trách', 150)
            code = ref.split(' - ')[0].strip()
            lecturer = _fetch_one(
                cursor,
                base_sql + "(u.UserCode = ? OR l.LecturerCode = ? OR u.FullName = ?)",
                (code, code, ref),
            )
        if not lecturer:
            raise AdminValidationError('Không tìm thấy giảng viên được phân công.')
        if lecturer.get('Status') != 'Active':
            raise AdminValidationError(f"Giảng viên {lecturer['UserCode']} đang bị khóa, không thể phân công.")
        return lecturer

    @staticmethod
    def create_class(course_id, class_code, semester_id, room, day_of_week, time_slot_id,
                     max_capacity, lecturer_id=None, lecturer_ref=None,
                     min_capacity=MIN_CLASS_ENROLLMENT):
        """Mo lop hoc phan moi + phan cong giang vien, kiem tra trung phong & trung lich GV."""
        course_id = _to_int(course_id, 'Môn học', 1)
        class_code = _parse_code(class_code, 'Mã lớp học phần', 30)
        semester_id = _to_int(semester_id, 'Học kỳ', 1)
        room = _normalize_room(room)
        day_of_week = _parse_day_of_week(day_of_week)
        time_slot_id = _to_int(time_slot_id, 'Ca học', 1)
        min_capacity = _to_int(min_capacity, 'Sĩ số tối thiểu', 1, MAX_CLASS_CAPACITY)
        max_capacity = _to_int(max_capacity, 'Sĩ số tối đa', 1, MAX_CLASS_CAPACITY)
        if max_capacity < min_capacity:
            raise AdminValidationError(f'Sĩ số tối đa phải lớn hơn hoặc bằng sĩ số tối thiểu ({min_capacity}).')

        with Database.get_cursor() as cursor:
            if _fetch_one(cursor,
                          "/* q:class_by_code */ SELECT Id FROM dbo.Classes WITH (UPDLOCK, HOLDLOCK) WHERE ClassCode = ?",
                          (class_code,)):
                raise AdminConflictError(f"Mã lớp học phần '{class_code}' đã tồn tại.")

            course = _fetch_one(cursor,
                                "/* q:course_by_id */ SELECT Id, CourseCode, IsActive FROM dbo.Courses WHERE Id = ?",
                                (course_id,))
            if not course or not course.get('IsActive'):
                raise AdminValidationError('Môn học cơ sở không tồn tại.')

            if not _fetch_one(cursor, "/* q:semester_by_id */ SELECT Id, SemesterName FROM dbo.Semesters WHERE Id = ?",
                              (semester_id,)):
                raise AdminValidationError('Học kỳ không tồn tại.')

            slot = _fetch_one(cursor, "/* q:timeslot_by_id */ SELECT Id, SlotName FROM dbo.TimeSlots WHERE Id = ?",
                              (time_slot_id,))
            if not slot:
                raise AdminValidationError('Ca học không tồn tại.')

            lecturer = AdminClassModel._resolve_lecturer(cursor, lecturer_id, lecturer_ref)

            classroom = _fetch_one(
                cursor,
                "/* q:classroom_by_code */ SELECT Id, RoomCode, Capacity FROM dbo.Classrooms WHERE RoomCode = ?",
                (room,),
            )
            classroom_id = classroom['Id'] if classroom else None
            if classroom and max_capacity > classroom['Capacity']:
                raise AdminValidationError(
                    f"Sĩ số tối đa ({max_capacity}) vượt quá sức chứa phòng {room} ({classroom['Capacity']})."
                )

            # --- Kiem tra TRUNG PHONG HOC (cung hoc ky, cung thu, cung ca) ---
            room_conflict = _fetch_one(
                cursor,
                """/* q:room_conflict */
                SELECT TOP 1 ClassCode FROM dbo.Classes WITH (UPDLOCK, HOLDLOCK)
                WHERE SemesterId = ? AND DayOfWeek = ? AND TimeSlotId = ?
                  AND Status <> 'Cancelled'
                  AND (Room = ? OR (ClassroomId IS NOT NULL AND ClassroomId = ?))""",
                (semester_id, day_of_week, time_slot_id, room, classroom_id),
            )
            if room_conflict:
                raise AdminConflictError(
                    f"Trùng phòng học: phòng {room} đã được xếp cho lớp {room_conflict['ClassCode']} "
                    f"vào {DAY_NAMES[day_of_week]} - {slot['SlotName']}."
                )

            # --- Kiem tra TRUNG CA GIANG VIEN ---
            lecturer_conflict = _fetch_one(
                cursor,
                """/* q:lecturer_conflict */
                SELECT TOP 1 ClassCode FROM dbo.Classes WITH (UPDLOCK, HOLDLOCK)
                WHERE SemesterId = ? AND DayOfWeek = ? AND TimeSlotId = ?
                  AND Status <> 'Cancelled' AND LecturerId = ?""",
                (semester_id, day_of_week, time_slot_id, lecturer['Id']),
            )
            if lecturer_conflict:
                raise AdminConflictError(
                    f"Trùng lịch giảng viên: {lecturer['FullName']} đã dạy lớp {lecturer_conflict['ClassCode']} "
                    f"vào {DAY_NAMES[day_of_week]} - {slot['SlotName']}."
                )

            inserted = _fetch_one(
                cursor,
                """/* q:insert_class */
                INSERT INTO dbo.Classes (ClassCode, CourseId, SemesterId, LecturerId, ClassroomId, Room,
                                         TimeSlotId, DayOfWeek, MinCapacity, MaxCapacity,
                                         CurrentEnrollment, Status)
                OUTPUT INSERTED.Id
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'Open')""",
                (class_code, course_id, semester_id, lecturer['Id'], classroom_id, room,
                 time_slot_id, day_of_week, min_capacity, max_capacity),
            )

        return {'Id': inserted['Id'], 'ClassCode': class_code, 'CourseCode': course['CourseCode'],
                'LecturerId': lecturer['Id'], 'LecturerName': lecturer['FullName'], 'Room': room,
                'DayOfWeek': day_of_week, 'DayName': DAY_NAMES[day_of_week],
                'TimeSlotId': time_slot_id, 'MaxCapacity': max_capacity, 'Status': 'Open'}

    @staticmethod
    def cancel_class(class_id, admin_user_id=None):
        """
        NGHIEP VU HUY LOP HOC PHAN (< 15 SV) - thuc hien trong MOT transaction:
          1. Doi trang thai lop trong bang Classes sang 'Cancelled'.
          2. Chuyen toan bo ban ghi Enrollments 'Enrolled' cua lop sang 'Cancelled'.
          3. Ghi lich su 'AdminCancelClass' cho tung sinh vien bi anh huong.
          4. Tinh lai hoc phi cho tung sinh vien bi anh huong.
        Bat ky buoc nao loi -> rollback toan bo.
        """
        class_id = _to_int(class_id, 'Mã lớp học phần', 1)

        with Database.get_cursor() as cursor:
            course_class = _fetch_one(
                cursor,
                """/* q:class_for_cancel */
                SELECT Id, ClassCode, Status, CurrentEnrollment, MinCapacity, SemesterId
                FROM dbo.Classes WITH (UPDLOCK, ROWLOCK)
                WHERE Id = ?""",
                (class_id,),
            )
            if not course_class:
                raise AdminNotFoundError('Không tìm thấy lớp học phần.')
            if course_class['Status'] == 'Cancelled':
                raise AdminConflictError(f"Lớp {course_class['ClassCode']} đã bị hủy trước đó.")

            enrolled_rows = _fetch_all(
                cursor,
                """/* q:class_enrolled_students */
                SELECT StudentId FROM dbo.Enrollments WITH (UPDLOCK)
                WHERE ClassId = ? AND Status = 'Enrolled'""",
                (class_id,),
            )
            student_ids = [row['StudentId'] for row in enrolled_rows]
            # Lay so lon hon giua bien dem va so ban ghi thuc te de tranh huy nham lop du si so
            enrollment_count = max(course_class.get('CurrentEnrollment') or 0, len(student_ids))
            if enrollment_count >= MIN_CLASS_ENROLLMENT:
                raise AdminValidationError(
                    f"Không thể hủy lớp {course_class['ClassCode']}: sĩ số hiện tại là {enrollment_count} "
                    f"(chỉ được hủy lớp dưới {MIN_CLASS_ENROLLMENT} sinh viên)."
                )

            # Buoc 1: Huy lop
            _execute(
                cursor,
                """/* q:cancel_class */
                UPDATE dbo.Classes SET Status = 'Cancelled', CurrentEnrollment = 0
                WHERE Id = ?""",
                (class_id,),
            )
            # Buoc 2: Huy toan bo dang ky cua sinh vien trong lop
            _execute(
                cursor,
                """/* q:cancel_enrollments */
                UPDATE dbo.Enrollments SET Status = 'Cancelled', CancelledAt = SYSDATETIME()
                WHERE ClassId = ? AND Status = 'Enrolled'""",
                (class_id,),
            )
            # Buoc 3 + 4: Lich su & hoc phi
            for student_id in student_ids:
                _execute(
                    cursor,
                    """/* q:insert_history */
                    INSERT INTO dbo.RegistrationHistory (StudentId, ClassId, ActionType, PerformedByUserId, Note)
                    VALUES (?, ?, ?, ?, ?)""",
                    (student_id, class_id, 'AdminCancelClass', admin_user_id,
                     f'Cancelled due to under-enrollment (< {MIN_CLASS_ENROLLMENT} students)'),
                )
            for student_id in student_ids:
                _execute(
                    cursor,
                    "/* q:recalc_tuition */ EXEC dbo.sp_RecalculateStudentTuition @StudentId = ?, @SemesterId = ?",
                    (student_id, course_class['SemesterId']),
                )

        return {'Id': class_id, 'ClassCode': course_class['ClassCode'], 'Status': 'Cancelled',
                'AffectedStudents': len(student_ids), 'PreviousEnrollment': enrollment_count}


# ==========================================================================
# 5. CAU HINH DOT DANG KY (Semesters / RegistrationPeriods)
# ==========================================================================
class AdminPeriodModel:

    @staticmethod
    def list_semesters():
        return Database.query_all(
            """/* q:list_semesters */
            SELECT Id, SemesterCode, SemesterName, AcademicYear, StartDate, EndDate,
                   CreditUnitPrice, IsCurrent
            FROM dbo.Semesters
            ORDER BY IsCurrent DESC, StartDate DESC"""
        )

    @staticmethod
    def get_current_semester_id():
        row = Database.query_one(
            "/* q:current_semester */ SELECT TOP 1 Id FROM dbo.Semesters ORDER BY IsCurrent DESC, StartDate DESC"
        )
        return row['Id'] if row else None

    @staticmethod
    def list_periods(semester_id=None):
        sql = """/* q:list_periods */
            SELECT rp.Id, rp.SemesterId, s.SemesterCode, s.SemesterName, rp.PeriodName,
                   rp.StartDate, rp.EndDate, rp.MinCredits, rp.MaxCredits, rp.IsActive
            FROM dbo.RegistrationPeriods rp
            INNER JOIN dbo.Semesters s ON s.Id = rp.SemesterId"""
        params = None
        if semester_id:
            sql += " WHERE rp.SemesterId = ?"
            params = (_to_int(semester_id, 'Học kỳ', 1),)
        sql += " ORDER BY rp.Id DESC"
        periods = Database.query_all(sql, params)
        now = datetime.now()
        for period in periods:
            period['WindowStatus'] = _period_status(period, now)
        return periods

    @staticmethod
    def get_active_period(semester_id):
        semester_id = _to_int(semester_id, 'Học kỳ', 1)
        period = Database.query_one(
            """/* q:active_period */
            SELECT TOP 1 rp.Id, rp.SemesterId, s.SemesterCode, s.SemesterName, rp.PeriodName,
                   rp.StartDate, rp.EndDate, rp.MinCredits, rp.MaxCredits, rp.IsActive
            FROM dbo.RegistrationPeriods rp
            INNER JOIN dbo.Semesters s ON s.Id = rp.SemesterId
            WHERE rp.SemesterId = ? AND rp.IsActive = 1
            ORDER BY rp.Id DESC""",
            (semester_id,),
        )
        if period:
            period['WindowStatus'] = _period_status(period)
        return period

    @staticmethod
    def save_period(semester_id, start_date, end_date, period_name=None,
                    min_credits=DEFAULT_MIN_CREDITS, max_credits=DEFAULT_MAX_CREDITS):
        """
        Thiet lap dot dang ky moi cho hoc ky: vo hieu hoa dot cu (giu lai lam lich su)
        va tao dot moi o trang thai Active.
        """
        semester_id = _to_int(semester_id, 'Học kỳ', 1)
        start = _parse_datetime(start_date, 'Ngày bắt đầu')
        end = _parse_datetime(end_date, 'Ngày kết thúc')
        if end <= start:
            raise AdminValidationError('Ngày kết thúc phải sau ngày bắt đầu.')
        min_credits = _to_int(min_credits if min_credits is not None else DEFAULT_MIN_CREDITS,
                              'Số tín chỉ tối thiểu', 0, 50)
        max_credits = _to_int(max_credits if max_credits is not None else DEFAULT_MAX_CREDITS,
                              'Số tín chỉ tối đa', 12, 50)
        if max_credits < min_credits:
            raise AdminValidationError('Số tín chỉ tối đa phải lớn hơn hoặc bằng số tín chỉ tối thiểu.')
        period_name = _optional_text(period_name, 'Tên đợt đăng ký', 150)

        with Database.get_cursor() as cursor:
            semester = _fetch_one(
                cursor,
                "/* q:semester_by_id */ SELECT Id, SemesterName FROM dbo.Semesters WHERE Id = ?",
                (semester_id,),
            )
            if not semester:
                raise AdminNotFoundError('Học kỳ không tồn tại.')
            period_name = period_name or f"Course Registration Period - {semester['SemesterName']}"

            _execute(
                cursor,
                "/* q:deactivate_periods */ UPDATE dbo.RegistrationPeriods SET IsActive = 0 WHERE SemesterId = ? AND IsActive = 1",
                (semester_id,),
            )
            inserted = _fetch_one(
                cursor,
                """/* q:insert_period */
                INSERT INTO dbo.RegistrationPeriods (SemesterId, PeriodName, StartDate, EndDate,
                                                     MinCredits, MaxCredits, IsActive)
                OUTPUT INSERTED.Id
                VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (semester_id, period_name, start, end, min_credits, max_credits),
            )

        result = {'Id': inserted['Id'], 'SemesterId': semester_id, 'PeriodName': period_name,
                  'StartDate': start, 'EndDate': end, 'MinCredits': min_credits,
                  'MaxCredits': max_credits, 'IsActive': True}
        result['WindowStatus'] = _period_status(result)
        return result

    @staticmethod
    def set_period_active(period_id, is_active):
        """Mo / dong mot dot dang ky. Moi hoc ky chi co toi da 1 dot Active."""
        period_id = _to_int(period_id, 'Mã đợt đăng ký', 1)
        is_active = bool(is_active) if not isinstance(is_active, str) \
            else is_active.strip().lower() in ('1', 'true', 'yes', 'on')

        with Database.get_cursor() as cursor:
            period = _fetch_one(
                cursor,
                "/* q:period_by_id */ SELECT Id, SemesterId, IsActive FROM dbo.RegistrationPeriods WITH (UPDLOCK) WHERE Id = ?",
                (period_id,),
            )
            if not period:
                raise AdminNotFoundError('Không tìm thấy đợt đăng ký.')
            if is_active:
                _execute(
                    cursor,
                    "/* q:deactivate_periods */ UPDATE dbo.RegistrationPeriods SET IsActive = 0 WHERE SemesterId = ? AND IsActive = 1",
                    (period['SemesterId'],),
                )
            _execute(
                cursor,
                "/* q:set_period_active */ UPDATE dbo.RegistrationPeriods SET IsActive = ? WHERE Id = ?",
                (1 if is_active else 0, period_id),
            )
        return {'Id': period_id, 'SemesterId': period['SemesterId'], 'IsActive': is_active}


# ==========================================================================
# 6. BAO CAO THONG KE
# ==========================================================================
class AdminReportModel:

    @staticmethod
    def section_report(semester_id):
        """Ty le lap day theo tung lop hoc phan."""
        sections = AdminClassModel.list_classes(semester_id)
        for item in sections:
            max_cap = item.get('MaxCapacity') or 0
            current = item.get('CurrentEnrollment') or 0
            item['FillRate'] = round(current * 100.0 / max_cap, 1) if max_cap else 0.0
        return sections

    @staticmethod
    def student_report(semester_id):
        """Danh sach lop da dang ky va tong tin chi cua tung sinh vien trong hoc ky."""
        semester_id = _to_int(semester_id, 'Học kỳ', 1)
        rows = Database.query_all(
            """/* q:student_report */
            SELECT u.Id AS StudentId, u.UserCode, u.FullName, s.StudentCode, s.Major,
                   s.AdministrativeClass, cl.ClassCode, co.CourseCode, co.Credits
            FROM dbo.Students s
            INNER JOIN dbo.Users u ON u.Id = s.UserId
            LEFT JOIN dbo.Enrollments e ON e.StudentId = u.Id AND e.Status = 'Enrolled'
            LEFT JOIN dbo.Classes cl ON cl.Id = e.ClassId AND cl.SemesterId = ? AND cl.Status <> 'Cancelled'
            LEFT JOIN dbo.Courses co ON co.Id = cl.CourseId
            ORDER BY u.UserCode, cl.ClassCode""",
            (semester_id,),
        )

        period = AdminPeriodModel.get_active_period(semester_id)
        min_credits = period['MinCredits'] if period else DEFAULT_MIN_CREDITS
        max_credits = period['MaxCredits'] if period else DEFAULT_MAX_CREDITS

        students = {}
        for row in rows:
            student = students.setdefault(row['StudentId'], {
                'StudentId': row['StudentId'],
                'StudentCode': row.get('StudentCode') or row.get('UserCode'),
                'FullName': row['FullName'],
                'Major': row.get('Major'),
                'AdministrativeClass': row.get('AdministrativeClass'),
                'Classes': [],
                'CourseCount': 0,
                'TotalCredits': 0,
            })
            if row.get('ClassCode'):
                student['Classes'].append(row['ClassCode'])
                student['CourseCount'] += 1
                student['TotalCredits'] += row.get('Credits') or 0

        result = []
        for student in students.values():
            total = student['TotalCredits']
            if total == 0:
                compliance = 'No Registration'
            elif total < min_credits:
                compliance = 'Below Minimum'
            elif total > max_credits:
                compliance = 'Over Limit'
            else:
                compliance = 'Compliant'
            student['Compliance'] = compliance
            student['MinCredits'] = min_credits
            student['MaxCredits'] = max_credits
            result.append(student)
        return result

    @staticmethod
    def full_report(semester_id):
        sections = AdminReportModel.section_report(semester_id)
        students = AdminReportModel.student_report(semester_id)

        active_sections = [s for s in sections if s.get('Status') != 'Cancelled']
        registered_students = [s for s in students if s['TotalCredits'] > 0]
        summary = {
            'TotalSections': len(active_sections),
            'CancelledSections': len(sections) - len(active_sections),
            'TotalEnrollments': sum(_to_number(s.get('CurrentEnrollment')) for s in active_sections),
            'AverageFillRate': round(sum(s['FillRate'] for s in active_sections) / len(active_sections), 1)
            if active_sections else 0.0,
            'AverageCredits': round(sum(s['TotalCredits'] for s in registered_students) / len(registered_students), 1)
            if registered_students else 0.0,
            'RegisteredStudents': len(registered_students),
        }
        return {'SemesterId': semester_id, 'Summary': summary, 'Sections': sections, 'Students': students}


# ==========================================================================
# 7. DU LIEU TRA CUU CHO FORM
# ==========================================================================
class AdminLookupModel:

    @staticmethod
    def list_timeslots():
        return Database.query_all(
            "/* q:list_timeslots */ SELECT Id, SlotNumber, SlotName, StartTime, EndTime FROM dbo.TimeSlots ORDER BY SlotNumber"
        )

    @staticmethod
    def list_lecturers():
        return Database.query_all(
            """/* q:list_lecturers */
            SELECT u.Id, u.UserCode, u.FullName, u.Email, u.Status, l.Department, l.AcademicDegree
            FROM dbo.Users u
            INNER JOIN dbo.Lecturers l ON l.UserId = u.Id
            WHERE u.Role = 'Lecturer'
            ORDER BY u.UserCode"""
        )

    @staticmethod
    def list_classrooms():
        return Database.query_all(
            "/* q:list_classrooms */ SELECT Id, RoomCode, Building, Capacity, RoomType FROM dbo.Classrooms ORDER BY RoomCode"
        )
