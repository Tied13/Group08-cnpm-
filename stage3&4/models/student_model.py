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

            # Condition 4: Credit limit
            exceeds_max_credits = (current_credits + credits > max_allowed_credits)

            # Current enrollment status
            is_enrolled = (c_id in enrolled_class_ids)
            is_course_enrolled = (course_id in enrolled_course_ids)

            can_register = True
            reasons = []

            if is_enrolled:
                can_register = False
                reasons.append("Already registered for this section")
            elif is_course_enrolled:
                can_register = False
                reasons.append("Already registered for another section of this course")
            else:
                if is_full:
                    can_register = False
                    reasons.append("Section is full (Max capacity reached)")
                if not prereq_met:
                    can_register = False
                    reasons.append(f"Prerequisite not met: {c_dict['PrerequisiteCode']}")
                if has_conflict:
                    can_register = False
                    reasons.append(f"Schedule conflict with {conflict_with['ClassCode']}")
                if exceeds_max_credits:
                    can_register = False
                    reasons.append(f"Exceeds max allowed credits (+{credits} -> {current_credits + credits})")

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
        """Get detailed information for a specific class section."""
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
            raise StudentNotFoundError("Class section not found.", 404)

        row['DayName'] = DAY_NAMES.get(row['DayOfWeek'], '')
        row['DayNameVi'] = DAY_NAMES_VI.get(row['DayOfWeek'], '')
        row['TimeRange'] = f"{_fmt_time(row['StartTime'])} - {_fmt_time(row['EndTime'])}"
        row['RemainingSeats'] = max(0, row['MaxCapacity'] - row['CurrentEnrollment'])

        # Check whether already enrolled
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
# 4. COURSE REGISTRATION & DROP LOGIC (StudentRegistrationModel)
# ==========================================================================
class StudentRegistrationModel:
    @staticmethod
    def register_course(student_id, class_id):
        with Database.get_cursor() as cursor:
            # Step 1: Lock row and fetch class section details
            cls = _fetch_one(
                cursor,
                """
                /* q:student_reg_get_class */
                SELECT cl.Id, cl.ClassCode, cl.CourseId, cl.SemesterId, cl.DayOfWeek, cl.TimeSlotId,
                       cl.CurrentEnrollment, cl.MaxCapacity, cl.Status AS ClassStatus,
                       co.CourseCode, co.CourseName, co.Credits, co.PrerequisiteCourseId, co.IsActive
                FROM dbo.Classes cl
                INNER JOIN dbo.Courses co ON co.Id = cl.CourseId
                WHERE cl.Id = ?
                """,
                (class_id,),
            )
            if not cls:
                raise StudentNotFoundError("Class section to register not found.", 404)

            semester_id = cls['SemesterId']
            course_id = cls['CourseId']
            day_of_week = cls['DayOfWeek']
            time_slot_id = cls['TimeSlotId']
            current_enrollment = int(cls['CurrentEnrollment'])
            max_capacity = int(cls['MaxCapacity'])
            course_credits = int(cls['Credits'])
            prereq_course_id = cls.get('PrerequisiteCourseId')

            # Check course and class status
            if cls.get('IsActive') is not None and not cls.get('IsActive'):
                raise StudentValidationError("This course has been locked/deactivated by the University and cannot be registered.")

            if cls['ClassStatus'] == 'Cancelled':
                raise StudentValidationError("This class section has been cancelled by the University.")

            # Step 2: Check whether the registration period is currently open
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
                raise StudentValidationError("There is currently no active registration period for this semester.")

            now = datetime.now()
            start = period['StartDate'] if isinstance(period['StartDate'], datetime) else datetime.fromisoformat(str(period['StartDate'])[:19])
            end = period['EndDate'] if isinstance(period['EndDate'], datetime) else datetime.fromisoformat(str(period['EndDate'])[:19])
            if now < start or now > end:
                raise StudentValidationError(f"Registration period is closed (Open time: {_fmt_datetime(start)} to {_fmt_datetime(end)}).")

            max_allowed_credits = int(period['MaxCredits']) if period.get('MaxCredits') else DEFAULT_MAX_CREDITS
            min_allowed_credits = int(period['MinCredits']) if period.get('MinCredits') else DEFAULT_MIN_CREDITS

            # Step 2.5: Check if the student is already registered for this course (prevent duplicate sections)
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
                    raise StudentConflictError("You have already registered for this class section.")
                else:
                    raise StudentConflictError(f"You have already registered for another section ({dup['ClassCode']}) of this course in this semester.")

            # ==============================================================
            # CONDITION 1: Open seat available (CurrentEnrollment < MaxCapacity)
            # ==============================================================
            if current_enrollment >= max_capacity or cls['ClassStatus'] == 'Closed':
                raise StudentConflictError(
                    f"Registration failed: Section {cls['ClassCode']} is full "
                    f"({current_enrollment}/{max_capacity})."
                )

            # ==============================================================
            # CONDITION 2: Prerequisite course completed (Academic history)
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
                        f"Registration failed: You have not completed the required prerequisite course ({prereq_name})."
                    )

            # Also check CoursePrerequisites for multiple mandatory prerequisites
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
                        f"Registration failed: You have not completed the required prerequisite course ({mp['CourseCode']} - {mp['CourseName']})."
                    )

            # ==============================================================
            # CONDITION 3: No day/time-slot conflict with enrolled classes
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
                day_name = DAY_NAMES.get(day_of_week, f"Day {day_of_week}")
                raise StudentConflictError(
                    f"Registration failed: Schedule conflict with class {conflict['ClassCode']} ({conflict['CourseName']}) "
                    f"on {day_name}, {conflict['SlotName']}."
                )

            # ==============================================================
            # CONDITION 4: Total credits do not exceed the maximum limit (25)
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
                    f"Registration failed: Total registered credits ({new_total_credits} credits) "
                    f"exceeds the maximum allowed limit ({max_allowed_credits} credits)."
                )

            # ==============================================================
            # COMMIT ENROLLMENT ONCE ALL 4 CONDITIONS PASS
            # ==============================================================
            # 1. Upsert Enrollments record
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

            # 2. Increment CurrentEnrollment on the class section by 1
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

            # 3. Record audit entry in RegistrationHistory
            _execute(
                cursor,
                """
                /* q:student_reg_audit_log */
                INSERT INTO dbo.RegistrationHistory (StudentId, ClassId, ActionType, PerformedByUserId, Note, ActionTime)
                VALUES (?, ?, 'Register', ?, ?, SYSDATETIME())
                """,
                (student_id, class_id, student_id, f"Student successfully registered for section {cls['ClassCode']}"),
            )

            # 4. Recalculate Tuitions automatically
            StudentTuitionModel.recalculate_tuition(student_id, semester_id, cursor=cursor)

            is_min_credits_met = (new_total_credits >= min_allowed_credits)
            notice = ""
            if not is_min_credits_met:
                notice = f" (Note: Currently enrolled in {new_total_credits} credits, minimum {min_allowed_credits} credits required before registration deadline)."

            return {
                'success': True,
                'message': f"Successfully registered for class {cls['ClassCode']} ({cls['CourseName']})!{notice}",
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
        Drop a registered course while the registration window is open:
- Decrement CurrentEnrollment on the class section by 1.
- Update Enrollments status to Cancelled.
- Record an audit entry in RegistrationHistory.
- Recalculate tuition automatically.
- Emit a warning if remaining credits fall below 12.
        """
        with Database.get_cursor() as cursor:
            # Step 1: Fetch class section details
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
                raise StudentNotFoundError("Class section not found.", 404)

            semester_id = cls['SemesterId']
            course_credits = int(cls['Credits'])

            # Step 2: Check whether the registration/drop period is still open
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
                raise StudentValidationError("Course registration/drop period is currently closed.")

            now = datetime.now()
            start = period['StartDate'] if isinstance(period['StartDate'], datetime) else datetime.fromisoformat(str(period['StartDate'])[:19])
            end = period['EndDate'] if isinstance(period['EndDate'], datetime) else datetime.fromisoformat(str(period['EndDate'])[:19])
            if now < start or now > end:
                raise StudentValidationError(f"Course drop deadline has expired (Closed at: {_fmt_datetime(end)}).")

            min_required_credits = int(period['MinCredits']) if period.get('MinCredits') else DEFAULT_MIN_CREDITS

            # Step 3: Verify the student has an active Enrolled record for this class
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
                raise StudentNotFoundError("No valid enrollment record found or course was previously dropped.", 404)

            # Step 4: Mark Enrollments record as Cancelled
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

            # Step 5: Decrement CurrentEnrollment on the class section by 1
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

            # Step 6: Record drop entry in RegistrationHistory
            _execute(
                cursor,
                """
                /* q:student_drop_audit_log */
                INSERT INTO dbo.RegistrationHistory (StudentId, ClassId, ActionType, PerformedByUserId, Note, ActionTime)
                VALUES (?, ?, 'Drop', ?, ?, SYSDATETIME())
                """,
                (student_id, class_id, student_id, f"Student dropped section {cls['ClassCode']}"),
            )

            # Step 7: Recalculate tuition
            StudentTuitionModel.recalculate_tuition(student_id, semester_id, cursor=cursor)

            # Compute remaining credits and warn if below min_required_credits
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
                warning = f" (Warning: Remaining credits {remaining_credits} is below the minimum required {min_required_credits} credits for this registration period)."

            return {
                'success': True,
                'message': f"Successfully dropped class {cls['ClassCode']} ({cls['CourseName']})!{warning}",
                'data': {
                    'class_id': class_id,
                    'class_code': cls['ClassCode'],
                    'remaining_credits': remaining_credits,
                    'min_credits': min_required_credits,
                    'warning': warning,
                },
            }


# ==========================================================================
# 5. WEEKLY GRID TIMETABLE (StudentScheduleModel)
# ==========================================================================
class StudentScheduleModel:
    @staticmethod
    def week_info(semester, week=None, today=None):
        """Calculate week index, start date (Monday), and end date (Sunday) for the week."""
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
            raise StudentValidationError("Invalid week number.")
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
        semester = StudentLookupModel.get_semester_by_id(semester_id)
        if not semester:
            raise StudentNotFoundError("Semester not found.", 404)

        info = StudentScheduleModel.week_info(semester, week, today)
        enrolled_classes = StudentCourseModel.get_registered_classes(student_id, semester_id)
        slots = StudentLookupModel.get_time_slots()

        sessions = []
        for c in enrolled_classes:
            session_date = info['week_start'] + timedelta(days=c['DayOfWeek'] - 2)
            item = dict(c)
            item['SessionDate'] = session_date
            sessions.append(item)

        # Days displayed in the selected week
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
# 6. AUTOMATED TUITION CALCULATION (StudentTuitionModel)
# ==========================================================================
class StudentTuitionModel:
    @staticmethod
    def recalculate_tuition(student_id, semester_id, cursor=None):
        """
        Recalculate the student's tuition for the semester:
          TotalCredits = SUM(Credits of currently Enrolled classes)
          TotalAmount = TotalCredits * CreditUnitPrice
        """
        def _do_calc(cur):
            # Fetch per-credit unit price for the semester
            sem = _fetch_one(
                cur,
                "/* q:student_tuition_get_unit_price */ SELECT CreditUnitPrice FROM dbo.Semesters WHERE Id = ?",
                (semester_id,),
            )
            unit_price = Decimal(str(sem['CreditUnitPrice'])) if sem and sem.get('CreditUnitPrice') else Decimal(str(DEFAULT_CREDIT_PRICE))

            # Sum currently enrolled credits
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

            # Check if a Tuitions record already exists
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
        Detailed tuition statement for the student in the semester:
- Total registered courses
- Total credits
- Per-credit unit price
- Total tuition amount
- Itemized list of courses & subtotals
        """
        # Ensure up-to-date calculation
        StudentTuitionModel.recalculate_tuition(student_id, semester_id)

        semester = StudentLookupModel.get_semester_by_id(semester_id)
        if not semester:
            raise StudentNotFoundError("Semester not found.", 404)

        unit_price = Decimal(str(semester.get('CreditUnitPrice') or DEFAULT_CREDIT_PRICE))

        # Fetch summary record from Tuitions
        tuition_record = Database.query_one(
            """
            /* q:student_tuition_statement_summary */
            SELECT Id, StudentId, SemesterId, TotalCredits, UnitPrice, PaidAmount, PaymentStatus, LastCalculatedAt
            FROM dbo.Tuitions
            WHERE StudentId = ? AND SemesterId = ?
            """,
            (student_id, semester_id),
        )

        # Fetch currently enrolled courses
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
# 7. REGISTRATION AUDIT LOG (StudentHistoryModel)
# ==========================================================================
class StudentHistoryModel:
    @staticmethod
    def get_history(student_id, semester_id=None, filter_type='all'):
        """
        Look up the student's full course registration & drop history.
        Filters: 'all', 'registered' (Register), 'canceled' (Drop).
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
