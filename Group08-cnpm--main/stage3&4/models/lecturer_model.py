"""
models/lecturer_model.py
========================
Tang du lieu (Model) cho PHAN HE GIANG VIEN (Lecturer).

Chuc nang:
    1. LecturerProfileModel  - Thong tin ca nhan + doi mat khau.
    2. LecturerClassModel    - Danh sach lop hoc phan duoc phan cong (kem si so THUC TE),
                               danh sach sinh vien theo lop, thong ke tai giang day.
    3. LecturerScheduleModel - Lich giang day theo tuan (dua tren ngay bat dau hoc ky).
    4. LecturerExportModel   - Tao noi dung file CSV (UTF-8) danh sach sinh vien cua lop.

Du lieu dua tren schema cua init_database.sql (TV1):
    Users, Lecturers, Semesters, Courses, Classes, Classrooms, TimeSlots, Enrollments, Students.
    - Classes.LecturerId tro toi Users.Id cua giang vien.
    - Si so thuc te = so ban ghi Enrollments co Status = 'Enrolled' (khong tin hoan toan
      vao cot Classes.CurrentEnrollment, de bao cao luon khop voi danh sach chi tiet).

Moi truy van dung tham so '?' (chong SQL Injection) qua models/db.py.
Moi cau SQL co comment /* q:ten_truy_van */ de Unit Test (tests/test_lecturer.py) nhan dien,
comment nay khong anh huong toi SQL Server (cung quy uoc voi models/admin_model.py).
"""

import csv
import io
import math
from datetime import date, datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

from models.db import Database


# ==========================================================================
# HANG SO
# ==========================================================================
MIN_PASSWORD_LENGTH = 6
DAY_NAMES = {
    2: 'Monday', 3: 'Tuesday', 4: 'Wednesday', 5: 'Thursday',
    6: 'Friday', 7: 'Saturday', 8: 'Sunday',
}

CSV_HEADERS = [
    'STT', 'MSSV', 'Họ và tên', 'Lớp', 'Ngành',
    'Email', 'Số điện thoại', 'Ngày đăng ký', 'Trạng thái',
]
# Ky tu dau o co the bi Excel hieu nham thanh cong thuc (CSV injection)
_CSV_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


# ==========================================================================
# EXCEPTIONS - Controller dua vao status_code de tra ve HTTP code tuong ung
# ==========================================================================
class LecturerError(Exception):
    """Loi nghiep vu chung cua phan he Giang vien."""
    status_code = 400

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class LecturerValidationError(LecturerError):
    """Du lieu dau vao khong hop le (HTTP 400)."""
    status_code = 400


class LecturerPermissionError(LecturerError):
    """Giang vien truy cap lop khong duoc phan cong cho minh (HTTP 403)."""
    status_code = 403


class LecturerNotFoundError(LecturerError):
    """Khong tim thay ban ghi (HTTP 404)."""
    status_code = 404


# ==========================================================================
# HAM TRO GIUP
# ==========================================================================
def _to_date(value):
    """Chuyen date/datetime/chuoi ISO ve datetime.date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()


def _fmt_time(value):
    """Chuyen time/chuoi ve 'HH:MM'."""
    if hasattr(value, 'strftime'):
        return value.strftime('%H:%M')
    return str(value)[:5]


def _fmt_datetime(value):
    if value is None:
        return ''
    if hasattr(value, 'strftime'):
        return value.strftime('%d/%m/%Y %H:%M')
    return str(value)


def _csv_safe(value):
    """Chong CSV/Excel formula injection: them dau ' truoc o bat dau bang = + - @."""
    if value is None:
        return ''
    text = str(value)
    if text.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + text
    return text


def _decorate_class(row):
    """Bo sung ten thu/ca hoc/si so cho 1 dong lop hoc phan."""
    item = dict(row)
    item['DayName'] = DAY_NAMES.get(item.get('DayOfWeek'), '')
    item['TimeRange'] = f"{_fmt_time(item.get('StartTime'))} - {_fmt_time(item.get('EndTime'))}"
    item['Room'] = item.get('RoomCode') or item.get('Room') or ''
    return item


# ==========================================================================
# 1. HO SO & DOI MAT KHAU
# ==========================================================================
class LecturerProfileModel:

    @staticmethod
    def get_profile(user_id):
        row = Database.query_one(
            """
            /* q:lecturer_profile */
            SELECT u.Id, u.UserCode, u.Username, u.FullName, u.Email, u.Phone,
                   u.Role, u.Status, l.LecturerCode, l.Department, l.AcademicDegree
            FROM dbo.Users u
            INNER JOIN dbo.Lecturers l ON l.UserId = u.Id
            WHERE u.Id = ?
            """,
            (user_id,),
        )
        if not row:
            raise LecturerNotFoundError('Không tìm thấy hồ sơ giảng viên.', 404)
        row.pop('PasswordHash', None)
        return row

    @staticmethod
    def change_password(user_id, current_password, new_password, confirm_password):
        """Doi mat khau: kiem tra mat khau cu, do dai, xac nhan, khac mat khau cu."""
        if not current_password or not new_password or not confirm_password:
            raise LecturerValidationError('Vui lòng nhập đầy đủ các trường mật khẩu.')
        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise LecturerValidationError(
                f'Mật khẩu mới phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự.')
        if new_password != confirm_password:
            raise LecturerValidationError('Mật khẩu xác nhận không khớp.')
        if new_password == current_password:
            raise LecturerValidationError('Mật khẩu mới phải khác mật khẩu hiện tại.')

        user = Database.query_one(
            "/* q:lecturer_password_hash */ SELECT Id, PasswordHash FROM dbo.Users WHERE Id = ?",
            (user_id,),
        )
        if not user:
            raise LecturerNotFoundError('Không tìm thấy tài khoản.', 404)
        if not check_password_hash(user['PasswordHash'], current_password):
            raise LecturerValidationError('Mật khẩu hiện tại không chính xác.')

        Database.execute(
            "/* q:lecturer_update_password */ "
            "UPDATE dbo.Users SET PasswordHash = ?, UpdatedAt = SYSDATETIME() WHERE Id = ?",
            (generate_password_hash(new_password), user_id),
        )
        return True


# ==========================================================================
# 2. LOP HOC PHAN & DANH SACH SINH VIEN
# ==========================================================================
class LecturerClassModel:

    @staticmethod
    def list_semesters():
        return Database.query_all(
            """
            /* q:lecturer_semesters */
            SELECT Id, SemesterCode, SemesterName, AcademicYear, StartDate, EndDate, IsCurrent
            FROM dbo.Semesters
            ORDER BY StartDate DESC
            """
        )

    @staticmethod
    def get_semester(semester_id):
        return Database.query_one(
            """
            /* q:lecturer_semester_by_id */
            SELECT Id, SemesterCode, SemesterName, AcademicYear, StartDate, EndDate, IsCurrent
            FROM dbo.Semesters WHERE Id = ?
            """,
            (semester_id,),
        )

    @staticmethod
    def get_current_semester_id():
        row = Database.query_one(
            """
            /* q:lecturer_current_semester */
            SELECT TOP 1 Id FROM dbo.Semesters
            ORDER BY IsCurrent DESC, StartDate DESC
            """
        )
        return row['Id'] if row else None

    @staticmethod
    def list_assigned_classes(lecturer_id, semester_id):
        """
        Cac lop hoc phan GV duoc phan cong trong hoc ky, kem si so thuc te
        (dem Enrollments 'Enrolled'). Lop da huy van hien thi voi Status='Cancelled'.
        """
        rows = Database.query_all(
            """
            /* q:lecturer_assigned_classes */
            SELECT cl.Id, cl.ClassCode, cl.CourseId, cl.SemesterId, cl.DayOfWeek, cl.TimeSlotId,
                   cl.Room AS Room, cr.RoomCode, cl.MinCapacity, cl.MaxCapacity,
                   cl.Status AS ClassStatus,
                   co.CourseCode, co.CourseName, co.Credits,
                   pre.CourseCode AS PrerequisiteCode, pre.CourseName AS PrerequisiteName,
                   ts.SlotName, ts.StartTime, ts.EndTime,
                   (SELECT COUNT(*) FROM dbo.Enrollments e
                     WHERE e.ClassId = cl.Id AND e.Status = 'Enrolled') AS EnrolledCount
            FROM dbo.Classes cl
            INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
            LEFT JOIN dbo.Courses pre ON pre.Id = co.PrerequisiteCourseId
            INNER JOIN dbo.TimeSlots ts ON ts.Id = cl.TimeSlotId
            LEFT JOIN dbo.Classrooms cr ON cr.Id = cl.ClassroomId
            WHERE cl.LecturerId = ? AND cl.SemesterId = ?
            ORDER BY cl.DayOfWeek, ts.SlotNumber, cl.ClassCode
            """,
            (lecturer_id, semester_id),
        )
        return [_decorate_class(r) for r in rows]

    @staticmethod
    def summarize(classes):
        """Thong ke tai giang day (bo qua lop da huy)."""
        active = [c for c in classes if c.get('ClassStatus') != 'Cancelled']
        return {
            'total_sections': len(active),
            'total_credits': sum(int(c['Credits']) for c in active),
            'total_students': sum(int(c['EnrolledCount']) for c in active),
            'distinct_courses': len({c['CourseId'] for c in active}),
            'teaching_days': len({c['DayOfWeek'] for c in active}),
        }

    @staticmethod
    def get_owned_class(lecturer_id, class_id):
        """Lay lop hoc phan va dam bao no thuoc ve giang vien dang dang nhap."""
        row = Database.query_one(
            """
            /* q:lecturer_class_by_id */
            SELECT cl.Id, cl.ClassCode, cl.LecturerId, cl.SemesterId, cl.Status AS ClassStatus,
                   co.CourseCode, co.CourseName, co.Credits
            FROM dbo.Classes cl
            INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
            WHERE cl.Id = ?
            """,
            (class_id,),
        )
        if not row:
            raise LecturerNotFoundError('Không tìm thấy lớp học phần.', 404)
        if row['LecturerId'] != lecturer_id:
            raise LecturerPermissionError('Bạn không được phân công giảng dạy lớp học phần này.', 403)
        return row

    @staticmethod
    def list_students(lecturer_id, class_id):
        """Danh sach SV dang ky thanh cong (Enrolled/Completed) cua lop: MSSV, ho ten, lop, ngay dang ky."""
        cls = LecturerClassModel.get_owned_class(lecturer_id, class_id)
        rows = Database.query_all(
            """
            /* q:lecturer_class_students */
            SELECT u.Id AS UserId, s.StudentCode, u.FullName, s.AdministrativeClass, s.Major,
                   u.Email, u.Phone, e.EnrolledAt, e.Status AS EnrollmentStatus
            FROM dbo.Enrollments e
            INNER JOIN dbo.Users u ON u.Id = e.StudentId
            INNER JOIN dbo.Students s ON s.UserId = u.Id
            WHERE e.ClassId = ? AND e.Status IN ('Enrolled', 'Completed')
            ORDER BY s.StudentCode
            """,
            (class_id,),
        )
        return cls, rows


# ==========================================================================
# 3. LICH GIANG DAY THEO TUAN
# ==========================================================================
class LecturerScheduleModel:

    @staticmethod
    def list_time_slots():
        return Database.query_all(
            """
            /* q:lecturer_timeslots */
            SELECT Id, SlotNumber, SlotName, StartTime, EndTime
            FROM dbo.TimeSlots ORDER BY SlotNumber
            """
        )

    @staticmethod
    def week_info(semester, week=None, today=None):
        """
        Tinh thong tin tuan hoc. Tuan 1 bat dau vao thu Hai cua tuan chua ngay bat dau hoc ky.
        Neu week=None thi lay tuan hien tai (gioi han trong [1, tong so tuan]).
        """
        start = _to_date(semester['StartDate'])
        end = _to_date(semester['EndDate'])
        first_monday = start - timedelta(days=start.weekday())
        total_weeks = max(1, math.ceil(((end - first_monday).days + 1) / 7))

        if week is None:
            today = today or date.today()
            week = ((today - first_monday).days // 7) + 1
        try:
            week = int(week)
        except (TypeError, ValueError):
            raise LecturerValidationError('Số tuần không hợp lệ.')
        week = min(max(week, 1), total_weeks)

        week_start = first_monday + timedelta(days=7 * (week - 1))
        return {
            'week': week,
            'total_weeks': total_weeks,
            'week_start': week_start,
            'week_end': week_start + timedelta(days=6),
            'semester_start': start,
            'semester_end': end,
        }

    @staticmethod
    def build_weekly_schedule(lecturer_id, semester_id, week=None, today=None):
        semester = LecturerClassModel.get_semester(semester_id)
        if not semester:
            raise LecturerNotFoundError('Không tìm thấy học kỳ.', 404)

        info = LecturerScheduleModel.week_info(semester, week, today)
        classes = LecturerClassModel.list_assigned_classes(lecturer_id, semester_id)

        sessions = []
        for c in classes:
            if c['ClassStatus'] == 'Cancelled':
                continue  # Lop da huy khong con lich day
            session_date = info['week_start'] + timedelta(days=c['DayOfWeek'] - 2)
            if not (info['semester_start'] <= session_date <= info['semester_end']):
                continue  # Buoi hoc nam ngoai thoi gian hoc ky
            item = dict(c)
            item['SessionDate'] = session_date
            sessions.append(item)

        days = [
            {'day': d, 'name': DAY_NAMES[d], 'date': info['week_start'] + timedelta(days=d - 2)}
            for d in range(2, 9)
        ]
        return {
            'semester': semester,
            'week': info,
            'days': days,
            'slots': LecturerScheduleModel.list_time_slots(),
            'sessions': sessions,
            'summary': LecturerClassModel.summarize(classes),
        }


# ==========================================================================
# 4. XUAT CSV
# ==========================================================================
class LecturerExportModel:

    @staticmethod
    def build_students_csv(lecturer_id, class_id):
        """
        Tra ve (ten_file, noi_dung_csv). Noi dung la str; controller ma hoa UTF-8 co BOM
        (utf-8-sig) de Excel hien thi dung tieng Viet. Lop chua co SV -> chi co dong tieu de.
        """
        cls, students = LecturerClassModel.list_students(lecturer_id, class_id)

        buffer = io.StringIO(newline='')
        writer = csv.writer(buffer, lineterminator='\r\n')
        writer.writerow(CSV_HEADERS)
        for index, s in enumerate(students, start=1):
            writer.writerow([
                index,
                _csv_safe(s['StudentCode']),
                _csv_safe(s['FullName']),
                _csv_safe(s['AdministrativeClass']),
                _csv_safe(s['Major']),
                _csv_safe(s['Email']),
                _csv_safe(s['Phone']),
                _fmt_datetime(s['EnrolledAt']),
                _csv_safe(s['EnrollmentStatus']),
            ])
        filename = f"students_{cls['ClassCode']}.csv"
        return filename, buffer.getvalue()
