"""
models/student_model.py
=======================
Tầng dữ liệu (Model) cho PHÂN HỆ SINH VIÊN (Student Portal).
Hệ thống Đăng ký Môn học (Course Registration System).

Chức năng chính:
    1. StudentProfileModel     - Hồ sơ sinh viên, thông tin tài khoản & đổi mật khẩu.
    2. StudentLookupModel      - Danh mục học kỳ, ca học, đợt đăng ký môn học.
    3. StudentCourseModel      - Danh mục các lớp học phần đang mở trong đợt đăng ký,
                                 lớp đã đăng ký, kiểm tra điều kiện đăng ký.
    4. StudentRegistrationModel- Thuật toán Đăng ký môn học (kiểm tra 4 điều kiện nghiêm ngặt),
                                 Hủy đăng ký môn học (giảm sĩ số, cập nhật Cancelled),
                                 ghi nhận nhật ký giao dịch (RegistrationHistory).
    5. StudentScheduleModel    - Lịch học / Thời khóa biểu tuần của sinh viên.
    6. StudentTuitionModel     - Bảng kê học phí tự động dựa trên tín chỉ đăng ký & đơn giá.
    7. StudentHistoryModel     - Lịch sử đăng ký / hủy môn học (Audit Log).

Quy ước:
    - Mọi truy vấn dùng tham số '?' chống SQL Injection qua models/db.py.
    - Các thao tác ghi nhiều bảng (đăng ký, hủy môn) được bọc trong một transaction
      bằng `Database.get_cursor()`.
    - Mỗi câu truy vấn có comment /* q:ten_truy_van */ để nhận diện và hỗ trợ Unit Test.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
import math
import re
from werkzeug.security import check_password_hash, generate_password_hash

from models.db import Database


# ==========================================================================
# HẰNG SỐ NGHIEP VỤ
# ==========================================================================
DEFAULT_MIN_CREDITS = 12
DEFAULT_MAX_CREDITS = 25
DEFAULT_CREDIT_PRICE = 550000.00
MIN_PASSWORD_LENGTH = 6

DAY_NAMES = {
    2: 'Monday', 3: 'Tuesday', 4: 'Wednesday', 5: 'Thursday',
    6: 'Friday', 7: 'Saturday', 8: 'Sunday',
}

DAY_NAMES_VI = {
    2: 'Thứ Hai', 3: 'Thứ Ba', 4: 'Thứ Tư', 5: 'Thứ Năm',
    6: 'Thứ Sáu', 7: 'Thứ Bảy', 8: 'Chủ Nhật',
}


# ==========================================================================
# EXCEPTIONS NGHIEP VU
# ==========================================================================
class StudentError(Exception):
    """Lỗi nghiệp vụ cơ sở của phân hệ Sinh viên."""
    status_code = 400

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class StudentValidationError(StudentError):
    """Dữ liệu đầu vào hoặc điều kiện tiên quyết không hợp lệ (HTTP 400)."""
    status_code = 400


class StudentNotFoundError(StudentError):
    """Không tìm thấy bản ghi (HTTP 404)."""
    status_code = 404


class StudentConflictError(StudentError):
    """Trùng lịch học, đầy lớp hoặc trùng đăng ký (HTTP 409)."""
    status_code = 409


class StudentPermissionError(StudentError):
    """Không có quyền thao tác (HTTP 403)."""
    status_code = 403


# ==========================================================================
# HÀM TRỢ GIÚP DÙNG CHUNG
# ==========================================================================
def _to_date(value):
    """Chuyển date/datetime/chuỗi ISO về datetime.date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return date.today()
    return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()


def _fmt_time(value):
    """Chuyển time/chuỗi về 'HH:MM'."""
    if hasattr(value, 'strftime'):
        return value.strftime('%H:%M')
    return str(value)[:5] if value else ''


def _fmt_datetime(value):
    """Chuyển datetime/chuỗi về định dạng hiển thị 'YYYY-MM-DD HH:MM:SS'."""
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    return str(value) if value else ''


def _clean_str(value):
    return str(value).strip() if value is not None else ''


def _execute(cursor, sql, params=None):
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)


def _fetch_one(cursor, sql, params=None):
    """Chạy SELECT trong transaction hiện tại và trả về 1 dict (hoặc None)."""
    _execute(cursor, sql, params)
    if not cursor.description:
        return None
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


def _fetch_all(cursor, sql, params=None):
    """Chạy SELECT trong transaction hiện tại và trả về danh sách dict."""
    _execute(cursor, sql, params)
    if not cursor.description:
        return []
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# ==========================================================================
# 1. TRA CỨU HỌC KỲ, CA HỌC, ĐỢT ĐĂNG KÝ (StudentLookupModel)
# ==========================================================================
class StudentLookupModel:
    @staticmethod
    def get_semesters():
        """Danh sách tất cả các học kỳ trong hệ thống."""
        return Database.query_all(
            """
            /* q:student_lookup_semesters */
            SELECT Id, SemesterCode, SemesterName, AcademicYear, StartDate, EndDate,
                   CreditUnitPrice, IsCurrent
            FROM dbo.Semesters
            ORDER BY StartDate DESC
            """
        )

    @staticmethod
    def get_current_semester():
        """Lấy học kỳ hiện hành (IsCurrent = 1 hoặc học kỳ mới nhất)."""
        row = Database.query_one(
            """
            /* q:student_lookup_current_semester */
            SELECT Id, SemesterCode, SemesterName, AcademicYear, StartDate, EndDate,
                   CreditUnitPrice, IsCurrent
            FROM dbo.Semesters
            WHERE IsCurrent = 1
            """
        )
        if not row:
            row = Database.query_one(
                """
                /* q:student_lookup_latest_semester */
                SELECT TOP 1 Id, SemesterCode, SemesterName, AcademicYear, StartDate, EndDate,
                             CreditUnitPrice, IsCurrent
                FROM dbo.Semesters
                ORDER BY StartDate DESC
                """
            )
        return row

    @staticmethod
    def get_semester_by_id(semester_id):
        """Lấy thông tin học kỳ theo Id."""
        return Database.query_one(
            """
            /* q:student_lookup_semester_by_id */
            SELECT Id, SemesterCode, SemesterName, AcademicYear, StartDate, EndDate,
                   CreditUnitPrice, IsCurrent
            FROM dbo.Semesters
            WHERE Id = ?
            """,
            (semester_id,),
        )

    @staticmethod
    def get_active_registration_period(semester_id):
        """Lấy đợt đăng ký đang hoạt động của học kỳ."""
        return Database.query_one(
            """
            /* q:student_lookup_active_period */
            SELECT Id, SemesterId, PeriodName, StartDate, EndDate, MinCredits, MaxCredits, IsActive
            FROM dbo.RegistrationPeriods
            WHERE SemesterId = ? AND IsActive = 1
            ORDER BY EndDate DESC
            """,
            (semester_id,),
        )

    @staticmethod
    def is_registration_open(semester_id):
        """Kiểm tra thời gian mở cổng đăng ký môn học."""
        period = StudentLookupModel.get_active_registration_period(semester_id)
        if not period:
            return False, None, "Học kỳ này hiện không có đợt đăng ký môn học nào đang mở."
        now = datetime.now()
        start = period['StartDate'] if isinstance(period['StartDate'], datetime) else datetime.fromisoformat(str(period['StartDate'])[:19])
        end = period['EndDate'] if isinstance(period['EndDate'], datetime) else datetime.fromisoformat(str(period['EndDate'])[:19])
        if now < start:
            return False, period, f"Đợt đăng ký '{period['PeriodName']}' chưa bắt đầu (Mở lúc: {_fmt_datetime(start)})."
        if now > end:
            return False, period, f"Đợt đăng ký '{period['PeriodName']}' đã kết thúc (Đóng lúc: {_fmt_datetime(end)})."
        return True, period, "Cổng đăng ký môn học đang mở."

    @staticmethod
    def get_time_slots():
        """Danh sách ca học."""
        return Database.query_all(
            """
            /* q:student_lookup_timeslots */
            SELECT Id, SlotNumber, SlotName, StartTime, EndTime
            FROM dbo.TimeSlots
            ORDER BY SlotNumber ASC
            """
        )


# ==========================================================================
# 2. HỒ SƠ & TÀI KHOẢN SINH VIÊN (StudentProfileModel)
# ==========================================================================
class StudentProfileModel:
    @staticmethod
    def get_profile(student_id):
        """Lấy thông tin cá nhân của sinh viên."""
        row = Database.query_one(
            """
            /* q:student_profile */
            SELECT u.Id, u.UserCode, u.Username, u.FullName, u.Email, u.Phone,
                   u.Role, u.Status, s.StudentCode, s.AdministrativeClass,
                   s.Major, s.Faculty, s.EnrollmentYear
            FROM dbo.Users u
            INNER JOIN dbo.Students s ON s.UserId = u.Id
            WHERE u.Id = ?
            """,
            (student_id,),
        )
        if not row:
            raise StudentNotFoundError("Không tìm thấy thông tin sinh viên.", 404)
        return row

    @staticmethod
    def change_password(student_id, current_password, new_password, confirm_password):
        """Đổi mật khẩu sinh viên."""
        if not current_password or not new_password or not confirm_password:
            raise StudentValidationError("Vui lòng điền đầy đủ thông tin mật khẩu.")
        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise StudentValidationError(f"Mật khẩu mới phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự.")
        if new_password != confirm_password:
            raise StudentValidationError("Mật khẩu xác nhận không khớp.")
        if new_password == current_password:
            raise StudentValidationError("Mật khẩu mới phải khác mật khẩu hiện tại.")

        user = Database.query_one(
            "/* q:student_check_password */ SELECT Id, PasswordHash FROM dbo.Users WHERE Id = ?",
            (student_id,),
        )
        if not user:
            raise StudentNotFoundError("Tài khoản sinh viên không tồn tại.", 404)

        stored = user['PasswordHash']
        # Hỗ trợ cả werkzeug hash (scrypt/pbkdf2) và SHA256 fallback
        valid = False
        try:
            valid = check_password_hash(stored, current_password)
        except Exception:
            import hashlib
            valid = (stored == hashlib.sha256(current_password.encode()).hexdigest())

        if not valid:
            raise StudentValidationError("Mật khẩu hiện tại không chính xác.")

        new_hash = generate_password_hash(new_password)
        Database.execute(
            "/* q:student_update_password */ UPDATE dbo.Users SET PasswordHash = ?, UpdatedAt = SYSDATETIME() WHERE Id = ?",
            (new_hash, student_id),
        )
        return True


# ==========================================================================
# 3. DANH MỤC LỚP HỌC PHẦN & ĐIỀU KIỆN TIÊN QUYẾT (StudentCourseModel)
# ==========================================================================
class StudentCourseModel:
    @staticmethod
    def get_registered_classes(student_id, semester_id):
        """Danh sách các lớp học phần sinh viên đã đăng ký trong học kỳ (Status = 'Enrolled')."""
        rows = Database.query_all(
            """
            /* q:student_enrolled_classes */
            SELECT e.Id AS EnrollmentId, e.StudentId, e.ClassId, e.EnrolledAt, e.Status AS EnrollmentStatus,
                   cl.ClassCode, cl.SemesterId, cl.DayOfWeek, cl.TimeSlotId, cl.Room,
                   cl.CurrentEnrollment, cl.MaxCapacity, cl.Status AS ClassStatus,
                   co.Id AS CourseId, co.CourseCode, co.CourseName, co.Credits,
                   ts.SlotNumber, ts.SlotName, ts.StartTime, ts.EndTime,
                   lu.FullName AS LecturerName, lec.AcademicDegree
            FROM dbo.Enrollments e
            INNER JOIN dbo.Classes cl ON cl.Id = e.ClassId
            INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
            INNER JOIN dbo.TimeSlots ts ON ts.Id = cl.TimeSlotId
            LEFT JOIN dbo.Users lu ON lu.Id = cl.LecturerId
            LEFT JOIN dbo.Lecturers lec ON lec.UserId = lu.Id
            WHERE e.StudentId = ?
              AND cl.SemesterId = ?
              AND e.Status = 'Enrolled'
              AND cl.Status <> 'Cancelled'
            ORDER BY cl.DayOfWeek, ts.SlotNumber, cl.ClassCode
            """,
            (student_id, semester_id),
        )
        for r in rows:
            r['DayName'] = DAY_NAMES.get(r['DayOfWeek'], '')
            r['DayNameVi'] = DAY_NAMES_VI.get(r['DayOfWeek'], '')
            r['TimeRange'] = f"{_fmt_time(r['StartTime'])} - {_fmt_time(r['EndTime'])}"
            r['ScheduleDisplay'] = f"{r['DayName']} • {r['TimeRange']} ({r['Room']})"
        return rows

    @staticmethod
    def get_registered_credits(student_id, semester_id):
        """Tổng số tín chỉ sinh viên đã đăng ký hợp lệ trong học kỳ."""
        row = Database.query_one(
            """
            /* q:student_total_credits */
            SELECT ISNULL(SUM(co.Credits), 0) AS TotalCredits
            FROM dbo.Enrollments e
            INNER JOIN dbo.Classes cl ON cl.Id = e.ClassId
            INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
            WHERE e.StudentId = ?
              AND cl.SemesterId = ?
              AND e.Status = 'Enrolled'
              AND cl.Status <> 'Cancelled'
            """,
            (student_id, semester_id),
        )
        return int(row['TotalCredits']) if row and row.get('TotalCredits') is not None else 0

    @staticmethod
    def get_passed_course_ids(student_id):
        """Lấy tập hợp các CourseId mà sinh viên đã học xong và qua môn (IsPassed = 1)."""
        rows = Database.query_all(
            """
            /* q:student_passed_courses */
            SELECT DISTINCT cl.CourseId
            FROM dbo.Enrollments e
            INNER JOIN dbo.Classes cl ON cl.Id = e.ClassId
            WHERE e.StudentId = ?
              AND e.Status = 'Completed'
              AND e.IsPassed = 1
            """,
            (student_id,),
        )
        return {r['CourseId'] for r in rows}

    @staticmethod
    def get_available_classes(student_id, semester_id):
        """
        Hiển thị danh mục các lớp học phần đang mở trong đợt đăng ký hiện hành.
        Kèm theo trạng thái phân tích từng lớp:
          - Lớp còn chỗ trống không? (CurrentEnrollment < MaxCapacity)
          - Môn tiên quyết đã đạt chưa?
          - Trùng lịch học với lớp nào đã đăng ký không?
          - Đã đăng ký lớp này / môn này chưa?
          - Có được phép đăng ký hay không (can_register) và lý do chi tiết.
        """
        # 1. Lấy thông tin đợt đăng ký
        period = StudentLookupModel.get_active_registration_period(semester_id)
        max_allowed_credits = period['MaxCredits'] if period else DEFAULT_MAX_CREDITS
        min_required_credits = period['MinCredits'] if period else DEFAULT_MIN_CREDITS

        # 2. Lớp sinh viên đã đăng ký trong kỳ hiện hành
        enrolled_classes = StudentCourseModel.get_registered_classes(student_id, semester_id)
        enrolled_class_ids = {c['ClassId'] for c in enrolled_classes}
        enrolled_course_ids = {c['CourseId'] for c in enrolled_classes}
        enrolled_schedules = {(c['DayOfWeek'], c['TimeSlotId']): c for c in enrolled_classes}
        current_credits = sum(int(c['Credits']) for c in enrolled_classes)

        # 3. Môn tiên quyết đã hoàn thành
        passed_course_ids = StudentCourseModel.get_passed_course_ids(student_id)

        # 4. Danh sách các lớp học phần mở trong kỳ (không lấy lớp bị Cancelled)
        classes_raw = Database.query_all(
            """
            /* q:student_available_classes */
            SELECT cl.Id, cl.ClassCode, cl.CourseId, cl.SemesterId, cl.LecturerId, cl.ClassroomId,
                   cl.Room, cl.TimeSlotId, cl.DayOfWeek, cl.MinCapacity, cl.MaxCapacity,
                   cl.CurrentEnrollment, cl.Status AS ClassStatus,
                   co.CourseCode, co.CourseName, co.Credits, co.TheoryHours, co.PracticeHours,
                   co.Department, co.PrerequisiteCourseId,
                   pco.CourseCode AS PrerequisiteCode, pco.CourseName AS PrerequisiteName,
                   ts.SlotNumber, ts.SlotName, ts.StartTime, ts.EndTime,
                   lu.FullName AS LecturerName, lec.AcademicDegree
            FROM dbo.Classes cl
            INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
            INNER JOIN dbo.TimeSlots ts ON ts.Id = cl.TimeSlotId
            LEFT JOIN dbo.Courses pco ON pco.Id = co.PrerequisiteCourseId
            LEFT JOIN dbo.Users lu ON lu.Id = cl.LecturerId
            LEFT JOIN dbo.Lecturers lec ON lec.UserId = lu.Id
            WHERE cl.SemesterId = ?
              AND cl.Status IN ('Open', 'Closed')
            ORDER BY co.CourseCode, cl.ClassCode
            """,
            (semester_id,),
        )

        results = []
        for c in classes_raw:
            c_dict = dict(c)
            c_id = c_dict['Id']
            course_id = c_dict['CourseId']
            day = c_dict['DayOfWeek']
            slot_id = c_dict['TimeSlotId']
            current_enrolled = int(c_dict['CurrentEnrollment'])
            max_capacity = int(c_dict['MaxCapacity'])
            credits = int(c_dict['Credits'])
            prereq_id = c_dict.get('PrerequisiteCourseId')

            # Formatting
            c_dict['DayName'] = DAY_NAMES.get(day, '')
            c_dict['DayNameVi'] = DAY_NAMES_VI.get(day, '')
            c_dict['TimeRange'] = f"{_fmt_time(c_dict['StartTime'])} - {_fmt_time(c_dict['EndTime'])}"
            c_dict['ScheduleDisplay'] = f"{c_dict['DayName']} ({c_dict['TimeRange']}) • {c_dict['Room']}"
            c_dict['RemainingSeats'] = max(0, max_capacity - current_enrolled)
            c_dict['SeatsDisplay'] = f"{c_dict['RemainingSeats']} / {max_capacity}"

            # Kiểm tra 4 điều kiện:
            # Điều kiện 1: Sĩ số
            is_full = current_enrolled >= max_capacity or c_dict['ClassStatus'] == 'Closed'

            # Điều kiện 2: Môn tiên quyết
            prereq_met = True
            if prereq_id:
                prereq_met = (prereq_id in passed_course_ids)

            # Điều kiện 3: Trùng lịch
            has_conflict = False
            conflict_with = None
            if (day, slot_id) in enrolled_schedules and c_id not in enrolled_class_ids:
                has_conflict = True
                conflict_with = enrolled_schedules[(day, slot_id)]

            # Điều kiện 4: Giới hạn tín chỉ
            exceeds_max_credits = (current_credits + credits > max_allowed_credits)

            # Trạng thái đăng ký hiện tại
            is_enrolled = (c_id in enrolled_class_ids)
            is_course_enrolled = (course_id in enrolled_course_ids)

            can_register = True
            reasons = []

            if is_enrolled:
                can_register = False
                reasons.append("Đã đăng ký lớp này")
            elif is_course_enrolled:
                can_register = False
                reasons.append("Đã đăng ký lớp khác của môn học này")
            else:
                if is_full:
                    can_register = False
                    reasons.append("Lớp đã đủ chỗ (Full)")
                if not prereq_met:
                    can_register = False
                    reasons.append(f"Chưa đạt tiên quyết: {c_dict['PrerequisiteCode']}")
                if has_conflict:
                    can_register = False
                    reasons.append(f"Trùng ca với {conflict_with['ClassCode']}")
                if exceeds_max_credits:
                    can_register = False
                    reasons.append(f"Vượt quá 25 tín chỉ (+{credits} -> {current_credits + credits})")

            c_dict['IsEnrolled'] = is_enrolled
            c_dict['IsCourseEnrolled'] = is_course_enrolled
            c_dict['IsFull'] = is_full
            c_dict['PrerequisiteMet'] = prereq_met
            c_dict['HasConflict'] = has_conflict
            c_dict['ConflictClass'] = conflict_with['ClassCode'] if conflict_with else None
            c_dict['ExceedsMaxCredits'] = exceeds_max_credits
            c_dict['CanRegister'] = can_register
            c_dict['ReasonDisabled'] = "; ".join(reasons) if reasons else ""

            results.append(c_dict)

        return {
            'classes': results,
            'registered_classes': enrolled_classes,
            'current_credits': current_credits,
            'min_credits': min_required_credits,
            'max_credits': max_allowed_credits,
            'period': period,
        }

    @staticmethod
    def get_class_detail(student_id, class_id):
        """Chi tiết một lớp học phần cụ thể."""
        row = Database.query_one(
            """
            /* q:student_class_detail */
            SELECT cl.Id, cl.ClassCode, cl.CourseId, cl.SemesterId, cl.LecturerId, cl.ClassroomId,
                   cl.Room, cl.TimeSlotId, cl.DayOfWeek, cl.MinCapacity, cl.MaxCapacity,
                   cl.CurrentEnrollment, cl.Status AS ClassStatus,
                   co.CourseCode, co.CourseName, co.Credits, co.TheoryHours, co.PracticeHours,
                   co.Department, co.PrerequisiteCourseId,
                   pco.CourseCode AS PrerequisiteCode, pco.CourseName AS PrerequisiteName,
                   ts.SlotNumber, ts.SlotName, ts.StartTime, ts.EndTime,
                   lu.FullName AS LecturerName, lec.AcademicDegree,
                   sem.SemesterName, sem.AcademicYear, sem.CreditUnitPrice
            FROM dbo.Classes cl
            INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
            INNER JOIN dbo.TimeSlots ts ON ts.Id = cl.TimeSlotId
            INNER JOIN dbo.Semesters sem ON sem.Id = cl.SemesterId
            LEFT JOIN dbo.Courses pco ON pco.Id = co.PrerequisiteCourseId
            LEFT JOIN dbo.Users lu ON lu.Id = cl.LecturerId
            LEFT JOIN dbo.Lecturers lec ON lec.UserId = lu.Id
            WHERE cl.Id = ?
            """,
            (class_id,),
        )
        if not row:
            raise StudentNotFoundError("Không tìm thấy thông tin lớp học phần.", 404)

        row['DayName'] = DAY_NAMES.get(row['DayOfWeek'], '')
        row['DayNameVi'] = DAY_NAMES_VI.get(row['DayOfWeek'], '')
        row['TimeRange'] = f"{_fmt_time(row['StartTime'])} - {_fmt_time(row['EndTime'])}"
        row['RemainingSeats'] = max(0, row['MaxCapacity'] - row['CurrentEnrollment'])

        # Kiểm tra đã đăng ký chưa
        enrolled = Database.query_one(
            """
            /* q:student_check_single_enrollment */
            SELECT Id, Status FROM dbo.Enrollments WHERE StudentId = ? AND ClassId = ? AND Status = 'Enrolled'
            """,
            (student_id, class_id),
        )
        row['IsEnrolled'] = (enrolled is not None)
        return row


# ==========================================================================
# 4. THUẬT TOÁN ĐĂNG KÝ & HỦY MÔN HỌC (StudentRegistrationModel)
# ==========================================================================
class StudentRegistrationModel:
    @staticmethod
    def register_course(student_id, class_id):
        """
        Thuật toán Đăng ký môn học với 4 điều kiện nghiêm ngặt thực hiện trong Transaction:
        1. Lớp còn chỗ trống (CurrentEnrollment < MaxCapacity).
        2. Môn tiên quyết đã được hoàn thành (Status = 'Completed', IsPassed = 1).
        3. Lớp đăng ký không trùng ngày học và ca học với bất kỳ lớp nào đã đăng ký trong kỳ.
        4. Tổng tín chỉ sau khi đăng ký không vượt quá 25 tín chỉ (và theo dõi đạt tối thiểu 12 tín chỉ).

        Hành động khi thành công:
          - Tăng CurrentEnrollment lên 1. Nếu đầy thì chuyển Status = 'Closed'.
          - Cập nhật/Thêm bản ghi Enrollments sang Status = 'Enrolled'.
          - Ghi log vào RegistrationHistory.
          - Tự động tính toán lại bảng học phí Tuitions.
        """
        with Database.get_cursor() as cursor:
            # Bước 1: Khóa dòng và lấy thông tin lớp học phần
            cls = _fetch_one(
                cursor,
                """
                /* q:student_reg_get_class */
                SELECT cl.Id, cl.ClassCode, cl.CourseId, cl.SemesterId, cl.DayOfWeek, cl.TimeSlotId,
                       cl.CurrentEnrollment, cl.MaxCapacity, cl.Status AS ClassStatus,
                       co.CourseCode, co.CourseName, co.Credits, co.PrerequisiteCourseId
                FROM dbo.Classes cl
                INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
                WHERE cl.Id = ?
                """,
                (class_id,),
            )
            if not cls:
                raise StudentNotFoundError("Không tìm thấy lớp học phần để đăng ký.", 404)

            semester_id = cls['SemesterId']
            course_id = cls['CourseId']
            day_of_week = cls['DayOfWeek']
            time_slot_id = cls['TimeSlotId']
            current_enrollment = int(cls['CurrentEnrollment'])
            max_capacity = int(cls['MaxCapacity'])
            course_credits = int(cls['Credits'])
            prereq_course_id = cls.get('PrerequisiteCourseId')

            # Kiểm tra trạng thái lớp
            if cls['ClassStatus'] == 'Cancelled':
                raise StudentValidationError("Lớp học phần này đã bị hủy bỏ bởi Nhà trường.")

            # Bước 2: Kiểm tra thời gian mở đợt đăng ký môn học
            period = _fetch_one(
                cursor,
                """
                /* q:student_reg_check_period */
                SELECT Id, PeriodName, StartDate, EndDate, MinCredits, MaxCredits, IsActive
                FROM dbo.RegistrationPeriods
                WHERE SemesterId = ? AND IsActive = 1
                """,
                (semester_id,),
            )
            if not period:
                raise StudentValidationError("Hiện tại không có đợt đăng ký môn học nào đang mở cho học kỳ này.")

            now = datetime.now()
            start = period['StartDate'] if isinstance(period['StartDate'], datetime) else datetime.fromisoformat(str(period['StartDate'])[:19])
            end = period['EndDate'] if isinstance(period['EndDate'], datetime) else datetime.fromisoformat(str(period['EndDate'])[:19])
            if now < start or now > end:
                raise StudentValidationError(f"Cổng đăng ký môn học hiện đang đóng (Thời gian mở: {_fmt_datetime(start)} đến {_fmt_datetime(end)}).")

            max_allowed_credits = int(period['MaxCredits']) if period.get('MaxCredits') else DEFAULT_MAX_CREDITS
            min_allowed_credits = int(period['MinCredits']) if period.get('MinCredits') else DEFAULT_MIN_CREDITS

            # Bước 2.5: Kiểm tra sinh viên đã đăng ký môn học này chưa (tránh trùng môn khác lớp)
            dup = _fetch_one(
                cursor,
                """
                /* q:student_reg_check_course_dup */
                SELECT cl.Id, cl.ClassCode
                FROM dbo.Enrollments e
                INNER JOIN dbo.Classes cl ON cl.Id = e.ClassId
                WHERE e.StudentId = ?
                  AND cl.SemesterId = ?
                  AND cl.CourseId = ?
                  AND e.Status = 'Enrolled'
                  AND cl.Status <> 'Cancelled'
                """,
                (student_id, semester_id, course_id),
            )
            if dup:
                if dup['Id'] == class_id:
                    raise StudentConflictError("Bạn đã đăng ký lớp học phần này rồi.")
                else:
                    raise StudentConflictError(f"Bạn đã đăng ký một lớp khác ({dup['ClassCode']}) của môn học này trong cùng học kỳ.")

            # ==============================================================
            # ĐIỀU KIỆN 1: Lớp còn chỗ trống (CurrentEnrollment < MaxCapacity)
            # ==============================================================
            if current_enrollment >= max_capacity or cls['ClassStatus'] == 'Closed':
                raise StudentConflictError(
                    f"Đăng ký thất bại: Lớp học phần {cls['ClassCode']} đã hết chỗ trống "
                    f"({current_enrollment}/{max_capacity})."
                )

            # ==============================================================
            # ĐIỀU KIỆN 2: Môn tiên quyết đã được hoàn thành (Lịch sử học tập)
            # ==============================================================
            if prereq_course_id:
                passed = _fetch_one(
                    cursor,
                    """
                    /* q:student_reg_check_prereq */
                    SELECT e.Id
                    FROM dbo.Enrollments e
                    INNER JOIN dbo.Classes cl ON cl.Id = e.ClassId
                    WHERE e.StudentId = ?
                      AND cl.CourseId = ?
                      AND e.Status = 'Completed'
                      AND e.IsPassed = 1
                    """,
                    (student_id, prereq_course_id),
                )
                if not passed:
                    p_info = _fetch_one(
                        cursor,
                        "/* q:student_reg_prereq_info */ SELECT CourseCode, CourseName FROM dbo.Courses WHERE Id = ?",
                        (prereq_course_id,),
                    )
                    prereq_name = f"{p_info['CourseCode']} - {p_info['CourseName']}" if p_info else str(prereq_course_id)
                    raise StudentValidationError(
                        f"Đăng ký thất bại: Bạn chưa hoàn thành môn học tiên quyết bắt buộc ({prereq_name})."
                    )

            # Kiểm tra thêm bảng CoursePrerequisites nếu có nhiều môn tiên quyết
            multi_prereqs = _fetch_all(
                cursor,
                """
                /* q:student_reg_multi_prereqs */
                SELECT cp.PrerequisiteCourseId, co.CourseCode, co.CourseName
                FROM dbo.CoursePrerequisites cp
                INNER JOIN dbo.Courses co ON co.Id = cp.PrerequisiteCourseId
                WHERE cp.CourseId = ? AND cp.IsMandatory = 1
                """,
                (course_id,),
            )
            for mp in multi_prereqs:
                mp_id = mp['PrerequisiteCourseId']
                passed_mp = _fetch_one(
                    cursor,
                    """
                    /* q:student_reg_check_multi_prereq */
                    SELECT e.Id
                    FROM dbo.Enrollments e
                    INNER JOIN dbo.Classes cl ON cl.Id = e.ClassId
                    WHERE e.StudentId = ?
                      AND cl.CourseId = ?
                      AND e.Status = 'Completed'
                      AND e.IsPassed = 1
                    """,
                    (student_id, mp_id),
                )
                if not passed_mp:
                    raise StudentValidationError(
                        f"Đăng ký thất bại: Bạn chưa hoàn thành môn học tiên quyết ({mp['CourseCode']} - {mp['CourseName']})."
                    )

            # ==============================================================
            # ĐIỀU KIỆN 3: Không trùng ngày học và ca học với lớp đã đăng ký
            # ==============================================================
            conflict = _fetch_one(
                cursor,
                """
                /* q:student_reg_check_conflict */
                SELECT cl.ClassCode, co.CourseCode, co.CourseName, ts.SlotName, ts.StartTime, ts.EndTime
                FROM dbo.Enrollments e
                INNER JOIN dbo.Classes cl ON cl.Id = e.ClassId
                INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
                INNER JOIN dbo.TimeSlots ts ON ts.Id = cl.TimeSlotId
                WHERE e.StudentId = ?
                  AND cl.SemesterId = ?
                  AND e.Status = 'Enrolled'
                  AND cl.Status <> 'Cancelled'
                  AND cl.DayOfWeek = ?
                  AND cl.TimeSlotId = ?
                """,
                (student_id, semester_id, day_of_week, time_slot_id),
            )
            if conflict:
                day_name = DAY_NAMES_VI.get(day_of_week, f"Thứ {day_of_week}")
                raise StudentConflictError(
                    f"Đăng ký thất bại: Trùng lịch học với lớp {conflict['ClassCode']} ({conflict['CourseName']}) "
                    f"vào {day_name}, {conflict['SlotName']}."
                )

            # ==============================================================
            # ĐIỀU KIỆN 4: Tổng tín chỉ không vượt quá 25 tín chỉ
            # ==============================================================
            sum_row = _fetch_one(
                cursor,
                """
                /* q:student_reg_sum_credits */
                SELECT ISNULL(SUM(co.Credits), 0) AS CurrentCredits
                FROM dbo.Enrollments e
                INNER JOIN dbo.Classes cl ON cl.Id = e.ClassId
                INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
                WHERE e.StudentId = ?
                  AND cl.SemesterId = ?
                  AND e.Status = 'Enrolled'
                  AND cl.Status <> 'Cancelled'
                """,
                (student_id, semester_id),
            )
            current_credits = int(sum_row['CurrentCredits']) if sum_row else 0
            new_total_credits = current_credits + course_credits

            if new_total_credits > max_allowed_credits:
                raise StudentValidationError(
                    f"Đăng ký thất bại: Tổng số tín chỉ sau khi đăng ký ({new_total_credits} tín chỉ) "
                    f"vượt quá giới hạn tối đa cho phép ({max_allowed_credits} tín chỉ)."
                )

            # ==============================================================
            # THỰC THI GHI DANH KHI VƯỢT QUA CẢ 4 ĐIỀU KIỆN
            # ==============================================================
            # 1. Upsert bản ghi Enrollments
            existing_enrollment = _fetch_one(
                cursor,
                "/* q:student_reg_find_enrollment */ SELECT Id FROM dbo.Enrollments WHERE StudentId = ? AND ClassId = ?",
                (student_id, class_id),
            )
            if existing_enrollment:
                _execute(
                    cursor,
                    """
                    /* q:student_reg_update_enrollment */
                    UPDATE dbo.Enrollments
                    SET Status = 'Enrolled',
                        EnrolledAt = SYSDATETIME(),
                        CancelledAt = NULL
                    WHERE StudentId = ? AND ClassId = ?
                    """,
                    (student_id, class_id),
                )
            else:
                _execute(
                    cursor,
                    """
                    /* q:student_reg_insert_enrollment */
                    INSERT INTO dbo.Enrollments (StudentId, ClassId, Status, EnrolledAt)
                    VALUES (?, ?, 'Enrolled', SYSDATETIME())
                    """,
                    (student_id, class_id),
                )

            # 2. Tăng biến đếm CurrentEnrollment của lớp lên 1
            new_enrollment_count = current_enrollment + 1
            new_status = 'Closed' if new_enrollment_count >= max_capacity else 'Open'
            _execute(
                cursor,
                """
                /* q:student_reg_inc_enrollment */
                UPDATE dbo.Classes
                SET CurrentEnrollment = CurrentEnrollment + 1,
                    Status = CASE WHEN CurrentEnrollment + 1 >= MaxCapacity THEN 'Closed' ELSE Status END
                WHERE Id = ?
                """,
                (class_id,),
            )

            # 3. Ghi log kiểm toán vào RegistrationHistory
            _execute(
                cursor,
                """
                /* q:student_reg_audit_log */
                INSERT INTO dbo.RegistrationHistory (StudentId, ClassId, ActionType, PerformedByUserId, Note, ActionTime)
                VALUES (?, ?, 'Register', ?, ?, SYSDATETIME())
                """,
                (student_id, class_id, student_id, f"Sinh viên đăng ký thành công lớp {cls['ClassCode']}"),
            )

            # 4. Tự động tính toán lại bảng học phí Tuitions
            StudentTuitionModel.recalculate_tuition(student_id, semester_id, cursor=cursor)

            is_min_credits_met = (new_total_credits >= min_allowed_credits)
            notice = ""
            if not is_min_credits_met:
                notice = f" (Lưu ý: Hiện có {new_total_credits} tín chỉ, cần đạt tối thiểu {min_allowed_credits} tín chỉ trước khi kết thúc đợt)."

            return {
                'success': True,
                'message': f"Đăng ký thành công lớp học phần {cls['ClassCode']} ({cls['CourseName']})!{notice}",
                'data': {
                    'class_id': class_id,
                    'class_code': cls['ClassCode'],
                    'course_code': cls['CourseCode'],
                    'course_name': cls['CourseName'],
                    'credits': course_credits,
                    'total_registered_credits': new_total_credits,
                    'min_credits': min_allowed_credits,
                    'max_credits': max_allowed_credits,
                    'is_min_credits_met': is_min_credits_met,
                    'current_enrollment': new_enrollment_count,
                    'max_capacity': max_capacity,
                },
            }

    @staticmethod
    def drop_course(student_id, class_id):
        """
        Hủy đăng ký môn học trong thời gian mở cổng:
          - Giảm CurrentEnrollment của lớp đi 1.
          - Cập nhật bản ghi Enrollments sang Cancelled.
          - Ghi log vào RegistrationHistory.
          - Tự động tính toán lại học phí.
          - Kiểm tra cảnh báo nếu tổng tín chỉ còn lại < 12 tín chỉ.
        """
        with Database.get_cursor() as cursor:
            # Bước 1: Lấy thông tin lớp học phần
            cls = _fetch_one(
                cursor,
                """
                /* q:student_drop_get_class */
                SELECT cl.Id, cl.ClassCode, cl.SemesterId, cl.CurrentEnrollment, cl.MaxCapacity, cl.Status AS ClassStatus,
                       co.CourseCode, co.CourseName, co.Credits
                FROM dbo.Classes cl
                INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
                WHERE cl.Id = ?
                """,
                (class_id,),
            )
            if not cls:
                raise StudentNotFoundError("Không tìm thấy thông tin lớp học phần.", 404)

            semester_id = cls['SemesterId']
            course_credits = int(cls['Credits'])

            # Bước 2: Kiểm tra đợt đăng ký môn học còn mở không
            period = _fetch_one(
                cursor,
                """
                /* q:student_drop_check_period */
                SELECT Id, PeriodName, StartDate, EndDate, MinCredits, MaxCredits, IsActive
                FROM dbo.RegistrationPeriods
                WHERE SemesterId = ? AND IsActive = 1
                """,
                (semester_id,),
            )
            if not period:
                raise StudentValidationError("Đợt đăng ký/hủy môn học hiện đang đóng.")

            now = datetime.now()
            start = period['StartDate'] if isinstance(period['StartDate'], datetime) else datetime.fromisoformat(str(period['StartDate'])[:19])
            end = period['EndDate'] if isinstance(period['EndDate'], datetime) else datetime.fromisoformat(str(period['EndDate'])[:19])
            if now < start or now > end:
                raise StudentValidationError(f"Thời gian hủy môn học đã hết hạn (Đóng lúc: {_fmt_datetime(end)}).")

            min_required_credits = int(period['MinCredits']) if period.get('MinCredits') else DEFAULT_MIN_CREDITS

            # Bước 3: Kiểm tra sinh viên có đang Enrolled lớp này không
            enrollment = _fetch_one(
                cursor,
                """
                /* q:student_drop_check_enrolled */
                SELECT Id, Status FROM dbo.Enrollments
                WHERE StudentId = ? AND ClassId = ? AND Status = 'Enrolled'
                """,
                (student_id, class_id),
            )
            if not enrollment:
                raise StudentNotFoundError("Không tìm thấy dữ liệu đăng ký hợp lệ hoặc môn học đã được hủy trước đó.", 404)

            # Bước 4: Cập nhật bản ghi Enrollments sang Cancelled
            _execute(
                cursor,
                """
                /* q:student_drop_update_enrollment */
                UPDATE dbo.Enrollments
                SET Status = 'Cancelled',
                    CancelledAt = SYSDATETIME()
                WHERE StudentId = ? AND ClassId = ?
                """,
                (student_id, class_id),
            )

            # Bước 5: Giảm biến đếm CurrentEnrollment của lớp đi 1
            _execute(
                cursor,
                """
                /* q:student_drop_dec_enrollment */
                UPDATE dbo.Classes
                SET CurrentEnrollment = CASE WHEN CurrentEnrollment > 0 THEN CurrentEnrollment - 1 ELSE 0 END,
                    Status = CASE WHEN Status = 'Closed' THEN 'Open' ELSE Status END
                WHERE Id = ?
                """,
                (class_id,),
            )

            # Bước 6: Ghi nhận nhật ký hủy môn (RegistrationHistory)
            _execute(
                cursor,
                """
                /* q:student_drop_audit_log */
                INSERT INTO dbo.RegistrationHistory (StudentId, ClassId, ActionType, PerformedByUserId, Note, ActionTime)
                VALUES (?, ?, 'Drop', ?, ?, SYSDATETIME())
                """,
                (student_id, class_id, student_id, f"Sinh viên tự hủy môn học lớp {cls['ClassCode']}"),
            )

            # Bước 7: Tính toán lại học phí
            StudentTuitionModel.recalculate_tuition(student_id, semester_id, cursor=cursor)

            # Tính số tín chỉ còn lại và cảnh báo nếu < min_required_credits
            sum_row = _fetch_one(
                cursor,
                """
                /* q:student_drop_sum_credits */
                SELECT ISNULL(SUM(co.Credits), 0) AS RemainingCredits
                FROM dbo.Enrollments e
                INNER JOIN dbo.Classes cl ON cl.Id = e.ClassId
                INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
                WHERE e.StudentId = ?
                  AND cl.SemesterId = ?
                  AND e.Status = 'Enrolled'
                  AND cl.Status <> 'Cancelled'
                """,
                (student_id, semester_id),
            )
            remaining_credits = int(sum_row['RemainingCredits']) if sum_row else 0

            warning = ""
            if remaining_credits < min_required_credits:
                warning = f" (Cảnh báo: Tổng tín chỉ còn lại {remaining_credits} tín chỉ, dưới mức tối thiểu {min_required_credits} tín chỉ theo quy định đợt đăng ký)."

            return {
                'success': True,
                'message': f"Đã hủy đăng ký lớp học phần {cls['ClassCode']} ({cls['CourseName']}) thành công!{warning}",
                'data': {
                    'class_id': class_id,
                    'class_code': cls['ClassCode'],
                    'remaining_credits': remaining_credits,
                    'min_credits': min_required_credits,
                    'warning': warning,
                },
            }


# ==========================================================================
# 5. THỜI KHÓA BIỂU DẠNG LƯỚI TUẦN (StudentScheduleModel)
# ==========================================================================
class StudentScheduleModel:
    @staticmethod
    def week_info(semester, week=None, today=None):
        """Tính toán tuần học, ngày bắt đầu (Thứ 2) và kết thúc (Chủ Nhật) của tuần."""
        start = _to_date(semester['StartDate'])
        end = _to_date(semester['EndDate'])
        first_monday = start - timedelta(days=start.weekday())
        total_weeks = max(1, math.ceil(((end - first_monday).days + 1) / 7))

        if week is None:
            today = today or date.today()
            if today < first_monday:
                week = 1
            else:
                week = ((today - first_monday).days // 7) + 1
        try:
            week = int(week)
        except (TypeError, ValueError):
            raise StudentValidationError("Số tuần không hợp lệ.")
        week = min(max(week, 1), total_weeks)

        week_start = first_monday + timedelta(days=7 * (week - 1))
        week_end = week_start + timedelta(days=6)
        return {
            'week': week,
            'total_weeks': total_weeks,
            'week_start': week_start,
            'week_end': week_end,
            'semester_start': start,
            'semester_end': end,
        }

    @staticmethod
    def build_weekly_schedule(student_id, semester_id, week=None, today=None):
        """
        Dựng thời khóa biểu cá nhân của sinh viên theo dạng lưới tuần:
          - Trục ngang: Các ngày trong tuần (Thứ 2 đến Thứ 7/Chủ Nhật kèm ngày cụ thể).
          - Trục dọc: Các ca học (Slot 1..N).
          - Tế bào (Cell): Thông tin lớp học phần (Mã môn, Tên môn, Lớp, Phòng, Giảng viên).
        """
        semester = StudentLookupModel.get_semester_by_id(semester_id)
        if not semester:
            raise StudentNotFoundError("Không tìm thấy học kỳ.", 404)

        info = StudentScheduleModel.week_info(semester, week, today)
        enrolled_classes = StudentCourseModel.get_registered_classes(student_id, semester_id)
        slots = StudentLookupModel.get_time_slots()

        sessions = []
        for c in enrolled_classes:
            session_date = info['week_start'] + timedelta(days=c['DayOfWeek'] - 2)
            item = dict(c)
            item['SessionDate'] = session_date
            sessions.append(item)

        # Danh sách các ngày trong tuần đang chọn
        has_sunday = any(s['DayOfWeek'] == 8 for s in sessions)
        day_range = range(2, 9) if has_sunday else range(2, 8)
        days = [
            {
                'day': d,
                'name': DAY_NAMES[d],
                'name_vi': DAY_NAMES_VI[d],
                'date': info['week_start'] + timedelta(days=d - 2),
            }
            for d in day_range
        ]

        total_credits = sum(int(s['Credits']) for s in enrolled_classes)

        return {
            'semester': semester,
            'week': info,
            'days': days,
            'slots': slots,
            'sessions': sessions,
            'total_enrolled': len(enrolled_classes),
            'total_credits': total_credits,
        }


# ==========================================================================
# 6. TÍNH TOÁN HỌC PHÍ TỰ ĐỘNG (StudentTuitionModel)
# ==========================================================================
class StudentTuitionModel:
    @staticmethod
    def recalculate_tuition(student_id, semester_id, cursor=None):
        """
        Tự động tính lại học phí của sinh viên trong học kỳ:
          TotalCredits = SUM(Credits của các lớp đang Enrolled)
          TotalAmount = TotalCredits * CreditUnitPrice
        """
        def _do_calc(cur):
            # Lấy đơn giá tín chỉ của học kỳ
            sem = _fetch_one(
                cur,
                "/* q:student_tuition_get_unit_price */ SELECT CreditUnitPrice FROM dbo.Semesters WHERE Id = ?",
                (semester_id,),
            )
            unit_price = Decimal(str(sem['CreditUnitPrice'])) if sem and sem.get('CreditUnitPrice') else Decimal(str(DEFAULT_CREDIT_PRICE))

            # Tính tổng số tín chỉ đang Enrolled
            credits_row = _fetch_one(
                cur,
                """
                /* q:student_tuition_calc_credits */
                SELECT ISNULL(SUM(co.Credits), 0) AS TotalCredits
                FROM dbo.Enrollments e
                INNER JOIN dbo.Classes cl ON cl.Id = e.ClassId
                INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
                WHERE e.StudentId = ?
                  AND cl.SemesterId = ?
                  AND e.Status = 'Enrolled'
                  AND cl.Status <> 'Cancelled'
                """,
                (student_id, semester_id),
            )
            total_credits = int(credits_row['TotalCredits']) if credits_row else 0

            # Kiểm tra bản ghi Tuitions đã tồn tại chưa
            t_record = _fetch_one(
                cur,
                "/* q:student_tuition_check_record */ SELECT Id, PaidAmount FROM dbo.Tuitions WHERE StudentId = ? AND SemesterId = ?",
                (student_id, semester_id),
            )
            if t_record:
                paid = Decimal(str(t_record.get('PaidAmount') or 0))
                total_amount = Decimal(total_credits) * unit_price
                new_status = 'Paid' if paid >= total_amount and total_amount > 0 else ('Partial' if paid > 0 else 'Unpaid')
                _execute(
                    cur,
                    """
                    /* q:student_tuition_update_record */
                    UPDATE dbo.Tuitions
                    SET TotalCredits = ?,
                        UnitPrice = ?,
                        PaymentStatus = ?,
                        LastCalculatedAt = SYSDATETIME()
                    WHERE StudentId = ? AND SemesterId = ?
                    """,
                    (total_credits, float(unit_price), new_status, student_id, semester_id),
                )
            else:
                _execute(
                    cur,
                    """
                    /* q:student_tuition_insert_record */
                    INSERT INTO dbo.Tuitions (StudentId, SemesterId, TotalCredits, UnitPrice, PaidAmount, PaymentStatus, LastCalculatedAt)
                    VALUES (?, ?, ?, ?, 0.00, 'Unpaid', SYSDATETIME())
                    """,
                    (student_id, semester_id, total_credits, float(unit_price)),
                )

        if cursor:
            _do_calc(cursor)
        else:
            with Database.get_cursor() as new_cursor:
                _do_calc(new_cursor)

    @staticmethod
    def get_tuition_statement(student_id, semester_id):
        """
        Bảng kê chi tiết học phí của sinh viên trong học kỳ:
          - Tổng số môn học đăng ký
          - Tổng số tín chỉ
          - Đơn giá trên mỗi tín chỉ
          - Tổng số tiền học phí
          - Danh sách chi tiết từng môn học & thành tiền tương ứng
        """
        # Đảm bảo tính toán mới nhất
        StudentTuitionModel.recalculate_tuition(student_id, semester_id)

        semester = StudentLookupModel.get_semester_by_id(semester_id)
        if not semester:
            raise StudentNotFoundError("Không tìm thấy học kỳ.", 404)

        unit_price = Decimal(str(semester.get('CreditUnitPrice') or DEFAULT_CREDIT_PRICE))

        # Lấy bản ghi tổng hợp từ Tuitions
        tuition_record = Database.query_one(
            """
            /* q:student_tuition_statement_summary */
            SELECT Id, StudentId, SemesterId, TotalCredits, UnitPrice, PaidAmount, PaymentStatus, LastCalculatedAt
            FROM dbo.Tuitions
            WHERE StudentId = ? AND SemesterId = ?
            """,
            (student_id, semester_id),
        )

        # Lấy danh sách các môn học đang đăng ký
        enrolled_classes = Database.query_all(
            """
            /* q:student_tuition_itemized_courses */
            SELECT cl.Id AS ClassId, cl.ClassCode, co.CourseCode, co.CourseName, co.Credits,
                   e.EnrolledAt
            FROM dbo.Enrollments e
            INNER JOIN dbo.Classes cl ON cl.Id = e.ClassId
            INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
            WHERE e.StudentId = ?
              AND cl.SemesterId = ?
              AND e.Status = 'Enrolled'
              AND cl.Status <> 'Cancelled'
            ORDER BY co.CourseCode, cl.ClassCode
            """,
            (student_id, semester_id),
        )

        items = []
        for index, item in enumerate(enrolled_classes, start=1):
            cr = int(item['Credits'])
            subtotal = Decimal(cr) * unit_price
            items.append({
                'index': index,
                'class_id': item['ClassId'],
                'class_code': item['ClassCode'],
                'course_code': item['CourseCode'],
                'course_name': item['CourseName'],
                'credits': cr,
                'unit_price': float(unit_price),
                'subtotal': float(subtotal),
                'enrolled_at': _fmt_datetime(item['EnrolledAt']),
            })

        total_credits = sum(x['credits'] for x in items)
        total_amount = Decimal(total_credits) * unit_price
        paid_amount = Decimal(str(tuition_record.get('PaidAmount') or 0)) if tuition_record else Decimal(0)
        remaining_amount = max(Decimal(0), total_amount - paid_amount)
        payment_status = tuition_record.get('PaymentStatus', 'Unpaid') if tuition_record else 'Unpaid'

        return {
            'semester': semester,
            'summary': {
                'total_courses': len(items),
                'total_credits': total_credits,
                'unit_price': float(unit_price),
                'total_amount': float(total_amount),
                'paid_amount': float(paid_amount),
                'remaining_amount': float(remaining_amount),
                'payment_status': payment_status,
                'billing_status': 'Calculated' if total_amount > 0 else 'No Charges',
                'last_calculated_at': _fmt_datetime(tuition_record.get('LastCalculatedAt')) if tuition_record else None,
            },
            'items': items,
        }


# ==========================================================================
# 7. LỊCH SỬ GIAO DỊCH ĐĂNG KÝ (StudentHistoryModel)
# ==========================================================================
class StudentHistoryModel:
    @staticmethod
    def get_history(student_id, semester_id=None, filter_type='all'):
        """
        Tra cứu toàn bộ lịch sử đăng ký & hủy môn học của sinh viên.
        Bộ lọc: 'all', 'registered' (Register), 'canceled' (Drop).
        """
        params = [student_id]
        where_clauses = ["rh.StudentId = ?"]

        if semester_id:
            where_clauses.append("cl.SemesterId = ?")
            params.append(semester_id)

        if filter_type == 'registered':
            where_clauses.append("rh.ActionType = 'Register'")
        elif filter_type == 'canceled':
            where_clauses.append("rh.ActionType IN ('Drop', 'AdminCancelClass')")

        where_sql = " AND ".join(where_clauses)
        sql = f"""
            /* q:student_history */
            SELECT rh.Id AS TransactionId, rh.ActionType, rh.ActionTime, rh.Note,
                   cl.ClassCode, co.CourseCode, co.CourseName, co.Credits,
                   sem.SemesterName, sem.AcademicYear
            FROM dbo.RegistrationHistory rh
            INNER JOIN dbo.Classes cl ON cl.Id = rh.ClassId
            INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
            INNER JOIN dbo.Semesters sem ON sem.Id = cl.SemesterId
            WHERE {where_sql}
            ORDER BY rh.ActionTime DESC, rh.Id DESC
        """
        rows = Database.query_all(sql, tuple(params))
        for r in rows:
            r['ActionTimeDisplay'] = _fmt_datetime(r['ActionTime'])
            if r['ActionType'] == 'Register':
                r['StatusBadge'] = 'Registered'
                r['StatusClass'] = 'badge-success'
            else:
                r['StatusBadge'] = 'Canceled'
                r['StatusClass'] = 'badge-danger'
        return rows
