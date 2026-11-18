"""
tests/test_admin.py
===================
Unit Test Suite for ADMINISTRATOR SUBSYSTEM (Stage 4 - Testing & Quality).
Based strictly on the Excel Testing Document (TC_ADM_01 to TC_ADM_28).

================================================================================
TEST CASE SPECIFICATION (EXCEL MAPPING - SHEET: Administrator Subsystem)
================================================================================
| Test Case ID | Feature / Module            | Test Objective                                       |
|--------------|-----------------------------|------------------------------------------------------|
| TC_ADM_01    | User Authentication (Login) | Admin logs in successfully with valid credentials    |
| TC_ADM_02    | API Security & Auth         | Unauthenticated API requests rejected with HTTP 401  |
| TC_ADM_03    | Role-Based Access Control   | Non-admin roles (Student) blocked with HTTP 403      |
| TC_ADM_04    | User Account Management     | View list of system user accounts (Admin, GV, SV)   |
| TC_ADM_05    | Create Student Account      | Create new student account with hashed password      |
| TC_ADM_06    | Create Lecturer Account     | Create new lecturer account with role 'Lecturer'     |
| TC_ADM_07    | Create User Account         | Reject duplicate username with HTTP 409 Conflict     |
| TC_ADM_08    | Update User Account         | Update user account profile (Name, Email, Phone)     |
| TC_ADM_09    | Lock User Account           | Change account status to 'Locked'                    |
| TC_ADM_10    | Unlock User Account         | Restore account status to 'Active', reset failed cnt |
| TC_ADM_11    | Create Course               | Create course with valid prerequisite course         |
| TC_ADM_12    | Create Course               | Reject duplicate course code with HTTP 409 Conflict  |
| TC_ADM_13    | Update Course Prerequisites | Prevent circular prerequisite dependency loops       |
| TC_ADM_14    | Delete Course               | Delete course that has no active class sections      |
| TC_ADM_15    | Open Class Section          | Open class section successfully with valid schedule  |
| TC_ADM_16    | Open Class Section          | Reject class section due to room booking conflict    |
| TC_ADM_17    | Open Class Section          | Reject class section due to lecturer schedule clash  |
| TC_ADM_18    | Cancel Class Section        | Cancel under-enrolled class (< 15 SV) & cancel enrs  |
| TC_ADM_19    | Cancel Class Section        | Reject cancellation of viable class (>= 15 SV)       |
| TC_ADM_20    | Cancel Class Section        | Rollback transaction if enrollment update fails      |
| TC_ADM_21    | Registration Period Mgmt    | Create and activate new registration period          |
| TC_ADM_22    | Registration Period Mgmt    | Reject invalid period dates (EndDate <= StartDate)   |
| TC_ADM_23    | Registration Period Mgmt    | Close active registration period (IsActive = 0)      |
| TC_ADM_24    | Manual Enrollment Override  | Admin manually force registers student into class    |
| TC_ADM_25    | Manual Enrollment Override  | Admin manually force drops student from class        |
| TC_ADM_26    | Registration Reports        | Generate section fill-rate viability report          |
| TC_ADM_27    | Registration Reports        | Generate student credit compliance statistics report |
| TC_ADM_28    | Account & Security          | Admin logout terminates session and redirects        |
================================================================================
"""

import copy
import os
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from models.user_model import UserModel

# Đảm bảo import được các module trong thư mục stage3&4
STAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if STAGE_DIR not in sys.path:
    sys.path.insert(0, STAGE_DIR)

from flask import Flask
from controllers.admin_controller import admin_bp
from models.admin_model import (
    AdminClassModel,
    AdminConflictError,
    AdminCourseModel,
    AdminEnrollmentModel,
    AdminNotFoundError,
    AdminPeriodModel,
    AdminReportModel,
    AdminUserModel,
    AdminValidationError,
)
from models.db import Database


# ==========================================================================
# FAKE IN-MEMORY SQL SERVER ENGINE (Phục vụ Unit Test độc lập, hỗ trợ Transaction)
# ==========================================================================
class FakeCursor:
    """Mô phỏng pyodbc Cursor dựa trên tag /* q:... */ trong câu lệnh SQL."""

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

    def execute(self, sql, params=None):
        params = tuple(params) if params is not None else ()
        self.description = None
        self._rows = []
        self.rowcount = 0

        # Cho phép test tiêm lỗi để kiểm tra rollback transaction
        if self.state.get('fail_on_tag') and self.state['fail_on_tag'] in sql:
            raise RuntimeError('Simulated database failure inside transaction')

        # --- USERS ---
        if '/* q:user_duplicate */' in sql:
            code, username, email = params
            found = [
                u for u in self.state['users']
                if u['UserCode'].upper() == code.upper()
                or u['Username'].lower() == username.lower()
                or u['Email'].lower() == email.lower()
            ]
            self._set_result(found[:1])
        elif '/* q:insert_user */' in sql:
            code, username, pw_hash, full_name, email, phone, role = params
            new_id = max((u['Id'] for u in self.state['users']), default=0) + 1
            self.state['users'].append({
                'Id': new_id, 'UserCode': code, 'Username': username,
                'PasswordHash': pw_hash, 'FullName': full_name, 'Email': email,
                'Phone': phone, 'Role': role, 'Status': 'Active',
                'FailedLoginCount': 0, 'CreatedAt': '2026-11-13T08:00:00',
            })
            self._set_result([{'Id': new_id}])
        elif '/* q:insert_student */' in sql:
            user_id, code, admin_class, major, year = params
            self.state['students'][user_id] = {
                'UserId': user_id, 'StudentCode': code,
                'AdministrativeClass': admin_class, 'Major': major, 'EnrollmentYear': year,
            }
            self.rowcount = 1
        elif '/* q:insert_lecturer */' in sql:
            user_id, code, dept, degree = params
            self.state['lecturers'][user_id] = {
                'UserId': user_id, 'LecturerCode': code,
                'Department': dept, 'AcademicDegree': degree,
            }
            self.rowcount = 1
        elif '/* q:user_by_id */' in sql or '/* q:user_for_status */' in sql or '/* q:user_for_update */' in sql:
            user_id = params[0]
            found = []
            for u in self.state['users']:
                if u['Id'] == user_id:
                    item = dict(u)
                    stu = self.state['students'].get(user_id)
                    lec = self.state['lecturers'].get(user_id)
                    item['Department'] = (stu and stu['Major']) or (lec and lec['Department'])
                    found.append(item)
            self._set_result(found[:1])
        elif '/* q:unlock_user */' in sql:
            user_id = params[0]
            for u in self.state['users']:
                if u['Id'] == user_id:
                    u['Status'] = 'Active'
                    u['FailedLoginCount'] = 0
                    self.rowcount = 1
        elif '/* q:lock_user */' in sql:
            user_id = params[0]
            for u in self.state['users']:
                if u['Id'] == user_id:
                    u['Status'] = 'Locked'
                    self.rowcount = 1

        # --- COURSES ---
        elif '/* q:course_by_code */' in sql:
            code = params[0].upper()
            found = [c for c in self.state['courses'] if c['CourseCode'].upper() == code]
            self._set_result(found[:1])
        elif '/* q:course_by_id */' in sql or '/* q:course_for_update */' in sql or '/* q:course_for_delete */' in sql or '/* q:course_detail */' in sql:
            cid = params[0]
            found = [c for c in self.state['courses'] if c['Id'] == cid]
            self._set_result(found[:1])
        elif '/* q:course_code_duplicate */' in sql:
            code, exclude_id = params[0].upper(), params[1]
            found = [c for c in self.state['courses'] if c['CourseCode'].upper() == code and c['Id'] != exclude_id]
            self._set_result(found[:1])
        elif '/* q:course_prereq_of */' in sql:
            cid = params[0]
            found = [{'PrerequisiteCourseId': c['PrerequisiteCourseId']} for c in self.state['courses'] if c['Id'] == cid]
            self._set_result(found[:1])
        elif '/* q:insert_course */' in sql:
            code, name, credits, theory, practice, dept, prereq = params
            new_id = max((c['Id'] for c in self.state['courses']), default=0) + 1
            self.state['courses'].append({
                'Id': new_id, 'CourseCode': code, 'CourseName': name, 'Credits': credits,
                'TheoryHours': theory, 'PracticeHours': practice, 'Department': dept,
                'PrerequisiteCourseId': prereq, 'IsActive': 1,
            })
            self._set_result([{'Id': new_id}])
        elif '/* q:update_course */' in sql:
            code, name, credits, theory, practice, dept, prereq, cid = params
            for c in self.state['courses']:
                if c['Id'] == cid:
                    c.update({
                        'CourseCode': code, 'CourseName': name, 'Credits': credits,
                        'TheoryHours': theory, 'PracticeHours': practice,
                        'Department': dept, 'PrerequisiteCourseId': prereq,
                    })
                    self.rowcount = 1
        elif '/* q:delete_course_prereq */' in sql:
            cid = params[0]
            self.state['course_prereqs'] = [p for p in self.state['course_prereqs'] if p['CourseId'] != cid]
        elif '/* q:insert_course_prereq */' in sql:
            cid, prereq_id = params
            self.state['course_prereqs'].append({'CourseId': cid, 'PrerequisiteCourseId': prereq_id, 'IsMandatory': 1})

        # --- CLASSES & CANCELLATION ---
        elif '/* q:class_by_code */' in sql:
            code = params[0].upper()
            found = [cl for cl in self.state['classes'] if cl['ClassCode'].upper() == code]
            self._set_result(found[:1])
        elif '/* q:semester_by_id */' in sql:
            sid = params[0]
            found = [s for s in self.state['semesters'] if s['Id'] == sid]
            self._set_result(found[:1])
        elif '/* q:timeslot_by_id */' in sql:
            tid = params[0]
            found = [t for t in self.state['timeslots'] if t['Id'] == tid]
            self._set_result(found[:1])
        elif '/* q:lecturer_lookup */' in sql:
            if len(params) == 1:
                lid = params[0]
                found = [u for u in self.state['users'] if u['Id'] == lid and u['Role'] == 'Lecturer']
            else:
                code1, code2, ref = params
                found = [
                    u for u in self.state['users']
                    if u['Role'] == 'Lecturer' and (
                        u['UserCode'].upper() == code1.upper()
                        or u['FullName'].lower() == ref.lower()
                    )
                ]
            self._set_result(found[:1])
        elif '/* q:classroom_by_code */' in sql:
            room = params[0].upper()
            found = [r for r in self.state['classrooms'] if r['RoomCode'].upper() == room]
            self._set_result(found[:1])
        elif '/* q:room_conflict */' in sql:
            sem_id, day, slot_id, room, classroom_id = params
            found = [
                cl for cl in self.state['classes']
                if cl['SemesterId'] == sem_id
                and cl['DayOfWeek'] == day
                and cl['TimeSlotId'] == slot_id
                and cl['Status'] != 'Cancelled'
                and (cl['Room'].upper() == room.upper()
                     or (classroom_id is not None and cl.get('ClassroomId') == classroom_id))
            ]
            self._set_result(found[:1])
        elif '/* q:lecturer_conflict */' in sql:
            sem_id, day, slot_id, lecturer_id = params
            found = [
                cl for cl in self.state['classes']
                if cl['SemesterId'] == sem_id
                and cl['DayOfWeek'] == day
                and cl['TimeSlotId'] == slot_id
                and cl['Status'] != 'Cancelled'
                and cl['LecturerId'] == lecturer_id
            ]
            self._set_result(found[:1])
        elif '/* q:insert_class */' in sql:
            code, cid, sem_id, lec_id, room_id, room, slot_id, day, min_cap, max_cap = params
            new_id = max((cl['Id'] for cl in self.state['classes']), default=0) + 1
            self.state['classes'].append({
                'Id': new_id, 'ClassCode': code, 'CourseId': cid, 'SemesterId': sem_id,
                'LecturerId': lec_id, 'ClassroomId': room_id, 'Room': room,
                'TimeSlotId': slot_id, 'DayOfWeek': day, 'MinCapacity': min_cap,
                'MaxCapacity': max_cap, 'CurrentEnrollment': 0, 'Status': 'Open',
            })
            self._set_result([{'Id': new_id}])
        elif '/* q:class_for_cancel */' in sql:
            class_id = params[0]
            found = [cl for cl in self.state['classes'] if cl['Id'] == class_id]
            self._set_result(found[:1])
        elif '/* q:class_enrolled_students */' in sql:
            class_id = params[0]
            found = [
                {'StudentId': e['StudentId']}
                for e in self.state['enrollments']
                if e['ClassId'] == class_id and e['Status'] == 'Enrolled'
            ]
            self._set_result(found)
        elif '/* q:cancel_class */' in sql:
            class_id = params[0]
            for cl in self.state['classes']:
                if cl['Id'] == class_id:
                    cl['Status'] = 'Cancelled'
                    cl['CurrentEnrollment'] = 0
                    self.rowcount = 1
        elif '/* q:cancel_enrollments */' in sql:
            class_id = params[0]
            for e in self.state['enrollments']:
                if e['ClassId'] == class_id and e['Status'] == 'Enrolled':
                    e['Status'] = 'Cancelled'
                    e['CancelledAt'] = '2026-11-13T09:00:00'
                    self.rowcount += 1
        elif '/* q:insert_history */' in sql:
            stu_id, class_id, action_type, actor_id, note = params
            self.state['history'].append({
                'StudentId': stu_id, 'ClassId': class_id,
                'ActionType': action_type, 'PerformedByUserId': actor_id, 'Note': note,
            })
            self.rowcount = 1
        elif '/* q:recalc_tuition */' in sql:
            stu_id, sem_id = params
            self.state['tuition_recalcs'].append((stu_id, sem_id))

        # --- REGISTRATION PERIODS ---
        elif '/* q:deactivate_periods */' in sql:
            sem_id = params[0]
            for p in self.state['periods']:
                if p['SemesterId'] == sem_id and p['IsActive']:
                    p['IsActive'] = 0
        elif '/* q:insert_period */' in sql:
            sem_id, name, start, end, min_cr, max_cr = params
            new_id = max((p['Id'] for p in self.state['periods']), default=0) + 1
            self.state['periods'].append({
                'Id': new_id, 'SemesterId': sem_id, 'PeriodName': name,
                'StartDate': start, 'EndDate': end,
                'MinCredits': min_cr, 'MaxCredits': max_cr, 'IsActive': 1,
            })
            self._set_result([{'Id': new_id}])
        elif '/* q:list_classes */' in sql:
            sem_id = params[0] if params else None
            rows = []
            for cl in self.state['classes']:
                if sem_id and cl['SemesterId'] != sem_id:
                    continue
                co = next((c for c in self.state['courses'] if c['Id'] == cl['CourseId']), {})
                ts = next((t for t in self.state['timeslots'] if t['Id'] == cl['TimeSlotId']), {})
                lu = next((u for u in self.state['users'] if u['Id'] == cl['LecturerId']), {})
                rows.append({
                    **cl,
                    'CourseCode': co.get('CourseCode'),
                    'CourseName': co.get('CourseName'),
                    'Credits': co.get('Credits', 3),
                    'SemesterCode': 'SEM1_2026_2027',
                    'SemesterName': 'Semester 1 (2026-2027)',
                    'LecturerCode': lu.get('UserCode'),
                    'LecturerName': lu.get('FullName'),
                    'SlotNumber': ts.get('SlotNumber', 1),
                    'SlotName': ts.get('SlotName', ''),
                    'StartTime': ts.get('StartTime', ''),
                    'EndTime': ts.get('EndTime', ''),
                    'CreatedAt': '2026-09-01',
                })
            self._set_result(rows)
        elif '/* q:active_period */' in sql:
            sem_id = params[0]
            from datetime import datetime
            found = []
            for p in self.state['periods']:
                if p['SemesterId'] == sem_id and p['IsActive']:
                    found.append({
                        **p,
                        'SemesterCode': 'SEM1_2026_2027',
                        'SemesterName': 'Semester 1 (2026-2027)',
                        'StartDate': datetime(2026, 9, 1, 0, 0),
                        'EndDate': datetime(2026, 12, 31, 23, 59),
                    })
            self._set_result(found[:1])

        elif '/* q:list_users */' in sql:
            res = []
            for u in self.state['users']:
                if u.get('Role') in ('Student', 'Lecturer'):
                    stu = self.state['students'].get(u['Id'], {})
                    lec = self.state['lecturers'].get(u['Id'], {})
                    res.append({
                        'Id': u['Id'], 'UserCode': u['UserCode'], 'Username': u['Username'],
                        'FullName': u['FullName'], 'Email': u['Email'], 'Phone': u['Phone'],
                        'Role': u['Role'], 'Status': u['Status'], 'FailedLoginCount': u.get('FailedLoginCount', 0),
                        'PasswordHash': u.get('PasswordHash'), 'CreatedAt': '2026-01-01',
                        'Department': stu.get('Major') or lec.get('Department'),
                        'AdministrativeClass': stu.get('AdministrativeClass'),
                        'EnrollmentYear': stu.get('EnrollmentYear'),
                        'AcademicDegree': lec.get('AcademicDegree'),
                    })
            self._set_result(res)

        elif '/* q:course_for_delete */' in sql:
            cid = params[0]
            found = [c for c in self.state['courses'] if c['Id'] == cid and c.get('IsActive', 1)]
            self._set_result(found[:1])

        elif '/* q:course_usage */' in sql:
            cid = params[0]
            cnt = sum(1 for cl in self.state['classes'] if cl['CourseId'] == cid and cl['Status'] != 'Cancelled')
            self._set_result([{'OpenClasses': cnt, 'AllClasses': cnt, 'ActiveDependents': 0, 'AllDependents': 0, 'PrereqLinks': 0}])

        elif '/* q:hard_delete_course */' in sql or '/* q:soft_delete_course */' in sql:
            cid = params[0]
            self.state['courses'] = [c for c in self.state['courses'] if c['Id'] != cid]
            self.rowcount = 1

        elif '/* q:delete_course_prereq */' in sql:
            cid = params[0]
            self.state['course_prereqs'] = [p for p in self.state['course_prereqs'] if p['CourseId'] != cid]
            self.rowcount = 1

        elif '/* q:user_for_update */' in sql or '/* q:user_for_status */' in sql:
            uid = params[0]
            found = [u for u in self.state['users'] if u['Id'] == uid]
            self._set_result(found[:1])

        elif '/* q:email_duplicate */' in sql:
            em, uid = params
            found = [u for u in self.state['users'] if u['Email'].lower() == em.lower() and u['Id'] != uid]
            self._set_result(found[:1])

        elif '/* q:update_user */' in sql:
            fn, em, ph, uid = params
            for u in self.state['users']:
                if u['Id'] == uid:
                    u['FullName'] = fn
                    u['Email'] = em
                    u['Phone'] = ph
            self.rowcount = 1

        elif '/* q:update_student */' in sql or '/* q:update_lecturer */' in sql:
            self.rowcount = 1

        elif '/* q:unlock_user */' in sql:
            uid = params[0]
            for u in self.state['users']:
                if u['Id'] == uid:
                    u['Status'] = 'Active'
                    u['FailedLoginCount'] = 0
            self.rowcount = 1

        elif '/* q:lock_user */' in sql:
            uid = params[0]
            for u in self.state['users']:
                if u['Id'] == uid:
                    u['Status'] = 'Locked'
            self.rowcount = 1

        elif '/* q:insert_user */' in sql:
            code, username, pw_hash, fn, em, ph, role = params
            new_id = max((u['Id'] for u in self.state['users']), default=0) + 1
            self.state['users'].append({
                'Id': new_id, 'UserCode': code, 'Username': username, 'PasswordHash': pw_hash,
                'FullName': fn, 'Email': em, 'Phone': ph, 'Role': role, 'Status': 'Active',
                'FailedLoginCount': 0, 'CreatedAt': '2026-11-18'
            })
            self._set_result([{'Id': new_id}])

        elif '/* q:insert_student */' in sql:
            uid, code, aclass, dept, year = params
            self.state['students'][uid] = {
                'UserId': uid, 'StudentCode': code, 'AdministrativeClass': aclass,
                'Major': dept, 'EnrollmentYear': year
            }
            self.rowcount = 1

        elif '/* q:insert_lecturer */' in sql:
            uid, code, dept, degree = params
            self.state['lecturers'][uid] = {
                'UserId': uid, 'LecturerCode': code, 'Department': dept, 'AcademicDegree': degree
            }
            self.rowcount = 1

        elif '/* q:student_by_code */' in sql:
            code1, code2 = params
            found = []
            for u in self.state['users']:
                stu = self.state['students'].get(u['Id'], {})
                if u['UserCode'].upper() == code1.upper() or stu.get('StudentCode', '').upper() == code2.upper():
                    found.append({'Id': u['Id'], 'UserCode': u['UserCode'], 'FullName': u['FullName'], 'Status': u['Status']})
            self._set_result(found[:1])

        elif '/* q:class_by_code_for_override */' in sql:
            cc = params[0].upper()
            found = [cl for cl in self.state['classes'] if cl['ClassCode'].upper() == cc]
            self._set_result(found[:1])

        elif '/* q:enrollment_by_pair */' in sql:
            sid, cid = params
            found = [e for e in self.state['enrollments'] if e['StudentId'] == sid and e['ClassId'] == cid]
            self._set_result(found[:1])

        elif '/* q:same_course_enrolled */' in sql:
            sid, coid, semid, cid = params
            found = []
            for e in self.state['enrollments']:
                if e['StudentId'] == sid and e['Status'] == 'Enrolled':
                    cl = next((c for c in self.state['classes'] if c['Id'] == e['ClassId']), None)
                    if cl and cl['CourseId'] == coid and cl['SemesterId'] == semid and cl['Id'] != cid:
                        found.append({'ClassCode': cl['ClassCode']})
            self._set_result(found[:1])

        elif '/* q:insert_enrollment */' in sql:
            sid, cid = params
            new_id = max((e['Id'] for e in self.state['enrollments']), default=0) + 1
            self.state['enrollments'].append({'Id': new_id, 'StudentId': sid, 'ClassId': cid, 'Status': 'Enrolled', 'CancelledAt': None})
            self.rowcount = 1

        elif '/* q:increment_enrollment */' in sql:
            cid = params[0]
            for cl in self.state['classes']:
                if cl['Id'] == cid:
                    cl['CurrentEnrollment'] += 1
            self.rowcount = 1

        elif '/* q:cancel_single_enrollment */' in sql:
            eid = params[0]
            for e in self.state['enrollments']:
                if e['Id'] == eid:
                    e['Status'] = 'Cancelled'
            self.rowcount = 1

        elif '/* q:decrement_enrollment */' in sql:
            cid = params[0]
            for cl in self.state['classes']:
                if cl['Id'] == cid:
                    cl['CurrentEnrollment'] = max(0, cl['CurrentEnrollment'] - 1)
            self.rowcount = 1

        elif '/* q:period_by_id */' in sql:
            pid = params[0]
            found = [p for p in self.state['periods'] if p['Id'] == pid]
            self._set_result(found[:1])

        elif '/* q:set_period_active */' in sql:
            is_act, pid = params
            for p in self.state['periods']:
                if p['Id'] == pid:
                    p['IsActive'] = is_act
            self.rowcount = 1

        elif '/* q:student_report */' in sql:
            sem_id = params[0]
            rows = []
            for stu_id, stu in self.state['students'].items():
                u = next(u for u in self.state['users'] if u['Id'] == stu_id)
                enrolled = [
                    e for e in self.state['enrollments']
                    if e['StudentId'] == stu_id and e['Status'] == 'Enrolled'
                ]
                if not enrolled:
                    rows.append({
                        'StudentId': stu_id, 'UserCode': u['UserCode'], 'FullName': u['FullName'],
                        'StudentCode': stu['StudentCode'], 'Major': stu['Major'],
                        'AdministrativeClass': stu['AdministrativeClass'],
                        'ClassCode': None, 'CourseCode': None, 'Credits': None,
                    })
                for e in enrolled:
                    cl = next((c for c in self.state['classes'] if c['Id'] == e['ClassId']
                               and c['SemesterId'] == sem_id and c['Status'] != 'Cancelled'), None)
                    co = next((c for c in self.state['courses'] if cl and c['Id'] == cl['CourseId']), None)
                    rows.append({
                        'StudentId': stu_id, 'UserCode': u['UserCode'], 'FullName': u['FullName'],
                        'StudentCode': stu['StudentCode'], 'Major': stu['Major'],
                        'AdministrativeClass': stu['AdministrativeClass'],
                        'ClassCode': cl['ClassCode'] if cl else None,
                        'CourseCode': co['CourseCode'] if co else None,
                        'Credits': co['Credits'] if co else None,
                    })
            self._set_result(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeDatabase:
    """Bộ giả lập Database có cơ chế commit / rollback đúng như SQL Server."""

    def __init__(self):
        self.state = {
            'fail_on_tag': None,
            'users': [
                {'Id': 1, 'UserCode': 'ADM001', 'Username': 'admin', 'PasswordHash': generate_password_hash('123456'),
                 'FullName': 'System Administrator', 'Email': 'admin@uth.edu.vn', 'Phone': '0901000001',
                 'Role': 'Admin', 'Status': 'Active', 'FailedLoginCount': 0, 'CreatedAt': '2026-09-01'},
                {'Id': 2, 'UserCode': 'GV001', 'Username': 'gv_nam', 'PasswordHash': 'hash_gv1',
                 'FullName': 'Le Hoang Nam', 'Email': 'nam.lh@uth.edu.vn', 'Phone': '0901000002',
                 'Role': 'Lecturer', 'Status': 'Active', 'FailedLoginCount': 0, 'CreatedAt': '2026-09-01'},
                {'Id': 3, 'UserCode': 'GV002', 'Username': 'gv_mai', 'PasswordHash': 'hash_gv2',
                 'FullName': 'Tran Phuong Mai', 'Email': 'mai.ttp@uth.edu.vn', 'Phone': '0901000003',
                 'Role': 'Lecturer', 'Status': 'Active', 'FailedLoginCount': 0, 'CreatedAt': '2026-09-01'},
                {'Id': 4, 'UserCode': 'SV001', 'Username': 'sv_an', 'PasswordHash': 'hash_sv1',
                 'FullName': 'Nguyen Van An', 'Email': 'an.sv@uth.edu.vn', 'Phone': '0901000004',
                 'Role': 'Student', 'Status': 'Active', 'FailedLoginCount': 0, 'CreatedAt': '2026-09-01'},
                {'Id': 5, 'UserCode': 'SV002', 'Username': 'sv_binh', 'PasswordHash': 'hash_sv2',
                 'FullName': 'Tran Hai Binh', 'Email': 'binh.sv@uth.edu.vn', 'Phone': '0901000005',
                 'Role': 'Student', 'Status': 'Locked', 'FailedLoginCount': 5, 'CreatedAt': '2026-09-01'},
            ],
            'students': {
                4: {'UserId': 4, 'StudentCode': 'SV001', 'AdministrativeClass': 'MIS2301',
                    'Major': 'Management Information Systems', 'EnrollmentYear': 2023},
                5: {'UserId': 5, 'StudentCode': 'SV002', 'AdministrativeClass': 'MIS2301',
                    'Major': 'Management Information Systems', 'EnrollmentYear': 2023},
            },
            'lecturers': {
                2: {'UserId': 2, 'LecturerCode': 'GV001', 'Department': 'MIS', 'AcademicDegree': 'Master'},
                3: {'UserId': 3, 'LecturerCode': 'GV002', 'Department': 'SE', 'AcademicDegree': 'Doctorate'},
            },
            'semesters': [
                {'Id': 2, 'SemesterCode': 'SEM1_2026_2027', 'SemesterName': 'Semester 1 (2026-2027)',
                 'AcademicYear': '2026-2027', 'IsCurrent': 1},
            ],
            'timeslots': [
                {'Id': 1, 'SlotNumber': 1, 'SlotName': 'Slot 1 (07:00 - 09:30)', 'StartTime': '07:00', 'EndTime': '09:30'},
                {'Id': 2, 'SlotNumber': 2, 'SlotName': 'Slot 2 (09:45 - 12:15)', 'StartTime': '09:45', 'EndTime': '12:15'},
            ],
            'classrooms': [
                {'Id': 1, 'RoomCode': 'A101', 'Building': 'Building A', 'Capacity': 50, 'RoomType': 'Theory'},
                {'Id': 2, 'RoomCode': 'B202', 'Building': 'Building B', 'Capacity': 45, 'RoomType': 'Theory'},
            ],
            'courses': [
                {'Id': 1, 'CourseCode': 'IT101', 'CourseName': 'Introduction to Programming',
                 'Credits': 3, 'TheoryHours': 30, 'PracticeHours': 15, 'Department': 'CS',
                 'PrerequisiteCourseId': None, 'IsActive': 1},
                {'Id': 2, 'CourseCode': 'IT102', 'CourseName': 'Data Structures and Algorithms',
                 'Credits': 4, 'TheoryHours': 45, 'PracticeHours': 15, 'Department': 'CS',
                 'PrerequisiteCourseId': 1, 'IsActive': 1},
            ],
            'course_prereqs': [
                {'CourseId': 2, 'PrerequisiteCourseId': 1, 'IsMandatory': 1},
            ],
            'classes': [
                # Lớp IT101_01: Thứ 2, Ca 1, Phòng A101, GV001 (Id=2), đang có 3 SV (< 15 SV)
                {'Id': 10, 'ClassCode': 'IT101_01', 'CourseId': 1, 'SemesterId': 2,
                 'LecturerId': 2, 'ClassroomId': 1, 'Room': 'A101',
                 'TimeSlotId': 1, 'DayOfWeek': 2, 'MinCapacity': 15, 'MaxCapacity': 50,
                 'CurrentEnrollment': 3, 'Status': 'Open'},
                # Lớp IT102_01: Thứ 3, Ca 2, Phòng B202, GV002 (Id=3), có đủ 15 SV (>= 15 SV)
                {'Id': 11, 'ClassCode': 'IT102_01', 'CourseId': 2, 'SemesterId': 2,
                 'LecturerId': 3, 'ClassroomId': 2, 'Room': 'B202',
                 'TimeSlotId': 2, 'DayOfWeek': 3, 'MinCapacity': 15, 'MaxCapacity': 45,
                 'CurrentEnrollment': 15, 'Status': 'Open'},
            ],
            'enrollments': [
                {'Id': 101, 'StudentId': 4, 'ClassId': 10, 'Status': 'Enrolled', 'CancelledAt': None},
                {'Id': 102, 'StudentId': 5, 'ClassId': 10, 'Status': 'Enrolled', 'CancelledAt': None},
                {'Id': 103, 'StudentId': 6, 'ClassId': 10, 'Status': 'Enrolled', 'CancelledAt': None},
            ],
            'periods': [
                {'Id': 1, 'SemesterId': 2, 'PeriodName': 'Fall 2026 Registration',
                 'StartDate': '2026-09-01T00:00:00', 'EndDate': '2026-12-31T23:59:59',
                 'MinCredits': 12, 'MaxCredits': 25, 'IsActive': 1},
            ],
            'history': [],
            'tuition_recalcs': [],
        }

    @contextmanager
    def get_cursor(self):
        snapshot = copy.deepcopy(self.state)
        cursor = FakeCursor(self.state)
        try:
            yield cursor
        except Exception:
            self.state = snapshot
            raise


# ==========================================================================
# UNIT TESTS CHO PHÂN HỆ ADMIN
# ==========================================================================
class TestAdminModule(unittest.TestCase):
    """Test suite covering TC_ADM_01 to TC_ADM_28 based strictly on Excel specification."""

    def setUp(self):
        self.fake_db = FakeDatabase()
        self.cursor_patcher = patch.object(Database, 'get_cursor', side_effect=self.fake_db.get_cursor)
        self.cursor_patcher.start()

        # Flask test app
        self.app = Flask(__name__, template_folder=os.path.join(STAGE_DIR, 'templates'))
        self.app.secret_key = 'test_secret_key'
        self.app.register_blueprint(admin_bp)
        self.client = self.app.test_client()

    def tearDown(self):
        self.cursor_patcher.stop()

    def _login_as_admin(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'Admin'

    # ==========================================================================
    # TC_ADM_01: Admin Login Success
    # ==========================================================================
    def test_tc01_admin_login_success(self):
        """TC_ADM_01: Admin logs in successfully with valid credentials."""
        user = UserModel.find_by_username('admin')
        self.assertIsNotNone(user)
        self.assertEqual(user['Role'], 'Admin')
        self.assertTrue(UserModel.verify_password(user['PasswordHash'], '123456'))

    # ==========================================================================
    # TC_ADM_02: API Security - Unauthenticated Requests Blocked
    # ==========================================================================
    def test_tc02_api_security_unauthenticated_rejected(self):
        """TC_ADM_02: Unauthenticated API requests rejected with HTTP 401."""
        res = self.client.get('/admin/api/users')
        self.assertEqual(res.status_code, 401)
        self.assertFalse(res.get_json()['success'])

    # ==========================================================================
    # TC_ADM_03: RBAC - Non-Admin Roles Blocked from Admin Portal
    # ==========================================================================
    def test_tc03_rbac_blocks_student_from_admin(self):
        """TC_ADM_03: Non-admin roles (Student) blocked with HTTP 403."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 4
            sess['role'] = 'Student'
            sess['username'] = 'sv_an'
        res = self.client.get('/admin/api/users')
        self.assertEqual(res.status_code, 403)
        self.assertFalse(res.get_json()['success'])

    # ==========================================================================
    # TC_ADM_04: View User Accounts List
    # ==========================================================================
    def test_tc04_user_account_list(self):
        """TC_ADM_04: View list of system user accounts (Admin, GV, SV)."""
        users = AdminUserModel.list_users()
        self.assertIsInstance(users, list)
        self.assertTrue(len(users) >= 2)
        for u in users:
            self.assertIn('Username', u)
            self.assertIn('Role', u)
            self.assertIn('Status', u)

    # ==========================================================================
    # TC_ADM_05: Create Student Account
    # ==========================================================================
    def test_tc05_create_student_account(self):
        """TC_ADM_05: Create new student account with hashed password."""
        created = AdminUserModel.create_user(
            role='Student', user_code='SV999', full_name='Test Student',
            email='test.student@uth.edu.vn', department='MIS', password='TestPassword123!',
            username='sv_test_new', phone='0909999999'
        )
        self.assertEqual(created['UserCode'], 'SV999')
        self.assertEqual(created['Role'], 'Student')
        self.assertEqual(created['Status'], 'Active')
        db_user = next(u for u in self.fake_db.state['users'] if u['Username'] == 'sv_test_new')
        self.assertEqual(db_user['Status'], 'Active')

    # ==========================================================================
    # TC_ADM_06: Create Lecturer Account
    # ==========================================================================
    def test_tc06_create_lecturer_account(self):
        """TC_ADM_06: Create new lecturer account with role 'Lecturer'."""
        created = AdminUserModel.create_user(
            role='Lecturer', user_code='GV999', full_name='Dr. Test Lecturer',
            email='test.lecturer@uth.edu.vn', department='SE', password='LecturerPass123!',
            username='gv_test_new', phone='0908888888', academic_degree='Doctorate'
        )
        self.assertEqual(created['UserCode'], 'GV999')
        self.assertEqual(created['Role'], 'Lecturer')
        self.assertEqual(created['Status'], 'Active')
        db_user = next(u for u in self.fake_db.state['users'] if u['Username'] == 'gv_test_new')
        self.assertEqual(db_user['Role'], 'Lecturer')

    # ==========================================================================
    # TC_ADM_07: Create User Account - Duplicate Username Rejected
    # ==========================================================================
    def test_tc07_create_user_duplicate_username_rejected(self):
        """TC_ADM_07: Reject duplicate username with HTTP 409 Conflict."""
        with self.assertRaises(AdminConflictError):
            AdminUserModel.create_user(
                role='Student', user_code='SV998', full_name='Duplicate Student',
                email='dup.sv@uth.edu.vn', department='MIS', password='TestPassword123!',
                username='sv_an'
            )

    # ==========================================================================
    # TC_ADM_08: Update User Account Profile
    # ==========================================================================
    def test_tc08_update_user_account(self):
        """TC_ADM_08: Update user account profile (Name, Email, Phone)."""
        updated = AdminUserModel.update_user(
            user_id=4,
            full_name='Nguyen Van An Updated',
            email='an.update@uth.edu.vn',
            department='MIS',
            phone='0901234999'
        )
        self.assertEqual(updated['FullName'], 'Nguyen Van An Updated')
        self.assertEqual(updated['Email'], 'an.update@uth.edu.vn')
        db_u = next(u for u in self.fake_db.state['users'] if u['Id'] == 4)
        self.assertEqual(db_u['FullName'], 'Nguyen Van An Updated')

    # ==========================================================================
    # TC_ADM_09: Lock User Account
    # ==========================================================================
    def test_tc09_lock_user_account(self):
        """TC_ADM_09: Change account status to 'Locked'."""
        res = AdminUserModel.set_user_status(user_id=4, status='Locked')
        self.assertEqual(res['Status'], 'Locked')
        u = next(usr for usr in self.fake_db.state['users'] if usr['Id'] == 4)
        self.assertEqual(u['Status'], 'Locked')

    # ==========================================================================
    # TC_ADM_10: Unlock User Account
    # ==========================================================================
    def test_tc10_unlock_user_account(self):
        """TC_ADM_10: Restore account status to 'Active', reset failed cnt."""
        sv_locked = next(u for u in self.fake_db.state['users'] if u['Id'] == 5)
        self.assertEqual(sv_locked['Status'], 'Locked')
        self.assertEqual(sv_locked['FailedLoginCount'], 5)

        unlocked = AdminUserModel.set_user_status(user_id=5, status='Active')
        self.assertEqual(unlocked['Status'], 'Active')
        user_after = next(u for u in self.fake_db.state['users'] if u['Id'] == 5)
        self.assertEqual(user_after['Status'], 'Active')
        self.assertEqual(user_after['FailedLoginCount'], 0)

    # ==========================================================================
    # TC_ADM_11: Create Course with Valid Prerequisite
    # ==========================================================================
    def test_tc11_create_course_success_with_prerequisite(self):
        """TC_ADM_11: Create course with valid prerequisite course."""
        created = AdminCourseModel.create_course(
            course_code='IT415',
            course_name='Information Security',
            credits=3,
            prerequisite_course_id=1,
        )
        self.assertEqual(created['CourseCode'], 'IT415')
        self.assertEqual(created['Credits'], 3)
        self.assertEqual(created['PrerequisiteCourseId'], 1)
        self.assertTrue(
            any(p['CourseId'] == created['Id'] and p['PrerequisiteCourseId'] == 1
                for p in self.fake_db.state['course_prereqs'])
        )

    # ==========================================================================
    # TC_ADM_12: Create Course - Duplicate Code Rejected
    # ==========================================================================
    def test_tc12_create_course_duplicate_code_rejected(self):
        """TC_ADM_12: Reject duplicate course code with HTTP 409 Conflict."""
        with self.assertRaises(AdminConflictError) as ctx:
            AdminCourseModel.create_course(
                course_code='IT101',
                course_name='Trùng mã IT101',
                credits=3,
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("IT101", str(ctx.exception))

    # ==========================================================================
    # TC_ADM_13: Update Course Prerequisites - Circular Dependency Loop
    # ==========================================================================
    def test_tc13_update_course_circular_prerequisite_rejected(self):
        """TC_ADM_13: Prevent circular prerequisite dependency loops."""
        with self.assertRaises(AdminValidationError) as ctx:
            AdminCourseModel.update_course(
                course_id=1,
                course_code='IT101',
                course_name='Introduction to Programming',
                credits=3,
                prerequisite_course_id=2,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("circular dependency", str(ctx.exception).lower())

    # ==========================================================================
    # TC_ADM_14: Delete Course Without Class Sections
    # ==========================================================================
    def test_tc14_delete_course_without_classes(self):
        """TC_ADM_14: Delete course that has no active class sections."""
        new_c = AdminCourseModel.create_course(
            course_code='IT999',
            course_name='Temporary Course',
            credits=2,
        )
        res = AdminCourseModel.delete_course(course_id=new_c['Id'])
        self.assertEqual(res['Id'], new_c['Id'])
        self.assertIn(res['DeleteMode'], ('hard', 'soft'))
        self.assertFalse(any(c['Id'] == new_c['Id'] for c in self.fake_db.state['courses']))

    # ==========================================================================
    # TC_ADM_15: Open Class Section - Valid Schedule Success
    # ==========================================================================
    def test_tc15_create_class_valid_schedule_success(self):
        """TC_ADM_15: Open class section successfully with valid schedule."""
        created = AdminClassModel.create_class(
            course_id=1,
            class_code='IT101_02',
            semester_id=2,
            room='B202',
            day_of_week=4,
            time_slot_id=2,
            max_capacity=45,
            lecturer_id=2,
        )
        self.assertEqual(created['ClassCode'], 'IT101_02')
        self.assertEqual(created['Status'], 'Open')
        self.assertEqual(created['MaxCapacity'], 45)
        self.assertTrue(any(cl['Id'] == created['Id'] for cl in self.fake_db.state['classes']))

    # ==========================================================================
    # TC_ADM_16: Open Class Section - Room Conflict Rejected
    # ==========================================================================
    def test_tc16_create_class_room_conflict_rejected(self):
        """TC_ADM_16: Reject class section due to room booking conflict."""
        with self.assertRaises(AdminConflictError) as ctx:
            AdminClassModel.create_class(
                course_id=2,
                class_code='IT102_02',
                semester_id=2,
                room='A101',
                day_of_week=2,
                time_slot_id=1,
                max_capacity=40,
                lecturer_id=3,
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertTrue('room' in str(ctx.exception).lower() or 'phòng' in str(ctx.exception).lower())

    # ==========================================================================
    # TC_ADM_17: Open Class Section - Lecturer Conflict Rejected
    # ==========================================================================
    def test_tc17_create_class_lecturer_conflict_rejected(self):
        """TC_ADM_17: Reject class section due to lecturer schedule clash."""
        with self.assertRaises(AdminConflictError) as ctx:
            AdminClassModel.create_class(
                course_id=2,
                class_code='IT102_03',
                semester_id=2,
                room='B202',
                day_of_week=2,
                time_slot_id=1,
                max_capacity=40,
                lecturer_id=2,
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertTrue('lecturer' in str(ctx.exception).lower() or 'giảng viên' in str(ctx.exception).lower())

    # ==========================================================================
    # TC_ADM_18: Cancel Class Section Under 15 Students
    # ==========================================================================
    def test_tc18_cancel_class_under_15_students(self):
        """TC_ADM_18: Cancel under-enrolled class (< 15 SV) & cancel enrs."""
        result = AdminClassModel.cancel_class(class_id=10)
        self.assertEqual(result['Id'], 10)
        self.assertEqual(result['Status'], 'Cancelled')
        self.assertEqual(result['AffectedStudents'], 3)

        cancelled_class = next(cl for cl in self.fake_db.state['classes'] if cl['Id'] == 10)
        self.assertEqual(cancelled_class['Status'], 'Cancelled')
        for enr in [e for e in self.fake_db.state['enrollments'] if e['ClassId'] == 10]:
            self.assertEqual(enr['Status'], 'Cancelled')

    # ==========================================================================
    # TC_ADM_19: Cancel Class Section >= 15 Students Rejected
    # ==========================================================================
    def test_tc19_cancel_class_with_15_or_more_students_rejected(self):
        """TC_ADM_19: Reject cancellation of viable class (>= 15 SV)."""
        with self.assertRaises(AdminValidationError) as ctx:
            AdminClassModel.cancel_class(class_id=11)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("15", str(ctx.exception))
        unchanged_class = next(cl for cl in self.fake_db.state['classes'] if cl['Id'] == 11)
        self.assertEqual(unchanged_class['Status'], 'Open')

    # ==========================================================================
    # TC_ADM_20: Cancel Class Section - Transaction Rollback on Error
    # ==========================================================================
    def test_tc20_cancel_class_transaction_rollback_on_error(self):
        """TC_ADM_20: Rollback transaction if enrollment update fails."""
        self.fake_db.state['fail_on_tag'] = '/* q:cancel_enrollments */'
        with self.assertRaises(RuntimeError):
            AdminClassModel.cancel_class(class_id=10)

        rolled_back_class = next(cl for cl in self.fake_db.state['classes'] if cl['Id'] == 10)
        self.assertEqual(rolled_back_class['Status'], 'Open')

    # ==========================================================================
    # TC_ADM_21: Save Registration Period Success
    # ==========================================================================
    def test_tc21_save_registration_period_success(self):
        """TC_ADM_21: Create and activate new registration period."""
        saved = AdminPeriodModel.save_period(
            semester_id=2, period_name='Registration Period Phase 2',
            start_date='2026-11-20', end_date='2026-11-30',
            min_credits=12, max_credits=25
        )
        self.assertEqual(saved['SemesterId'], 2)
        self.assertTrue(saved['IsActive'])
        old_period = next(p for p in self.fake_db.state['periods'] if p['Id'] == 1)
        self.assertEqual(old_period['IsActive'], 0)

    # ==========================================================================
    # TC_ADM_22: Save Registration Period - Invalid Dates Rejected
    # ==========================================================================
    def test_tc22_save_registration_period_invalid_dates_rejected(self):
        """TC_ADM_22: Reject invalid period dates (EndDate <= StartDate)."""
        with self.assertRaises(AdminValidationError) as ctx:
            AdminPeriodModel.save_period(
                semester_id=2, period_name='Invalid Period',
                start_date='2026-11-30', end_date='2026-11-20',
                min_credits=12, max_credits=25
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("start date", str(ctx.exception).lower())

    # ==========================================================================
    # TC_ADM_23: Close Registration Period
    # ==========================================================================
    def test_tc23_close_registration_period(self):
        """TC_ADM_23: Close active registration period (IsActive = 0)."""
        res = AdminPeriodModel.set_period_active(period_id=1, is_active=False)
        self.assertFalse(res['IsActive'])
        period = next(p for p in self.fake_db.state['periods'] if p['Id'] == 1)
        self.assertEqual(period['IsActive'], 0)

    # ==========================================================================
    # TC_ADM_24: Manual Enrollment Override - Force Add
    # ==========================================================================
    def test_tc24_manual_override_force_add(self):
        """TC_ADM_24: Admin manually force registers student into class."""
        res = AdminEnrollmentModel.manual_override(
            student_code='SV001', class_code='IT102_01', action='ADD',
            admin_user_id=1
        )
        self.assertEqual(res['StudentCode'], 'SV001')
        self.assertEqual(res['ClassCode'], 'IT102_01')
        self.assertEqual(res['Action'], 'ADD')

    # ==========================================================================
    # TC_ADM_25: Manual Enrollment Override - Force Drop
    # ==========================================================================
    def test_tc25_manual_override_force_drop(self):
        """TC_ADM_25: Admin manually force drops student from class."""
        res = AdminEnrollmentModel.manual_override(
            student_code='SV001', class_code='IT101_01', action='REMOVE',
            admin_user_id=1
        )
        self.assertEqual(res['StudentCode'], 'SV001')
        self.assertEqual(res['ClassCode'], 'IT101_01')
        self.assertEqual(res['Action'], 'REMOVE')

    # ==========================================================================
    # TC_ADM_26: Reports - Section Fill Rate Viability
    # ==========================================================================
    def test_tc26_reports_section_fill_rate(self):
        """TC_ADM_26: Generate section fill-rate viability report."""
        report = AdminReportModel.section_report(semester_id=2)
        self.assertIsInstance(report, list)
        self.assertGreater(len(report), 0)
        sec_it101 = next(s for s in report if s['ClassCode'] == 'IT101_01')
        self.assertEqual(sec_it101['CurrentEnrollment'], 3)
        self.assertEqual(sec_it101['MaxCapacity'], 50)
        self.assertAlmostEqual(float(sec_it101['FillRate']), 6.0, places=1)

    # ==========================================================================
    # TC_ADM_27: Reports - Student Credit Compliance Statistics
    # ==========================================================================
    def test_tc27_reports_student_credits(self):
        """TC_ADM_27: Generate student credit compliance statistics report."""
        report = AdminReportModel.student_report(semester_id=2)
        self.assertIsInstance(report, list)
        stu_sv001 = next(st for st in report if st['StudentCode'] == 'SV001')
        self.assertEqual(stu_sv001['TotalCredits'], 3)
        self.assertEqual(stu_sv001['Compliance'], 'Below Minimum')

    # ==========================================================================
    # TC_ADM_28: Admin Logout Clears Session & Redirects
    # ==========================================================================
    def test_tc28_admin_logout(self):
        """TC_ADM_28: Admin logout terminates session and redirects."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'Admin'
            sess['username'] = 'admin'
        res = self.client.get('/admin/logout')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/logout', res.headers.get('Location'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
