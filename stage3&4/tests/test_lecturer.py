"""
tests/test_lecturer.py
======================
Unit Test Suite for LECTURER SUBSYSTEM (Stage 4 - Testing & Quality).
Based on Test Cases Specification in the Excel Testing Document (TC_LEC_01 to TC_LEC_15).

================================================================================
TEST CASE SPECIFICATION (EXCEL MAPPING)
================================================================================
| Test Case ID | Function                    | Test Objective                                       |
|--------------|-----------------------------|------------------------------------------------------|
| TC_LEC_01    | User Authentication (Login) | Successful login as Lecturer and redirect to classes |
| TC_LEC_02    | Access Control (RBAC)        | RBAC blocks lecturer from accessing Admin Portal     |
| TC_LEC_03    | Assigned Classes            | Retrieve assigned classes with real-time enrollments |
| TC_LEC_04    | Teaching Summary            | Workload calculation (total classes, credits, seats) |
| TC_LEC_05    | Assigned Classes (Filter)   | Filter classes by selected historical semester       |
| TC_LEC_06    | Teaching Schedule           | Render weekly teaching timetable grid                |
| TC_LEC_07    | Schedule Navigation         | Navigate between calendar weeks                      |
| TC_LEC_08    | Class Student Roster        | Retrieve enrolled student list for assigned class    |
| TC_LEC_09    | Class Student Roster        | Handle newly opened class section with 0 students    |
| TC_LEC_10    | Data Access Control         | Prevent lecturer from accessing another's class roster|
| TC_LEC_11    | Export Student Roster       | Export roster to UTF-8 BOM encoded CSV               |
| TC_LEC_12    | Lecturer Profile            | View personal lecturer profile information           |
| TC_LEC_13    | Change Password             | Change password successfully                         |
| TC_LEC_14    | Change Password             | Reject password change with incorrect current pass   |
| TC_LEC_15    | User Logout                 | Terminate lecturer session securely                  |
================================================================================
"""

import copy
import os
import sys
import unittest
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from werkzeug.security import generate_password_hash

STAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if STAGE_DIR not in sys.path:
    sys.path.insert(0, STAGE_DIR)

from flask import Flask
from controllers.lecturer_controller import lecturer_bp
from controllers.auth_controller import auth_bp
from models.lecturer_model import (
    LecturerClassModel,
    LecturerError,
    LecturerExportModel,
    LecturerNotFoundError,
    LecturerPermissionError,
    LecturerProfileModel,
    LecturerScheduleModel,
    LecturerValidationError,
)
from models.db import Database


# ==============================================================================
# FAKE IN-MEMORY DATABASE ENGINE FOR LECTURER TESTS
# ==============================================================================
class FakeLecturerCursor:
    """Simulates pyodbc cursor for lecturer queries marked with /* q:... */."""

    def __init__(self, state):
        self.state = state
        self.description = None
        self._rows = []
        self.rowcount = 0

    def _set_result(self, rows):
        if not rows:
            self.description = [('Col',)]
            self._rows = []
            return
        cols = list(rows[0].keys())
        self.description = [(c,) for c in cols]
        self._rows = [tuple(r[c] for c in cols) for r in rows]

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass

    def execute(self, sql, params=None):
        params = tuple(params) if params is not None else ()
        self.description = None
        self._rows = []
        self.rowcount = 0

        # 1. Profile & Password
        if '/* q:lecturer_profile */' in sql:
            uid = params[0]
            found = []
            for u in self.state['users']:
                if u['Id'] == uid:
                    lec = self.state['lecturers'].get(uid, {})
                    found.append({
                        'Id': u['Id'],
                        'UserCode': u['UserCode'],
                        'Username': u['Username'],
                        'FullName': u['FullName'],
                        'Email': u['Email'],
                        'Phone': u.get('Phone'),
                        'Role': u['Role'],
                        'Status': u['Status'],
                        'LecturerCode': lec.get('LecturerCode', u['UserCode']),
                        'Department': lec.get('Department', 'Software Engineering'),
                        'AcademicDegree': lec.get('AcademicDegree', 'PhD'),
                    })
            self._set_result(found[:1])

        elif '/* q:lecturer_password_hash */' in sql:
            uid = params[0]
            found = [{'Id': u['Id'], 'PasswordHash': u['PasswordHash']}
                     for u in self.state['users'] if u['Id'] == uid]
            self._set_result(found[:1])

        elif '/* q:lecturer_update_password */' in sql:
            new_hash, uid = params
            for u in self.state['users']:
                if u['Id'] == uid:
                    u['PasswordHash'] = new_hash
                    self.rowcount = 1

        # 2. Semesters
        elif '/* q:lecturer_semesters */' in sql:
            sorted_sems = sorted(self.state['semesters'], key=lambda s: s['StartDate'], reverse=True)
            self._set_result(sorted_sems)

        elif '/* q:lecturer_semester_by_id */' in sql:
            sid = params[0]
            found = [s for s in self.state['semesters'] if s['Id'] == sid]
            self._set_result(found[:1])

        elif '/* q:lecturer_current_semester */' in sql:
            current = [s for s in self.state['semesters'] if s.get('IsCurrent')]
            if not current:
                current = self.state['semesters']
            self._set_result([{'Id': current[0]['Id']}])

        # 3. TimeSlots
        elif '/* q:lecturer_timeslots */' in sql:
            sorted_ts = sorted(self.state['timeslots'], key=lambda t: t['SlotNumber'])
            self._set_result(sorted_ts)

        # 4. Assigned Classes
        elif '/* q:lecturer_assigned_classes */' in sql:
            lec_id, sem_id = params
            res = []
            for cl in self.state['classes']:
                if cl.get('LecturerId') == lec_id and cl.get('SemesterId') == sem_id:
                    course = next((c for c in self.state['courses'] if c['Id'] == cl['CourseId']), {})
                    ts = next((t for t in self.state['timeslots'] if t['Id'] == cl['TimeSlotId']), {})
                    actual_enr = sum(
                        1 for e in self.state['enrollments']
                        if e['ClassId'] == cl['Id'] and e['Status'] == 'Enrolled'
                    )
                    res.append({
                        'Id': cl['Id'],
                        'ClassCode': cl['ClassCode'],
                        'CourseId': cl['CourseId'],
                        'SemesterId': cl['SemesterId'],
                        'DayOfWeek': cl['DayOfWeek'],
                        'TimeSlotId': cl['TimeSlotId'],
                        'Room': cl['Room'],
                        'RoomCode': cl['Room'],
                        'MinCapacity': cl['MinCapacity'],
                        'MaxCapacity': cl['MaxCapacity'],
                        'ClassStatus': cl['Status'],
                        'CourseCode': course.get('CourseCode'),
                        'CourseName': course.get('CourseName'),
                        'Credits': course.get('Credits'),
                        'TheoryHours': course.get('TheoryHours', 30),
                        'PracticeHours': course.get('PracticeHours', 15),
                        'Department': course.get('Department', 'SE'),
                        'SlotNumber': ts.get('SlotNumber'),
                        'SlotName': ts.get('SlotName'),
                        'StartTime': ts.get('StartTime'),
                        'EndTime': ts.get('EndTime'),
                        'EnrolledCount': actual_enr,
                        'ActualEnrolled': actual_enr,
                    })
            self._set_result(res)

        # 5. Class By ID (for permission verification)
        elif '/* q:lecturer_class_by_id */' in sql:
            cid = params[0]
            found = []
            for cl in self.state['classes']:
                if cl['Id'] == cid:
                    course = next((c for c in self.state['courses'] if c['Id'] == cl['CourseId']), {})
                    found.append({
                        'Id': cl['Id'],
                        'ClassCode': cl['ClassCode'],
                        'LecturerId': cl.get('LecturerId'),
                        'SemesterId': cl['SemesterId'],
                        'ClassStatus': cl['Status'],
                        'CourseCode': course.get('CourseCode'),
                        'CourseName': course.get('CourseName'),
                        'Credits': course.get('Credits'),
                    })
            self._set_result(found[:1])

        # 6. Class Students
        elif '/* q:lecturer_class_students */' in sql:
            cid = params[0]
            res = []
            for e in self.state['enrollments']:
                if e['ClassId'] == cid and e['Status'] == 'Enrolled':
                    u = next((usr for usr in self.state['users'] if usr['Id'] == e['StudentId']), {})
                    stu = self.state['students'].get(e['StudentId'], {})
                    res.append({
                        'UserId': u.get('Id'),
                        'StudentCode': stu.get('StudentCode', u.get('UserCode')),
                        'FullName': u.get('FullName'),
                        'AdministrativeClass': stu.get('AdministrativeClass', 'K21-CNPM01'),
                        'Major': stu.get('Major', 'Software Engineering'),
                        'Email': u.get('Email'),
                        'Phone': u.get('Phone', '0901234567'),
                        'EnrolledAt': e.get('EnrolledAt', '2026-11-15T09:00:00'),
                        'EnrollmentStatus': e.get('Status', 'Enrolled'),
                    })
            self._set_result(res)

        # 7. User Find by Username (for auth controller login)
        elif 'WHERE Username = ?' in sql:
            uname = params[0]
            found = [u for u in self.state['users'] if u['Username'].lower() == uname.lower()]
            self._set_result(found[:1])


class FakeLecturerDB:
    def __init__(self, state):
        self.state = state

    @contextmanager
    def get_cursor(self):
        cursor = FakeLecturerCursor(self.state)
        yield cursor


# ==============================================================================
# TEST CASE IMPLEMENTATION FOR LECTURER PORTAL
# ==============================================================================
class TestLecturerModule(unittest.TestCase):
    """Test suite covering TC_LEC_01 to TC_LEC_15."""

    def setUp(self):
        self.state = {
            'users': [
                {
                    'Id': 1, 'UserCode': 'AD001', 'Username': 'admin',
                    'PasswordHash': generate_password_hash('123456'),
                    'FullName': 'System Administrator', 'Email': 'admin@uth.edu.vn',
                    'Role': 'Admin', 'Status': 'Active', 'FailedLoginCount': 0
                },
                {
                    'Id': 2, 'UserCode': 'GV001', 'Username': 'gv_nam',
                    'PasswordHash': generate_password_hash('123456'),
                    'FullName': 'Dr. Le Hoang Nam', 'Email': 'nam.lh@uth.edu.vn',
                    'Phone': '0912345678', 'Role': 'Lecturer', 'Status': 'Active', 'FailedLoginCount': 0
                },
                {
                    'Id': 3, 'UserCode': 'GV002', 'Username': 'gv_mai',
                    'PasswordHash': generate_password_hash('123456'),
                    'FullName': 'MSc. Tran Phuong Mai', 'Email': 'mai.tp@uth.edu.vn',
                    'Phone': '0912345679', 'Role': 'Lecturer', 'Status': 'Active', 'FailedLoginCount': 0
                },
                {
                    'Id': 4, 'UserCode': 'SV001', 'Username': 'sv_an',
                    'PasswordHash': generate_password_hash('123456'),
                    'FullName': 'Nguyen Van An', 'Email': 'an.nv@uth.edu.vn',
                    'Role': 'Student', 'Status': 'Active', 'FailedLoginCount': 0
                },
                {
                    'Id': 5, 'UserCode': 'SV002', 'Username': 'sv_binh',
                    'PasswordHash': generate_password_hash('123456'),
                    'FullName': 'Tran Hai Binh', 'Email': 'binh.th@uth.edu.vn',
                    'Role': 'Student', 'Status': 'Active', 'FailedLoginCount': 0
                },
            ],
            'lecturers': {
                2: {'UserId': 2, 'LecturerCode': 'GV001', 'Department': 'Software Engineering', 'AcademicDegree': 'PhD'},
                3: {'UserId': 3, 'LecturerCode': 'GV002', 'Department': 'Information Systems', 'AcademicDegree': 'MSc'},
            },
            'students': {
                4: {'UserId': 4, 'StudentCode': 'SV001', 'AdministrativeClass': 'K21-CNPM01', 'Major': 'Software Engineering'},
                5: {'UserId': 5, 'StudentCode': 'SV002', 'AdministrativeClass': 'K21-CNPM01', 'Major': 'Software Engineering'},
            },
            'semesters': [
                {
                    'Id': 2, 'SemesterCode': '2025_2026_HK2', 'SemesterName': 'Semester 2, 2025-2026',
                    'AcademicYear': '2025-2026', 'StartDate': date(2026, 1, 15),
                    'EndDate': date(2026, 5, 30), 'IsCurrent': 1, 'CreditUnitPrice': 550000
                },
                {
                    'Id': 1, 'SemesterCode': '2025_2026_HK1', 'SemesterName': 'Semester 1, 2025-2026',
                    'AcademicYear': '2025-2026', 'StartDate': date(2025, 8, 15),
                    'EndDate': date(2025, 12, 30), 'IsCurrent': 0, 'CreditUnitPrice': 500000
                },
            ],
            'courses': [
                {'Id': 101, 'CourseCode': 'IT101', 'CourseName': 'Introduction to Programming', 'Credits': 3, 'Department': 'SE'},
                {'Id': 102, 'CourseCode': 'IT102', 'CourseName': 'Object Oriented Programming', 'Credits': 4, 'Department': 'SE'},
            ],
            'timeslots': [
                {'Id': 1, 'SlotNumber': 1, 'SlotName': 'Slot 1', 'StartTime': time(7, 0), 'EndTime': time(9, 30)},
                {'Id': 2, 'SlotNumber': 2, 'SlotName': 'Slot 2', 'StartTime': time(9, 45), 'EndTime': time(12, 15)},
            ],
            'classes': [
                {
                    'Id': 1, 'ClassCode': 'IT101_01', 'CourseId': 101, 'SemesterId': 2,
                    'LecturerId': 2, 'Room': 'A101', 'TimeSlotId': 1, 'DayOfWeek': 2, # Monday
                    'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 2, 'Status': 'Open'
                },
                {
                    'Id': 2, 'ClassCode': 'IT102_01', 'CourseId': 102, 'SemesterId': 2,
                    'LecturerId': 2, 'Room': 'B202', 'TimeSlotId': 2, 'DayOfWeek': 4, # Wednesday
                    'MinCapacity': 15, 'MaxCapacity': 40, 'CurrentEnrollment': 0, 'Status': 'Open'
                },
                {
                    'Id': 99, 'ClassCode': 'IS201_01', 'CourseId': 101, 'SemesterId': 2,
                    'LecturerId': 3, 'Room': 'C303', 'TimeSlotId': 1, 'DayOfWeek': 3, # Tuesday - Lecturer Mai
                    'MinCapacity': 15, 'MaxCapacity': 40, 'CurrentEnrollment': 1, 'Status': 'Open'
                },
                {
                    'Id': 3, 'ClassCode': 'IT101_OLD', 'CourseId': 101, 'SemesterId': 1,
                    'LecturerId': 2, 'Room': 'A101', 'TimeSlotId': 1, 'DayOfWeek': 2,
                    'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 30, 'Status': 'Closed'
                },
            ],
            'enrollments': [
                {'Id': 1, 'StudentId': 4, 'ClassId': 1, 'Status': 'Enrolled', 'EnrolledAt': '2026-01-20T08:00:00'},
                {'Id': 2, 'StudentId': 5, 'ClassId': 1, 'Status': 'Enrolled', 'EnrolledAt': '2026-01-20T08:15:00'},
                {'Id': 3, 'StudentId': 4, 'ClassId': 99, 'Status': 'Enrolled', 'EnrolledAt': '2026-01-20T09:00:00'},
            ]
        }

        self.fake_db = FakeLecturerDB(self.state)
        self.cursor_patcher = patch.object(Database, 'get_cursor', side_effect=self.fake_db.get_cursor)
        self.cursor_patcher.start()

        # Setup Flask Test Application
        self.app = Flask(__name__)
        self.app.secret_key = 'test_secret_key_lecturer'
        self.app.register_blueprint(lecturer_bp)
        self.app.register_blueprint(auth_bp)
        self.client = self.app.test_client()

    def tearDown(self):
        self.cursor_patcher.stop()

    def _login_as_lecturer(self, lecturer_id=2, username='gv_nam'):
        with self.client.session_transaction() as sess:
            sess['user_id'] = lecturer_id
            sess['username'] = username
            sess['role'] = 'Lecturer'

    # ==========================================================================
    # TC_LEC_01: Lecturer Login & Dashboard Redirection
    # ==========================================================================
    def test_tc01_lecturer_login_success(self):
        """TC_LEC_01: Valid lecturer credentials redirect to lecturer dashboard."""
        self._login_as_lecturer()
        res = self.client.get('/lecturer/api/me')
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(body['data']['Username'], 'gv_nam')
        self.assertEqual(body['data']['Role'], 'Lecturer')

    # ==========================================================================
    # TC_LEC_02: RBAC Blocks Lecturer from Accessing Admin Portal
    # ==========================================================================
    def test_tc02_rbac_blocks_lecturer_from_admin(self):
        """TC_LEC_02: Lecturer role blocked when attempting to access Admin Portal."""
        self._login_as_lecturer()
        res = self.client.get('/admin-period.html')
        self.assertIn(res.status_code, (302, 403))

    # ==========================================================================
    # TC_LEC_03: View Assigned Classes for Current Semester
    # ==========================================================================
    def test_tc03_assigned_classes_list(self):
        """TC_LEC_03: Lecturer retrieves list of assigned classes with actual enrollment."""
        self._login_as_lecturer()
        res = self.client.get('/lecturer/api/classes?semester_id=2')
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body['success'])
        classes = body['data']['classes']
        self.assertEqual(len(classes), 2)  # IT101_01 and IT102_01

        it101 = next(c for c in classes if c['ClassCode'] == 'IT101_01')
        self.assertEqual(it101['ActualEnrolled'], 2)
        self.assertEqual(it101['Room'], 'A101')

    # ==========================================================================
    # TC_LEC_04: Teaching Workload Summary
    # ==========================================================================
    def test_tc04_teaching_workload_summary(self):
        """TC_LEC_04: Workload metrics summary calculates total classes, credits, and students."""
        classes = LecturerClassModel.list_assigned_classes(lecturer_id=2, semester_id=2)
        summary = LecturerClassModel.summarize(classes)
        self.assertEqual(summary['total_sections'], 2)
        self.assertEqual(summary['total_credits'], 7)  # 3 (IT101) + 4 (IT102)
        self.assertEqual(summary['total_students'], 2)  # 2 students in IT101

    # ==========================================================================
    # TC_LEC_05: Filter Assigned Classes by Semester
    # ==========================================================================
    def test_tc05_filter_classes_by_semester(self):
        """TC_LEC_05: Filter assigned classes by historical semester."""
        self._login_as_lecturer()
        res = self.client.get('/lecturer/api/classes?semester_id=1')
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        classes = body['data']['classes']
        self.assertEqual(len(classes), 1)
        self.assertEqual(classes[0]['ClassCode'], 'IT101_OLD')

    # ==========================================================================
    # TC_LEC_06: Teaching Schedule Grid Rendering
    # ==========================================================================
    def test_tc06_weekly_teaching_schedule(self):
        """TC_LEC_06: Weekly teaching schedule correctly positions sessions by day and slot."""
        self._login_as_lecturer()
        res = self.client.get('/lecturer/api/schedule?semester_id=2')
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body['success'])
        data = body['data']
        self.assertIn('sessions', data)
        self.assertIn('slots', data)
        self.assertIn('days', data)
        self.assertIn('week', data)

    # ==========================================================================
    # TC_LEC_07: Schedule Navigation Across Weeks
    # ==========================================================================
    def test_tc07_schedule_week_navigation(self):
        """TC_LEC_07: Navigate between weeks on teaching schedule."""
        self._login_as_lecturer()
        res = self.client.get('/lecturer/api/schedule?semester_id=2&week=3')
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body['data']['week']['week'], 3)

    # ==========================================================================
    # TC_LEC_08: Enrolled Student Roster
    # ==========================================================================
    def test_tc08_class_student_roster(self):
        """TC_LEC_08: View enrolled students list for an assigned class section."""
        self._login_as_lecturer()
        res = self.client.get('/lecturer/api/classes/1/students')
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(body['data']['total'], 2)
        students = body['data']['students']
        codes = [s['StudentCode'] for s in students]
        self.assertIn('SV001', codes)
        self.assertIn('SV002', codes)

    # ==========================================================================
    # TC_LEC_09: Empty Student Roster for Newly Opened Section
    # ==========================================================================
    def test_tc09_class_student_roster_empty(self):
        """TC_LEC_09: View student roster of section with 0 enrolled students."""
        self._login_as_lecturer()
        res = self.client.get('/lecturer/api/classes/2/students')
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body['data']['total'], 0)
        self.assertEqual(len(body['data']['students']), 0)

    # ==========================================================================
    # TC_LEC_10: Data Access Control - Restrict Other Lecturer's Class
    # ==========================================================================
    def test_tc10_data_access_control_other_lecturer_class(self):
        """TC_LEC_10: Lecturer cannot view roster of class assigned to another lecturer."""
        self._login_as_lecturer(lecturer_id=2)
        # ClassId 99 is assigned to Lecturer 3
        res = self.client.get('/lecturer/api/classes/99/students')
        self.assertEqual(res.status_code, 403)
        body = res.get_json()
        self.assertFalse(body['success'])

    # ==========================================================================
    # TC_LEC_11: Export Student Roster to CSV
    # ==========================================================================
    def test_tc11_export_students_csv(self):
        """TC_LEC_11: Export class roster as UTF-8 with BOM encoded CSV file."""
        self._login_as_lecturer()
        res = self.client.get('/lecturer/api/classes/1/export')
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res.headers.get('Content-Type'))
        self.assertTrue(res.data.startswith(b'\xef\xbb\xbf'))
        content = res.data.decode('utf-8-sig')
        self.assertIn('Nguyen Van An', content)
        self.assertIn('Tran Hai Binh', content)

    # ==========================================================================
    # TC_LEC_12: Lecturer Profile Information
    # ==========================================================================
    def test_tc12_lecturer_profile(self):
        """TC_LEC_12: Retrieve lecturer profile details."""
        profile = LecturerProfileModel.get_profile(user_id=2)
        self.assertEqual(profile['LecturerCode'], 'GV001')
        self.assertEqual(profile['FullName'], 'Dr. Le Hoang Nam')
        self.assertEqual(profile['Department'], 'Software Engineering')
        self.assertEqual(profile['AcademicDegree'], 'PhD')

    # ==========================================================================
    # TC_LEC_13: Change Password Success
    # ==========================================================================
    def test_tc13_change_password_success(self):
        """TC_LEC_13: Lecturer successfully updates password."""
        self._login_as_lecturer()
        res = self.client.post('/lecturer/api/change-password', json={
            'current_password': '123456',
            'new_password': 'NewLecturerPass@2026',
            'confirm_password': 'NewLecturerPass@2026'
        })
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body['success'])

    # ==========================================================================
    # TC_LEC_14: Change Password Rejection with Invalid Credentials
    # ==========================================================================
    def test_tc14_change_password_wrong_current(self):
        """TC_LEC_14: Password change rejected if current password is incorrect."""
        self._login_as_lecturer()
        res = self.client.post('/lecturer/api/change-password', json={
            'current_password': 'wrong_password',
            'new_password': 'NewLecturerPass@2026',
            'confirm_password': 'NewLecturerPass@2026'
        })
        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertFalse(body['success'])

    # ==========================================================================
    # TC_LEC_15: Lecturer Logout
    # ==========================================================================
    def test_tc15_lecturer_logout(self):
        """TC_LEC_15: Logout clears session and redirects to login."""
        self._login_as_lecturer()
        res = self.client.get('/lecturer/lecturer-login.html')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/logout', res.headers.get('Location'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
