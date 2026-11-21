"""
models/lecturer_model.py
========================
Data layer (Model) for the LECTURER MODULE.

Features:
    1. LecturerProfileModel  - Personal information + password change.
    2. LecturerClassModel    - List of assigned course sections (with ACTUAL enrollment count),
                               student list per class, teaching load statistics.
    3. LecturerScheduleModel - Weekly teaching schedule (based on the semester start date).
    4. LecturerExportModel   - Builds the CSV (UTF-8) content of a class's student list.

Data is based on the schema of init_database.sql (Member 1):
    Users, Lecturers, Semesters, Courses, Classes, Classrooms, TimeSlots, Enrollments, Students.
    - Classes.LecturerId points to the lecturer's Users.Id.
    - Actual enrollment count = number of Enrollments records with Status = 'Enrolled' (the
      Classes.CurrentEnrollment column is not fully trusted, so reports always match the
      detailed list).

Every query uses '?' parameters (SQL Injection protection) via models/db.py.
Every SQL statement has a /* q:query_name */ comment so the Unit Tests (tests/test_lecturer.py)
can identify it; this comment does not affect SQL Server (same convention as models/admin_model.py).
"""

import csv
import io
import math
from datetime import date, datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

from models.db import Database


# ==========================================================================
# CONSTANTS
# ==========================================================================
MIN_PASSWORD_LENGTH = 6
DAY_NAMES = {
    2: 'Monday', 3: 'Tuesday', 4: 'Wednesday', 5: 'Thursday',
    6: 'Friday', 7: 'Saturday', 8: 'Sunday',
}

CSV_HEADERS = [
    'No.', 'Student ID', 'Full Name', 'Class', 'Major',
    'Email', 'Phone Number', 'Registration Date', 'Status',
]
# Leading characters that Excel may misinterpret as a formula (CSV injection)
_CSV_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


# ==========================================================================
# EXCEPTIONS - the Controller uses status_code to return the matching HTTP code
# ==========================================================================
class LecturerError(Exception):
    """General business error of the Lecturer module."""
    status_code = 400

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class LecturerValidationError(LecturerError):
    """Invalid input data (HTTP 400)."""
    status_code = 400


class LecturerPermissionError(LecturerError):
    """Lecturer accessing a class that is not assigned to them (HTTP 403)."""
    status_code = 403


class LecturerNotFoundError(LecturerError):
    """Record not found (HTTP 404)."""
    status_code = 404


# ==========================================================================
# HELPER FUNCTIONS
# ==========================================================================
def _to_date(value):
    """Convert a date/datetime/ISO string to datetime.date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()


def _fmt_time(value):
    """Convert a time/string to 'HH:MM'."""
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
    """Prevent CSV/Excel formula injection: prefix a ' to cells starting with = + - @."""
    if value is None:
        return ''
    text = str(value)
    if text.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + text
    return text


def _decorate_class(row):
    """Add day name / time range / room to one course section row."""
    item = dict(row)
    item['DayName'] = DAY_NAMES.get(item.get('DayOfWeek'), '')
    item['TimeRange'] = f"{_fmt_time(item.get('StartTime'))} - {_fmt_time(item.get('EndTime'))}"
    item['Room'] = item.get('RoomCode') or item.get('Room') or ''
    return item


# ==========================================================================
# 1. PROFILE & PASSWORD CHANGE
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
            raise LecturerNotFoundError('Lecturer profile not found.', 404)
        row.pop('PasswordHash', None)
        return row

    @staticmethod
    def change_password(user_id, current_password, new_password, confirm_password):
        """Change password: validate the old password, length, confirmation, and that it differs from the old password."""
        if not current_password or not new_password or not confirm_password:
            raise LecturerValidationError('Please enter all required password fields.')
        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise LecturerValidationError(
                f'New password must be at least {MIN_PASSWORD_LENGTH} characters.')
        if new_password != confirm_password:
            raise LecturerValidationError('Password confirmation does not match.')
        if new_password == current_password:
            raise LecturerValidationError('New password must be different from current password.')

        user = Database.query_one(
            "/* q:lecturer_password_hash */ SELECT Id, PasswordHash FROM dbo.Users WHERE Id = ?",
            (user_id,),
        )
        if not user:
            raise LecturerNotFoundError('User account not found.', 404)
        if not check_password_hash(user['PasswordHash'], current_password):
            raise LecturerValidationError('Current password is incorrect.')

        Database.execute(
            "/* q:lecturer_update_password */ "
            "UPDATE dbo.Users SET PasswordHash = ?, UpdatedAt = SYSDATETIME() WHERE Id = ?",
            (generate_password_hash(new_password), user_id),
        )
        return True


# ==========================================================================
# 2. COURSE SECTIONS & STUDENT LISTS
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
        Course sections assigned to the lecturer in the semester, with the actual enrollment
        count (counting 'Enrolled' Enrollments). Cancelled classes are still shown with Status='Cancelled'.
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
        """Teaching load statistics (cancelled classes are excluded)."""
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
        """Get the course section and ensure it belongs to the logged-in lecturer."""
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
            raise LecturerNotFoundError('Class section not found.', 404)
        if row['LecturerId'] != lecturer_id:
            raise LecturerPermissionError('You are not assigned to teach this class section.', 403)
        return row

    @staticmethod
    def list_students(lecturer_id, class_id):
        """Students successfully enrolled (Enrolled/Completed) in the class: student ID, full name, class, enrollment date."""
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
# 3. WEEKLY TEACHING SCHEDULE
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
        Compute week information. Week 1 starts on the Monday of the week containing the semester start date.
        If week=None, use the current week (clamped to [1, total number of weeks]).
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
            raise LecturerValidationError('Invalid week number.')
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
            raise LecturerNotFoundError('Semester not found.', 404)

        info = LecturerScheduleModel.week_info(semester, week, today)
        classes = LecturerClassModel.list_assigned_classes(lecturer_id, semester_id)

        sessions = []
        for c in classes:
            if c['ClassStatus'] == 'Cancelled':
                continue  # Cancelled classes no longer have teaching sessions
            session_date = info['week_start'] + timedelta(days=c['DayOfWeek'] - 2)
            if not (info['semester_start'] <= session_date <= info['semester_end']):
                continue  # Session falls outside the semester period
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
# 4. CSV EXPORT
# ==========================================================================
class LecturerExportModel:

    @staticmethod
    def build_students_csv(lecturer_id, class_id):
        """
        Return (filename, csv_content). The content is a str; the controller encodes it as UTF-8 with BOM
        (utf-8-sig) so Excel displays accented characters correctly. A class with no students -> header row only.
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
