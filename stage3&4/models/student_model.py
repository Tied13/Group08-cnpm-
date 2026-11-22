"""
models/student_model.py
=======================
Data access layer (Model) for the STUDENT PORTAL module.
Course Registration System.

Core features:
1. StudentProfileModel      - Student profile, account info & password change.
2. StudentLookupModel       - Semesters, time slots & course registration periods lookup.
3. StudentCourseModel       - Open class sections during registration period,
                              enrolled classes & registration eligibility checks.
4. StudentRegistrationModel - Course registration algorithm (strict 4-condition check),
                              course drop (decrement enrollment count, mark Cancelled),
                              audit logging (RegistrationHistory).
5. StudentScheduleModel     - Student weekly class schedule / timetable.
6. StudentTuitionModel      - Automated tuition calculation based on registered credits & unit rate.
7. StudentHistoryModel      - Course registration / drop history (Audit Log).

Conventions:
- All queries use '?' parameters to prevent SQL injection via models/db.py.
- Multi-table write operations (register, drop) are wrapped in a single transaction
  using `Database.get_cursor()`.
- Each query includes a /* q:query_name */ comment for identification and unit testing.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
import math
import re
from werkzeug.security import check_password_hash, generate_password_hash

from models.db import Database


# ==========================================================================
# BUSINESS CONSTANTS
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
    2: 'Monday', 3: 'Tuesday', 4: 'Wednesday', 5: 'Thursday',
    6: 'Friday', 7: 'Saturday', 8: 'Sunday',
}


# ==========================================================================
# BUSINESS EXCEPTIONS
# ==========================================================================
class StudentError(Exception):
    """Base business exception for the Student Portal module."""
    status_code = 400

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class StudentValidationError(StudentError):
    """Invalid input data or unmet prerequisite/rule condition (HTTP 400)."""
    status_code = 400


class StudentNotFoundError(StudentError):
    """Record not found (HTTP 404)."""
    status_code = 404


class StudentConflictError(StudentError):
    """Schedule conflict, full capacity, or duplicate registration (HTTP 409)."""
    status_code = 409


class StudentPermissionError(StudentError):
    """Permission denied for the requested action (HTTP 403)."""
    status_code = 403


# ==========================================================================
# SHARED HELPER FUNCTIONS
# ==========================================================================
def _to_date(value):
    """Convert date / datetime / ISO string to datetime.date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return date.today()
    return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()


def _fmt_time(value):
    """Format time / string as 'HH:MM'."""
    if hasattr(value, 'strftime'):
        return value.strftime('%H:%M')
    return str(value)[:5] if value else ''


def _fmt_datetime(value):
    """Format datetime / string as 'YYYY-MM-DD HH:MM:SS'."""
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
    """Run SELECT within the current transaction and return one dict (or None)."""
    _execute(cursor, sql, params)
    if not cursor.description:
        return None
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


def _fetch_all(cursor, sql, params=None):
    """Run SELECT within the current transaction and return a list of dicts."""
    _execute(cursor, sql, params)
    if not cursor.description:
        return []
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# ==========================================================================
# 1. SEMESTERS, TIME SLOTS & REGISTRATION PERIODS LOOKUP (StudentLookupModel)
# ==========================================================================
class StudentLookupModel:
    @staticmethod
    def get_semesters():
        """List all semesters in the system."""
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
        """Get the current active semester (IsCurrent = 1 or the latest semester)."""
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
        """Get semester details by Id."""
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
        """Get the active registration period for a semester."""
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
        """Check whether the course registration window is currently open."""
        period = StudentLookupModel.get_active_registration_period(semester_id)
        if not period:
            return False, None, "There is currently no active registration period for this semester."
        now = datetime.now()
        start = period['StartDate'] if isinstance(period['StartDate'], datetime) else datetime.fromisoformat(str(period['StartDate'])[:19])
        end = period['EndDate'] if isinstance(period['EndDate'], datetime) else datetime.fromisoformat(str(period['EndDate'])[:19])
        if now < start:
            return False, period, f"Registration period '{period['PeriodName']}' has not started yet (Opens at: {_fmt_datetime(start)})."
        if now > end:
            return False, period, f"Registration period '{period['PeriodName']}' has ended (Closed at: {_fmt_datetime(end)})."
        return True, period, "Course registration portal is currently open."

    @staticmethod
    def get_time_slots():
        """List all time slots."""
        return Database.query_all(
            """
            /* q:student_lookup_timeslots */
            SELECT Id, SlotNumber, SlotName, StartTime, EndTime
            FROM dbo.TimeSlots
            ORDER BY SlotNumber ASC
            """
        )


# ==========================================================================
# 2. STUDENT PROFILE & ACCOUNT (StudentProfileModel)
# ==========================================================================
class StudentProfileModel:
    @staticmethod
    def get_profile(student_id):
        """Get personal and academic profile information for a student."""
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
            raise StudentNotFoundError("Student profile not found.", 404)
        return row

    @staticmethod
    def change_password(student_id, current_password, new_password, confirm_password):
        """Change a student's account password."""
        if not current_password or not new_password or not confirm_password:
            raise StudentValidationError("Please enter all required password fields.")
        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise StudentValidationError(f"New password must be at least {MIN_PASSWORD_LENGTH} characters.")
        if new_password != confirm_password:
            raise StudentValidationError("Password confirmation does not match.")
        if new_password == current_password:
            raise StudentValidationError("New password must be different from current password.")

        user = Database.query_one(
            "/* q:student_check_password */ SELECT Id, PasswordHash FROM dbo.Users WHERE Id = ?",
            (student_id,),
        )
        if not user:
            raise StudentNotFoundError("Student account does not exist.", 404)

        stored = user['PasswordHash']
        # Support both Werkzeug hashes (scrypt/pbkdf2) and SHA-256 fallback
        valid = False
        try:
            valid = check_password_hash(stored, current_password)
        except Exception:
            import hashlib
            valid = (stored == hashlib.sha256(current_password.encode()).hexdigest())

        if not valid:
            raise StudentValidationError("Current password is incorrect.")

        new_hash = generate_password_hash(new_password)
        Database.execute(
            "/* q:student_update_password */ UPDATE dbo.Users SET PasswordHash = ?, UpdatedAt = SYSDATETIME() WHERE Id = ?",
            (new_hash, student_id),
        )
        return True


# ==========================================================================
# 3. CLASS SECTIONS CATALOG & PREREQUISITES (StudentCourseModel)
# ==========================================================================
class StudentCourseModel:
    @staticmethod
    def get_registered_classes(student_id, semester_id):
        """List class sections the student is currently enrolled in for the semester (Status = 'Enrolled')."""
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
        """Total valid enrolled credits for the student in the semester."""
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
        """Get the set of CourseIds that the student has completed and passed (IsPassed = 1)."""
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
        Display class sections open during the current registration period.
        Includes per-class eligibility analysis:
- Does the section have open seats? (CurrentEnrollment < MaxCapacity)
- Has the prerequisite course been passed?
- Does it conflict with an already-enrolled class schedule?
- Is this section or course already registered?
- Whether registration is allowed (can_register) and detailed reasons if disabled.
        """
        # 1. Fetch registration period settings
        period = StudentLookupModel.get_active_registration_period(semester_id)
        max_allowed_credits = period['MaxCredits'] if period else DEFAULT_MAX_CREDITS
        min_required_credits = period['MinCredits'] if period else DEFAULT_MIN_CREDITS

        # 2. Classes already enrolled in for the current semester
        enrolled_classes = StudentCourseModel.get_registered_classes(student_id, semester_id)
        enrolled_class_ids = {c['ClassId'] for c in enrolled_classes}
        enrolled_course_ids = {c['CourseId'] for c in enrolled_classes}
        enrolled_schedules = {(c['DayOfWeek'], c['TimeSlotId']): c for c in enrolled_classes}
        current_credits = sum(int(c['Credits']) for c in enrolled_classes)

        # 3. Completed prerequisite courses
        passed_course_ids = StudentCourseModel.get_passed_course_ids(student_id)

        # 4. Open/closed class sections in the semester (excluding Cancelled classes)
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
              AND co.IsActive = 1
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

            # Check the 4 conditions:
            # Condition 1: Class capacity
            is_full = current_enrolled >= max_capacity or c_dict['ClassStatus'] == 'Closed'

            # Condition 2: Prerequisite course
            prereq_met = True
            if prereq_id:
                prereq_met = (prereq_id in passed_course_ids)

            # Condition 3: Schedule conflict
            has_conflict = False
            conflict_with = None
            if (day, slot_id) in enrolled_schedules and c_id not in enrolled_class_ids:
                has_conflict = True
                conflict_with = enrolled_schedules[(day, slot_id)]
