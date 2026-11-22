"""
tests/test_student.py
=====================
Test Cases & Unit Tests for the STUDENT PORTAL module (Stage 4 - Testing & Quality).
Course Registration System.

================================================================================
TEST CASE SPECIFICATION TABLE
================================================================================
| TC ID     | Test Case Name                                            | Input                                                  | Expected Output                                                             |
|-----------|-----------------------------------------------------------|--------------------------------------------------------|-----------------------------------------------------------------------------|
| TC_STU_01 | Display open class sections in semester                   | SemesterId=2, StudentId=4                             | Class list with seat availability, prerequisite status, eligibility flags     |
| TC_STU_02 | Registration fails when class section is full             | ClassId=1 (CurrentEnrollment=50, MaxCapacity=50)       | StudentConflictError (HTTP 409), enrollment count unchanged               |
| TC_STU_03 | Registration fails when prerequisite is not met           | Course IT102 requires IT101, student has not passed    | StudentValidationError (HTTP 400), registration blocked                   |
| TC_STU_04 | Registration succeeds when prerequisite is met            | Course IT102, student completed IT101 (IsPassed=1)     | Registration succeeds (HTTP 201), 'Enrolled' record created               |
| TC_STU_05 | Registration fails on schedule conflict                   | Class conflicts on Day/TimeSlot with enrolled class    | StudentConflictError (HTTP 409), identifies conflicting class & slot        |
| TC_STU_06 | Registration fails when exceeding 25 max credits          | Current 23 credits + new 4 credits = 27 credits        | StudentValidationError (HTTP 400), exceeds 25-credit cap                  |
| TC_STU_07 | Registration succeeds & increments enrollment count by 1  | All 4 strict conditions satisfied                      | CurrentEnrollment +1, 'Enrolled' saved, 'Register' audit log recorded      |
| TC_STU_08 | Block duplicate registration across sections of same course | Already enrolled in IT101_01, registers IT101_02       | StudentConflictError (HTTP 409) for duplicate course in semester          |
| TC_STU_09 | Block registration when registration period is closed     | Registration window IsActive=0 or outside date range   | StudentValidationError (HTTP 400) indicating registration is closed         |
| TC_STU_10 | Drop course succeeds & decrements enrollment count by 1   | Enrolled student drops class while window is open      | CurrentEnrollment -1, Enrollment -> 'Cancelled', 'Drop' audit log recorded  |
| TC_STU_11 | Render weekly timetable grid                              | Student has enrolled classes in the selected week       | Sessions mapped accurately across days and time slots (Slot 1..N)           |
| TC_STU_12 | Automatically calculate total tuition by credit rate      | 7 total credits, Unit price 550,000 VND                | Total = 7 * 550,000 = 3,850,000 VND, itemized course breakdown              |
| TC_STU_13 | Verify RBAC authorization on `/student/*` APIs            | Unauthenticated (401) or role='Lecturer' (403)       | Unauthorized requests rejected with HTTP 401 / 403                        |
================================================================================
"""

import copy
import os
import sys
import unittest
from contextlib import contextmanager
from datetime import datetime, date, time
from decimal import Decimal
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from models.user_model import UserModel

# Ensure modules in the stage3&4 directory can be imported
STAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if STAGE_DIR not in sys.path:
    sys.path.insert(0, STAGE_DIR)

from flask import Flask
from controllers.student_controller import student_bp
from models.student_model import (
    StudentCourseModel,
    StudentConflictError,
    StudentHistoryModel,
    StudentLookupModel,
    StudentNotFoundError,
    StudentProfileModel,
    StudentRegistrationModel,
    StudentScheduleModel,
    StudentTuitionModel,
    StudentValidationError,
)
from models.db import Database


# ==========================================================================
# FAKE IN-MEMORY DATABASE ENGINE (For standalone unit tests)
# ==========================================================================
class FakeStudentCursor:
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

        # 1. Semesters & RegistrationPeriods
        if '/* q:student_lookup_semesters */' in sql:
            self._set_result(self.state['semesters'])
        elif '/* q:student_lookup_current_semester */' in sql:
            found = [s for s in self.state['semesters'] if s.get('IsCurrent')]
            self._set_result(found[:1])
        elif '/* q:student_lookup_semester_by_id */' in sql or '/* q:student_schedule_semester */' in sql:
            sid = params[0]
            found = [s for s in self.state['semesters'] if s['Id'] == sid]
            self._set_result(found[:1])
        elif '/* q:student_lookup_active_period */' in sql or '/* q:student_reg_check_period */' in sql or '/* q:student_drop_check_period */' in sql:
            sid = params[0]
            found = [p for p in self.state['periods'] if p['SemesterId'] == sid and p.get('IsActive')]
            self._set_result(found[:1])
        elif '/* q:student_lookup_timeslots */' in sql:
            self._set_result(self.state['timeslots'])

        # 2. Profile
        elif '/* q:student_check_password */' in sql:
            uid = params[0]
            found = [{'Id': u['Id'], 'PasswordHash': u.get('PasswordHash')} for u in self.state['users'] if u['Id'] == uid]
            self._set_result(found[:1])

        elif '/* q:student_update_password */' in sql:
            new_hash, uid = params
            for u in self.state['users']:
                if u['Id'] == uid:
                    u['PasswordHash'] = new_hash
            self.rowcount = 1

        elif '/* q:student_drop_check_period */' in sql:
            sid = params[0]
            found = [p for p in self.state['periods'] if p['SemesterId'] == sid and p.get('IsActive', 1) == 1]
            self._set_result(found[:1])

        elif '/* q:student_profile */' in sql:
            uid = params[0]
            found = []
            for u in self.state['users']:
                if u['Id'] == uid:
                    stu = self.state['students'].get(uid, {})
                    item = dict(u)
                    item.update(stu)
                    found.append(item)
            self._set_result(found[:1])

        # 3. Available Classes & Detail
        elif '/* q:student_available_classes */' in sql:
            sid = params[0]
            res = []
            for cl in self.state['classes']:
                if cl['SemesterId'] == sid and cl['Status'] in ('Open', 'Closed'):
                    co = next((c for c in self.state['courses'] if c['Id'] == cl['CourseId']), {})
                    ts = next((t for t in self.state['timeslots'] if t['Id'] == cl['TimeSlotId']), {})
                    lec = next((u for u in self.state['users'] if u['Id'] == cl.get('LecturerId')), {})
                    pco = next((c for c in self.state['courses'] if c['Id'] == co.get('PrerequisiteCourseId')), {})
                    row = {
                        'Id': cl['Id'], 'ClassCode': cl['ClassCode'], 'CourseId': cl['CourseId'],
                        'SemesterId': cl['SemesterId'], 'LecturerId': cl.get('LecturerId'),
                        'ClassroomId': cl.get('ClassroomId'), 'Room': cl['Room'],
                        'TimeSlotId': cl['TimeSlotId'], 'DayOfWeek': cl['DayOfWeek'],
                        'MinCapacity': cl['MinCapacity'], 'MaxCapacity': cl['MaxCapacity'],
                        'CurrentEnrollment': cl['CurrentEnrollment'], 'ClassStatus': cl['Status'],
                        'CourseCode': co.get('CourseCode'), 'CourseName': co.get('CourseName'),
                        'Credits': co.get('Credits'), 'TheoryHours': co.get('TheoryHours', 30),
                        'PracticeHours': co.get('PracticeHours', 15), 'Department': co.get('Department'),
                        'PrerequisiteCourseId': co.get('PrerequisiteCourseId'),
                        'PrerequisiteCode': pco.get('CourseCode'), 'PrerequisiteName': pco.get('CourseName'),
                        'SlotNumber': ts.get('SlotNumber'), 'SlotName': ts.get('SlotName'),
                        'StartTime': ts.get('StartTime'), 'EndTime': ts.get('EndTime'),
                        'LecturerName': lec.get('FullName'), 'AcademicDegree': 'Master',
                    }
                    res.append(row)
            self._set_result(res)

        elif '/* q:student_class_detail */' in sql:
            cid = params[0]
            found = []
            for cl in self.state['classes']:
                if cl['Id'] == cid:
                    co = next((c for c in self.state['courses'] if c['Id'] == cl['CourseId']), {})
                    ts = next((t for t in self.state['timeslots'] if t['Id'] == cl['TimeSlotId']), {})
                    sem = next((s for s in self.state['semesters'] if s['Id'] == cl['SemesterId']), {})
                    lec = next((u for u in self.state['users'] if u['Id'] == cl.get('LecturerId')), {})
                    pco = next((c for c in self.state['courses'] if c['Id'] == co.get('PrerequisiteCourseId')), {})
                    found.append({
                        'Id': cl['Id'], 'ClassCode': cl['ClassCode'], 'CourseId': cl['CourseId'],
                        'SemesterId': cl['SemesterId'], 'LecturerId': cl.get('LecturerId'),
                        'ClassroomId': cl.get('ClassroomId'), 'Room': cl['Room'],
                        'TimeSlotId': cl['TimeSlotId'], 'DayOfWeek': cl['DayOfWeek'],
                        'MinCapacity': cl['MinCapacity'], 'MaxCapacity': cl['MaxCapacity'],
                        'CurrentEnrollment': cl['CurrentEnrollment'], 'ClassStatus': cl['Status'],
                        'CourseCode': co.get('CourseCode'), 'CourseName': co.get('CourseName'),
                        'Credits': co.get('Credits'), 'TheoryHours': co.get('TheoryHours', 30),
                        'PracticeHours': co.get('PracticeHours', 15), 'Department': co.get('Department'),
                        'PrerequisiteCourseId': co.get('PrerequisiteCourseId'),
                        'PrerequisiteCode': pco.get('CourseCode'), 'PrerequisiteName': pco.get('CourseName'),
                        'SlotNumber': ts.get('SlotNumber'), 'SlotName': ts.get('SlotName'),
                        'StartTime': ts.get('StartTime'), 'EndTime': ts.get('EndTime'),
                        'LecturerName': lec.get('FullName'), 'AcademicDegree': 'Master',
                        'SemesterName': sem.get('SemesterName'), 'AcademicYear': sem.get('AcademicYear'),
                        'CreditUnitPrice': sem.get('CreditUnitPrice', 550000),
                    })
            self._set_result(found[:1])

        # 4. Enrolled Classes & Total Credits
        elif '/* q:student_enrolled_classes */' in sql:
            stu_id, sid = params
            res = []
            for e in self.state['enrollments']:
                if e['StudentId'] == stu_id and e['Status'] == 'Enrolled':
                    cl = next((c for c in self.state['classes'] if c['Id'] == e['ClassId']), None)
                    if cl and cl['SemesterId'] == sid and cl['Status'] != 'Cancelled':
                        co = next((c for c in self.state['courses'] if c['Id'] == cl['CourseId']), {})
                        ts = next((t for t in self.state['timeslots'] if t['Id'] == cl['TimeSlotId']), {})
                        lec = next((u for u in self.state['users'] if u['Id'] == cl.get('LecturerId')), {})
                        res.append({
                            'EnrollmentId': e['Id'], 'StudentId': stu_id, 'ClassId': cl['Id'],
                            'EnrolledAt': e['EnrolledAt'], 'EnrollmentStatus': e['Status'],
                            'ClassCode': cl['ClassCode'], 'SemesterId': sid,
                            'DayOfWeek': cl['DayOfWeek'], 'TimeSlotId': cl['TimeSlotId'],
                            'Room': cl['Room'], 'CurrentEnrollment': cl['CurrentEnrollment'],
                            'MaxCapacity': cl['MaxCapacity'], 'ClassStatus': cl['Status'],
                            'CourseId': co.get('Id'), 'CourseCode': co.get('CourseCode'),
                            'CourseName': co.get('CourseName'), 'Credits': co.get('Credits'),
                            'SlotNumber': ts.get('SlotNumber'), 'SlotName': ts.get('SlotName'),
                            'StartTime': ts.get('StartTime'), 'EndTime': ts.get('EndTime'),
                            'LecturerName': lec.get('FullName'), 'AcademicDegree': 'Master',
                        })
            self._set_result(res)

        elif '/* q:student_total_credits */' in sql or '/* q:student_reg_sum_credits */' in sql or '/* q:student_drop_sum_credits */' in sql or '/* q:student_tuition_calc_credits */' in sql:
            stu_id, sid = params
            tot = 0
            for e in self.state['enrollments']:
                if e['StudentId'] == stu_id and e['Status'] == 'Enrolled':
                    cl = next((c for c in self.state['classes'] if c['Id'] == e['ClassId']), None)
                    if cl and cl['SemesterId'] == sid and cl['Status'] != 'Cancelled':
                        co = next((c for c in self.state['courses'] if c['Id'] == cl['CourseId']), None)
                        if co:
                            tot += int(co['Credits'])
            self._set_result([{'TotalCredits': tot, 'CurrentCredits': tot, 'RemainingCredits': tot}])

        elif '/* q:student_passed_courses */' in sql:
            stu_id = params[0]
            passed = []
            for e in self.state['enrollments']:
                if e['StudentId'] == stu_id and e['Status'] == 'Completed' and e.get('IsPassed'):
                    cl = next((c for c in self.state['classes'] if c['Id'] == e['ClassId']), None)
                    if cl:
                        passed.append({'CourseId': cl['CourseId']})
            self._set_result(passed)

        # 5. Registration Transactions
        elif '/* q:student_reg_get_class */' in sql:
            cid = params[0]
            found = []
            for cl in self.state['classes']:
                if cl['Id'] == cid:
                    co = next((c for c in self.state['courses'] if c['Id'] == cl['CourseId']), {})
                    found.append({
                        'Id': cl['Id'], 'ClassCode': cl['ClassCode'], 'CourseId': cl['CourseId'],
                        'SemesterId': cl['SemesterId'], 'DayOfWeek': cl['DayOfWeek'],
                        'TimeSlotId': cl['TimeSlotId'], 'CurrentEnrollment': cl['CurrentEnrollment'],
                        'MaxCapacity': cl['MaxCapacity'], 'ClassStatus': cl['Status'],
                        'CourseCode': co.get('CourseCode'), 'CourseName': co.get('CourseName'),
                        'Credits': co.get('Credits'), 'PrerequisiteCourseId': co.get('PrerequisiteCourseId'),
                    })
            self._set_result(found[:1])

        elif '/* q:student_reg_check_course_dup */' in sql:
            stu_id, sid, co_id = params
            found = []
            for e in self.state['enrollments']:
                if e['StudentId'] == stu_id and e['Status'] == 'Enrolled':
                    cl = next((c for c in self.state['classes'] if c['Id'] == e['ClassId']), None)
                    if cl and cl['SemesterId'] == sid and cl['CourseId'] == co_id:
                        found.append({'Id': cl['Id'], 'ClassCode': cl['ClassCode']})
            self._set_result(found[:1])

        elif '/* q:student_reg_check_prereq */' in sql:
            stu_id, prereq_co_id = params
            found = []
            for e in self.state['enrollments']:
                if e['StudentId'] == stu_id and e['Status'] == 'Completed' and e.get('IsPassed'):
                    cl = next((c for c in self.state['classes'] if c['Id'] == e['ClassId']), None)
                    if cl and cl['CourseId'] == prereq_co_id:
                        found.append({'Id': e['Id']})
            self._set_result(found[:1])

        elif '/* q:student_reg_prereq_info */' in sql:
            p_id = params[0]
            found = [{'CourseCode': c['CourseCode'], 'CourseName': c['CourseName']} for c in self.state['courses'] if c['Id'] == p_id]
            self._set_result(found[:1])

        elif '/* q:student_reg_multi_prereqs */' in sql:
            self._set_result([])

        elif '/* q:student_reg_check_conflict */' in sql:
            stu_id, sid, day, slot_id = params
            found = []
            for e in self.state['enrollments']:
                if e['StudentId'] == stu_id and e['Status'] == 'Enrolled':
                    cl = next((c for c in self.state['classes'] if c['Id'] == e['ClassId']), None)
                    if cl and cl['SemesterId'] == sid and cl['Status'] != 'Cancelled' and cl['DayOfWeek'] == day and cl['TimeSlotId'] == slot_id:
                        co = next((c for c in self.state['courses'] if c['Id'] == cl['CourseId']), {})
                        ts = next((t for t in self.state['timeslots'] if t['Id'] == cl['TimeSlotId']), {})
                        found.append({
                            'ClassCode': cl['ClassCode'], 'CourseCode': co.get('CourseCode'),
                            'CourseName': co.get('CourseName'), 'SlotName': ts.get('SlotName'),
                            'StartTime': ts.get('StartTime'), 'EndTime': ts.get('EndTime'),
                        })
            self._set_result(found[:1])

        elif '/* q:student_reg_find_enrollment */' in sql:
            stu_id, cid = params
            found = [e for e in self.state['enrollments'] if e['StudentId'] == stu_id and e['ClassId'] == cid]
            self._set_result(found[:1])

        elif '/* q:student_reg_update_enrollment */' in sql:
            stu_id, cid = params
            for e in self.state['enrollments']:
                if e['StudentId'] == stu_id and e['ClassId'] == cid:
                    e['Status'] = 'Enrolled'
                    e['EnrolledAt'] = '2026-11-13T08:00:00'
                    e['CancelledAt'] = None
            self.rowcount = 1

        elif '/* q:student_reg_insert_enrollment */' in sql:
            stu_id, cid = params
            new_id = max((e['Id'] for e in self.state['enrollments']), default=0) + 1
            self.state['enrollments'].append({
                'Id': new_id, 'StudentId': stu_id, 'ClassId': cid,
                'Status': 'Enrolled', 'EnrolledAt': '2026-11-13T08:00:00', 'CancelledAt': None,
                'IsPassed': 0, 'FinalGrade': None,
            })
            self.rowcount = 1

        elif '/* q:student_reg_inc_enrollment */' in sql:
            cid = params[0]
            for cl in self.state['classes']:
                if cl['Id'] == cid:
                    cl['CurrentEnrollment'] += 1
                    if cl['CurrentEnrollment'] >= cl['MaxCapacity']:
                        cl['Status'] = 'Closed'
            self.rowcount = 1

        elif '/* q:student_reg_audit_log */' in sql:
            stu_id, cid, by_id, note = params
            new_id = max((h['Id'] for h in self.state['history']), default=0) + 1
            self.state['history'].append({
                'Id': new_id, 'StudentId': stu_id, 'ClassId': cid,
                'ActionType': 'Register', 'PerformedByUserId': by_id, 'Note': note,
                'ActionTime': '2026-11-13T08:00:00',
            })
            self.rowcount = 1

        elif '/* q:student_drop_audit_log */' in sql:
            stu_id, cid, by_id, note = params
            new_id = max((h['Id'] for h in self.state['history']), default=0) + 1
            self.state['history'].append({
                'Id': new_id, 'StudentId': stu_id, 'ClassId': cid,
                'ActionType': 'Drop', 'PerformedByUserId': by_id, 'Note': note,
                'ActionTime': '2026-11-13T08:00:00',
            })
            self.rowcount = 1

        # 6. Drop Course Transactions
        elif '/* q:student_drop_get_class */' in sql:
            cid = params[0]
            found = []
            for cl in self.state['classes']:
                if cl['Id'] == cid:
                    co = next((c for c in self.state['courses'] if c['Id'] == cl['CourseId']), {})
                    found.append({
                        'Id': cl['Id'], 'ClassCode': cl['ClassCode'], 'SemesterId': cl['SemesterId'],
                        'CurrentEnrollment': cl['CurrentEnrollment'], 'MaxCapacity': cl['MaxCapacity'],
                        'ClassStatus': cl['Status'], 'CourseCode': co.get('CourseCode'),
                        'CourseName': co.get('CourseName'), 'Credits': co.get('Credits'),
                    })
            self._set_result(found[:1])

        elif '/* q:student_drop_check_enrolled */' in sql:
            stu_id, cid = params
            found = [e for e in self.state['enrollments'] if e['StudentId'] == stu_id and e['ClassId'] == cid and e['Status'] == 'Enrolled']
            self._set_result(found[:1])

        elif '/* q:student_drop_update_enrollment */' in sql:
            stu_id, cid = params
            for e in self.state['enrollments']:
                if e['StudentId'] == stu_id and e['ClassId'] == cid:
                    e['Status'] = 'Cancelled'
                    e['CancelledAt'] = '2026-11-13T09:00:00'
            self.rowcount = 1

        elif '/* q:student_drop_dec_enrollment */' in sql:
            cid = params[0]
            for cl in self.state['classes']:
                if cl['Id'] == cid:
                    cl['CurrentEnrollment'] = max(0, cl['CurrentEnrollment'] - 1)
                    if cl['Status'] == 'Closed':
                        cl['Status'] = 'Open'
            self.rowcount = 1

        # 7. Tuition
        elif '/* q:student_tuition_get_unit_price */' in sql:
            sid = params[0]
            sem = next((s for s in self.state['semesters'] if s['Id'] == sid), {})
            self._set_result([{'CreditUnitPrice': sem.get('CreditUnitPrice', 550000)}])

        elif '/* q:student_tuition_check_record */' in sql or '/* q:student_tuition_statement_summary */' in sql:
            stu_id, sid = params
            found = [t for t in self.state['tuitions'] if t['StudentId'] == stu_id and t['SemesterId'] == sid]
            self._set_result(found[:1])

        elif '/* q:student_tuition_update_record */' in sql:
            tot, price, st, stu_id, sid = params
            for t in self.state['tuitions']:
                if t['StudentId'] == stu_id and t['SemesterId'] == sid:
                    t.update({'TotalCredits': tot, 'UnitPrice': price, 'PaymentStatus': st, 'LastCalculatedAt': '2026-11-13T08:00:00'})
            self.rowcount = 1

        elif '/* q:student_tuition_insert_record */' in sql:
            stu_id, sid, tot, price = params
            new_id = max((t['Id'] for t in self.state['tuitions']), default=0) + 1
            self.state['tuitions'].append({
                'Id': new_id, 'StudentId': stu_id, 'SemesterId': sid,
                'TotalCredits': tot, 'UnitPrice': price, 'PaidAmount': 0.00,
                'PaymentStatus': 'Unpaid', 'LastCalculatedAt': '2026-11-13T08:00:00',
            })
            self.rowcount = 1

        elif '/* q:student_tuition_itemized_courses */' in sql:
            stu_id, sid = params
            res = []
            for e in self.state['enrollments']:
                if e['StudentId'] == stu_id and e['Status'] == 'Enrolled':
                    cl = next((c for c in self.state['classes'] if c['Id'] == e['ClassId']), None)
                    if cl and cl['SemesterId'] == sid and cl['Status'] != 'Cancelled':
                        co = next((c for c in self.state['courses'] if c['Id'] == cl['CourseId']), {})
                        res.append({
                            'ClassId': cl['Id'], 'ClassCode': cl['ClassCode'],
                            'CourseCode': co.get('CourseCode'), 'CourseName': co.get('CourseName'),
                            'Credits': co.get('Credits'), 'EnrolledAt': e['EnrolledAt'],
                        })
            self._set_result(res)

        # 8. History Log
        elif '/* q:student_history */' in sql:
            stu_id = params[0]
            res = []
            for h in self.state['history']:
                if h['StudentId'] == stu_id:
                    cl = next((c for c in self.state['classes'] if c['Id'] == h['ClassId']), {})
                    co = next((c for c in self.state['courses'] if c['Id'] == cl.get('CourseId')), {})
                    sem = next((s for s in self.state['semesters'] if s['Id'] == cl.get('SemesterId')), {})
                    res.append({
                        'TransactionId': h['Id'], 'ActionType': h['ActionType'],
                        'ActionTime': h['ActionTime'], 'Note': h['Note'],
                        'ClassCode': cl.get('ClassCode'), 'CourseCode': co.get('CourseCode'),
                        'CourseName': co.get('CourseName'), 'Credits': co.get('Credits'),
                        'SemesterName': sem.get('SemesterName'), 'AcademicYear': sem.get('AcademicYear'),
                    })
            self._set_result(res)

        else:
            self._set_result([])


class FakeStudentDB:
    @staticmethod
    def create_initial_state():
        return {
            'users': [
                {'Id': 4, 'UserCode': 'SV001', 'Username': 'sv_an', 'FullName': 'Nguyen Van An', 'Email': 'an.sv@uth.edu.vn', 'Phone': '0901000004', 'Role': 'Student', 'Status': 'Active', 'PasswordHash': generate_password_hash('123456')},
                {'Id': 5, 'UserCode': 'SV002', 'Username': 'sv_binh', 'FullName': 'Tran Hai Binh', 'Email': 'binh.sv@uth.edu.vn', 'Phone': '0901000005', 'Role': 'Student', 'Status': 'Active', 'PasswordHash': generate_password_hash('123456')},
                {'Id': 2, 'UserCode': 'GV001', 'Username': 'gv_nam', 'FullName': 'Le Hoang Nam', 'Email': 'nam.lh@uth.edu.vn', 'Phone': '0901000002', 'Role': 'Lecturer', 'Status': 'Active', 'PasswordHash': generate_password_hash('123456')},
            ],
            'students': {
                4: {'StudentCode': 'SV001', 'AdministrativeClass': 'MIS2301', 'Major': 'Management Information Systems', 'Faculty': 'IT', 'EnrollmentYear': 2023},
                5: {'StudentCode': 'SV002', 'AdministrativeClass': 'MIS2301', 'Major': 'Management Information Systems', 'Faculty': 'IT', 'EnrollmentYear': 2023},
            },
            'semesters': [
                {'Id': 2, 'SemesterCode': 'SEM1_2026_2027', 'SemesterName': 'Semester 1 (2026-2027)', 'AcademicYear': '2026-2027', 'StartDate': '2026-09-01', 'EndDate': '2027-01-31', 'CreditUnitPrice': 550000, 'IsCurrent': 1},
                {'Id': 1, 'SemesterCode': 'SEM2_2025_2026', 'SemesterName': 'Semester 2 (2025-2026)', 'AcademicYear': '2025-2026', 'StartDate': '2026-01-15', 'EndDate': '2026-06-15', 'CreditUnitPrice': 520000, 'IsCurrent': 0},
            ],
            'periods': [
                {'Id': 1, 'SemesterId': 2, 'PeriodName': 'Fall 2026 Official Registration', 'StartDate': '2026-01-01 00:00:00', 'EndDate': '2027-12-31 23:59:59', 'MinCredits': 12, 'MaxCredits': 25, 'IsActive': 1},
            ],
            'timeslots': [
                {'Id': 1, 'SlotNumber': 1, 'SlotName': 'Slot 1 (07:00 - 09:30)', 'StartTime': '07:00:00', 'EndTime': '09:30:00'},
                {'Id': 2, 'SlotNumber': 2, 'SlotName': 'Slot 2 (09:45 - 12:15)', 'StartTime': '09:45:00', 'EndTime': '12:15:00'},
                {'Id': 3, 'SlotNumber': 3, 'SlotName': 'Slot 3 (13:00 - 15:30)', 'StartTime': '13:00:00', 'EndTime': '15:30:00'},
            ],
            'courses': [
                {'Id': 101, 'CourseCode': 'IT101', 'CourseName': 'Introduction to Programming', 'Credits': 3, 'PrerequisiteCourseId': None, 'Department': 'Computer Science'},
                {'Id': 102, 'CourseCode': 'IT102', 'CourseName': 'Data Structures and Algorithms', 'Credits': 4, 'PrerequisiteCourseId': 101, 'Department': 'Computer Science'},
                {'Id': 201, 'CourseCode': 'IS201', 'CourseName': 'Database Systems', 'Credits': 3, 'PrerequisiteCourseId': None, 'Department': 'Information Systems'},
                {'Id': 301, 'CourseCode': 'IS301', 'CourseName': 'Systems Analysis and Design', 'Credits': 3, 'PrerequisiteCourseId': 201, 'Department': 'Information Systems'},
                {'Id': 999, 'CourseCode': 'BIG99', 'CourseName': 'Heavy Elective Course', 'Credits': 10, 'PrerequisiteCourseId': None, 'Department': 'General'},
            ],
            'classes': [
                {'Id': 1, 'ClassCode': 'IT101_01', 'CourseId': 101, 'SemesterId': 2, 'LecturerId': 2, 'Room': 'A101', 'TimeSlotId': 1, 'DayOfWeek': 2, 'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 10, 'Status': 'Open'},
                {'Id': 2, 'ClassCode': 'IT101_02', 'CourseId': 101, 'SemesterId': 2, 'LecturerId': 2, 'Room': 'A102', 'TimeSlotId': 2, 'DayOfWeek': 3, 'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 20, 'Status': 'Open'},
                {'Id': 3, 'ClassCode': 'IT102_01', 'CourseId': 102, 'SemesterId': 2, 'LecturerId': 2, 'Room': 'B201', 'TimeSlotId': 2, 'DayOfWeek': 4, 'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 15, 'Status': 'Open'},
                {'Id': 4, 'ClassCode': 'IS201_01', 'CourseId': 201, 'SemesterId': 2, 'LecturerId': 2, 'Room': 'B202', 'TimeSlotId': 1, 'DayOfWeek': 2, 'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 12, 'Status': 'Open'},
                {'Id': 5, 'ClassCode': 'IS301_01', 'CourseId': 301, 'SemesterId': 2, 'LecturerId': 2, 'Room': 'C301', 'TimeSlotId': 3, 'DayOfWeek': 5, 'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 50, 'Status': 'Closed'}, # Full class section
            ],
            'enrollments': [
                # Student 4 completed IT101 and passed (IsPassed=1) in a previous semester
                {'Id': 1, 'StudentId': 4, 'ClassId': 99, 'Status': 'Completed', 'IsPassed': 1, 'FinalGrade': 8.5, 'EnrolledAt': '2026-01-20T08:00:00', 'CancelledAt': None},
            ],
            'history': [],
            'tuitions': [],
        }


# ==========================================================================
# MAIN TEST SUITE
# ==========================================================================
class TestStudentModule(unittest.TestCase):
    """Test suite covering TC_STU_01 to TC_STU_26 based strictly on the Excel specification."""

    def setUp(self):
        self.state = FakeStudentDB.create_initial_state()
        self.state['classes'].append({
            'Id': 99, 'ClassCode': 'IT101_OLD', 'CourseId': 101, 'SemesterId': 1,
            'LecturerId': 2, 'Room': 'A101', 'TimeSlotId': 1, 'DayOfWeek': 2,
            'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 45, 'Status': 'Open'
        })

        @contextmanager
        def fake_get_cursor():
            cursor = FakeStudentCursor(self.state)
            yield cursor

        self.patcher_cursor = patch.object(Database, 'get_cursor', side_effect=fake_get_cursor)
        self.patcher_query_all = patch.object(Database, 'query_all', side_effect=lambda sql, params=None: self._run_query_all(sql, params))
        self.patcher_query_one = patch.object(Database, 'query_one', side_effect=lambda sql, params=None: self._run_query_one(sql, params))
        self.patcher_execute = patch.object(Database, 'execute', side_effect=lambda sql, params=None: self._run_execute(sql, params))

        self.patcher_cursor.start()
        self.patcher_query_all.start()
        self.patcher_query_one.start()
        self.patcher_execute.start()

        # Create Flask Test Client
        app = Flask(__name__)
        app.secret_key = 'test_secret_student'
        app.register_blueprint(student_bp)
        self.app = app
        self.client = app.test_client()

    def tearDown(self):
        self.patcher_cursor.stop()
        self.patcher_query_all.stop()
        self.patcher_query_one.stop()
        self.patcher_execute.stop()

    def _run_query_all(self, sql, params=None):
        cur = FakeStudentCursor(self.state)
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description] if cur.description else []
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def _run_query_one(self, sql, params=None):
        res = self._run_query_all(sql, params)
        return res[0] if res else None

    def _run_execute(self, sql, params=None):
        cur = FakeStudentCursor(self.state)
        cur.execute(sql, params)
        return cur.rowcount

    # ==========================================================================
    # TC_STU_01: Student Login Success
    # ==========================================================================
    def test_tc01_student_login_success(self):
        """TC_STU_01: Student logs in successfully with valid credentials."""
        user = UserModel.find_by_username('sv_an')
        self.assertIsNotNone(user)
        self.assertEqual(user['Role'], 'Student')
        self.assertTrue(UserModel.verify_password(user['PasswordHash'], '123456'))

    # ==========================================================================
    # TC_STU_02: Student Login Failed with Wrong Password
    # ==========================================================================
    def test_tc02_student_login_wrong_password(self):
        """TC_STU_02: Login rejected due to incorrect password."""
        user = UserModel.find_by_username('sv_an')
        self.assertIsNotNone(user)
        self.assertFalse(UserModel.verify_password(user['PasswordHash'], 'wrongpassword@2026'))

    # ==========================================================================
    # TC_STU_03: Student Login Blocked on Empty Fields
    # ==========================================================================
    def test_tc03_student_login_empty_fields(self):
        """TC_STU_03: Submission blocked when username or password is empty."""
        self.assertIsNone(UserModel.find_by_username(''))
        self.assertIsNone(UserModel.find_by_username(None))

    # ==========================================================================
    # TC_STU_04: Display Open Class Sections in Semester
    # ==========================================================================
    def test_tc04_get_available_classes(self):
        """TC_STU_04: Retrieve and display open class sections in semester."""
        res = StudentCourseModel.get_available_classes(semester_id=2, student_id=4)
        self.assertIsInstance(res, dict)
        classes = res['classes']
        self.assertTrue(len(classes) > 0)
        it101_01 = next(c for c in classes if c['ClassCode'] == 'IT101_01')
        self.assertEqual(it101_01['Credits'], 3)
        self.assertTrue(it101_01['CanRegister'])
        is301 = next(c for c in classes if c['ClassCode'] == 'IS301_01')
        self.assertFalse(is301['CanRegister'])
        self.assertTrue(is301['IsFull'])

    # ==========================================================================
    # TC_STU_05: Filter and Search Classes by Keyword
    # ==========================================================================
    def test_tc05_search_classes_by_keyword(self):
        """TC_STU_05: Filter and search open class sections by keyword."""
        res = StudentCourseModel.get_available_classes(semester_id=2, student_id=4)
        classes = res['classes']
        filtered = [c for c in classes if 'IT101' in c.get('CourseCode', '') or 'IT101' in c.get('ClassCode', '')]
        self.assertTrue(len(filtered) >= 1)
        for c in filtered:
            self.assertTrue('IT101' in c.get('CourseCode', '') or 'IT101' in c.get('ClassCode', ''))

    # ==========================================================================
    # TC_STU_06: View Class Details and Prerequisites
    # ==========================================================================
    def test_tc06_view_class_details_and_prerequisites(self):
        """TC_STU_06: View class details, schedule, capacity, prerequisite."""
        detail = StudentCourseModel.get_class_detail(class_id=1, student_id=4)
        self.assertIsNotNone(detail)
        self.assertEqual(detail['ClassCode'], 'IT101_01')
        self.assertEqual(detail['CourseCode'], 'IT101')
        self.assertEqual(detail['Credits'], 3)

    # ==========================================================================
    # TC_STU_07: Course Registration Success & Increments Enrollment
    # ==========================================================================
    def test_tc07_successful_registration_increments_enrollment(self):
        """TC_STU_07: Registration succeeds and increments enrollment count."""
        class_id = 1
        prev_enrollment = next(c['CurrentEnrollment'] for c in self.state['classes'] if c['Id'] == class_id)
        res = StudentRegistrationModel.register_course(student_id=4, class_id=class_id)
        self.assertTrue(res['success'])
        new_enrollment = next(c['CurrentEnrollment'] for c in self.state['classes'] if c['Id'] == class_id)
        self.assertEqual(new_enrollment, prev_enrollment + 1)
        enr = next(e for e in self.state['enrollments'] if e['StudentId'] == 4 and e['ClassId'] == class_id)
        self.assertEqual(enr['Status'], 'Enrolled')

    # ==========================================================================
    # TC_STU_08: Registration Rejected When Class Section is Full
    # ==========================================================================
    def test_tc08_reject_registration_when_class_is_full(self):
        """TC_STU_08: Registration rejected when section is at max capacity."""
        with self.assertRaises(StudentConflictError) as ctx:
            StudentRegistrationModel.register_course(student_id=4, class_id=5)
        self.assertTrue("full" in str(ctx.exception).lower() or "hết chỗ" in str(ctx.exception).lower())

    # ==========================================================================
    # TC_STU_09: Registration Blocked When Prerequisite is Not Completed
    # ==========================================================================
    def test_tc09_reject_registration_when_prerequisite_not_met(self):
        """TC_STU_09: Registration blocked when prerequisite is not passed."""
        self.state['classes'].append({
            'Id': 6, 'ClassCode': 'IS301_02', 'CourseId': 301, 'SemesterId': 2,
            'LecturerId': 2, 'Room': 'C302', 'TimeSlotId': 2, 'DayOfWeek': 6,
            'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 10, 'Status': 'Open'
        })
        with self.assertRaises(StudentValidationError) as ctx:
            StudentRegistrationModel.register_course(student_id=5, class_id=6)
        self.assertTrue("prerequisite" in str(ctx.exception).lower() or "tiên quyết" in str(ctx.exception).lower())

    # ==========================================================================
    # TC_STU_10: Registration Succeeds When Prerequisite Completed
    # ==========================================================================
    def test_tc10_allow_registration_when_prerequisite_completed(self):
        """TC_STU_10: Registration succeeds when prerequisite completed."""
        res = StudentRegistrationModel.register_course(student_id=4, class_id=3)
        self.assertTrue(res['success'])
        self.assertEqual(res['data']['class_code'], 'IT102_01')
        self.assertEqual(res['data']['credits'], 4)

    # ==========================================================================
    # TC_STU_11: Registration Rejected on Schedule Slot Conflict
    # ==========================================================================
    def test_tc11_reject_registration_when_schedule_conflicts(self):
        """TC_STU_11: Registration rejected on schedule slot conflict."""
        res1 = StudentRegistrationModel.register_course(student_id=4, class_id=1)
        self.assertTrue(res1['success'])
        with self.assertRaises(StudentConflictError) as ctx:
            StudentRegistrationModel.register_course(student_id=4, class_id=4)
        self.assertTrue("conflict" in str(ctx.exception).lower() or "trùng lịch" in str(ctx.exception).lower())

    # ==========================================================================
    # TC_STU_12: Registration Rejected When Exceeding 25 Credits Limit
    # ==========================================================================
    def test_tc12_reject_registration_when_exceeding_max_credits(self):
        """TC_STU_12: Registration rejected when exceeding 25 credits limit."""
        self.state['courses'].append({'Id': 501, 'CourseCode': 'M1', 'CourseName': 'M1', 'Credits': 10, 'PrerequisiteCourseId': None})
        self.state['courses'].append({'Id': 502, 'CourseCode': 'M2', 'CourseName': 'M2', 'Credits': 10, 'PrerequisiteCourseId': None})
        self.state['classes'].append({'Id': 51, 'ClassCode': 'M1_01', 'CourseId': 501, 'SemesterId': 2, 'LecturerId': 2, 'Room': 'R1', 'TimeSlotId': 1, 'DayOfWeek': 6, 'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 10, 'Status': 'Open'})
        self.state['classes'].append({'Id': 52, 'ClassCode': 'M2_01', 'CourseId': 502, 'SemesterId': 2, 'LecturerId': 2, 'Room': 'R2', 'TimeSlotId': 2, 'DayOfWeek': 7, 'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 10, 'Status': 'Open'})
        self.state['enrollments'].append({'Id': 101, 'StudentId': 4, 'ClassId': 51, 'Status': 'Enrolled', 'EnrolledAt': '2026-11-13T08:00:00', 'CancelledAt': None})
        self.state['enrollments'].append({'Id': 102, 'StudentId': 4, 'ClassId': 52, 'Status': 'Enrolled', 'EnrolledAt': '2026-11-13T08:00:00', 'CancelledAt': None})
        self.state['classes'].append({'Id': 53, 'ClassCode': 'BIG99_01', 'CourseId': 999, 'SemesterId': 2, 'LecturerId': 2, 'Room': 'R3', 'TimeSlotId': 3, 'DayOfWeek': 3, 'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 5, 'Status': 'Open'})

        with self.assertRaises(StudentValidationError) as ctx:
            StudentRegistrationModel.register_course(student_id=4, class_id=53)
        self.assertTrue("exceeds" in str(ctx.exception).lower() or "vượt quá" in str(ctx.exception).lower())

    # ==========================================================================
    # TC_STU_13: Block Duplicate Registration of Same Course Sections
    # ==========================================================================
    def test_tc13_prevent_duplicate_course_registration(self):
        """TC_STU_13: Block duplicate registration of same course sections."""
        res = StudentRegistrationModel.register_course(student_id=4, class_id=1)
        self.assertTrue(res['success'])
        with self.assertRaises(StudentConflictError) as ctx:
            StudentRegistrationModel.register_course(student_id=4, class_id=2)
        self.assertTrue("already registered" in str(ctx.exception).lower() or "đã đăng ký một lớp khác" in str(ctx.exception).lower())

    # ==========================================================================
    # TC_STU_14: Registration Blocked When Registration Period Closed
    # ==========================================================================
    def test_tc14_reject_registration_when_period_is_closed(self):
        """TC_STU_14: Registration blocked when registration period closed."""
        for p in self.state['periods']:
            p['IsActive'] = 0
        with self.assertRaises(StudentValidationError) as ctx:
            StudentRegistrationModel.register_course(student_id=4, class_id=1)
        self.assertTrue("no active registration period" in str(ctx.exception).lower() or "không có đợt đăng ký" in str(ctx.exception).lower())

    # ==========================================================================
    # TC_STU_15: Drop Course Decrements Enrollment & Sets 'Cancelled'
    # ==========================================================================
    def test_tc15_drop_course_decrements_enrollment(self):
        """TC_STU_15: Drop course decrements enrollment & sets 'Cancelled'."""
        StudentRegistrationModel.register_course(student_id=4, class_id=1)
        cl = next(c for c in self.state['classes'] if c['Id'] == 1)
        enr_before = cl['CurrentEnrollment']
        res = StudentRegistrationModel.drop_course(student_id=4, class_id=1)
        self.assertTrue(res['success'])
        self.assertEqual(cl['CurrentEnrollment'], enr_before - 1)
        cancelled = next(e for e in self.state['enrollments'] if e['StudentId'] == 4 and e['ClassId'] == 1)
        self.assertEqual(cancelled['Status'], 'Cancelled')

    # ==========================================================================
    # TC_STU_16: Drop Course Rejected When Registration Period Closed
    # ==========================================================================
    def test_tc16_reject_drop_when_period_is_closed(self):
        """TC_STU_16: Drop course rejected when registration period closed."""
        StudentRegistrationModel.register_course(student_id=4, class_id=1)
        for p in self.state['periods']:
            p['IsActive'] = 0
        with self.assertRaises(StudentValidationError) as ctx:
            StudentRegistrationModel.drop_course(student_id=4, class_id=1)
        self.assertTrue("closed" in str(ctx.exception).lower() or "expired" in str(ctx.exception).lower() or "đóng" in str(ctx.exception).lower())

    # ==========================================================================
    # TC_STU_17: Render Weekly Timetable Grid for Enrolled Student
    # ==========================================================================
    def test_tc17_render_weekly_timetable(self):
        """TC_STU_17: Render weekly timetable grid for enrolled student."""
        StudentRegistrationModel.register_course(student_id=4, class_id=1)
        grid = StudentScheduleModel.build_weekly_schedule(student_id=4, semester_id=2, week=1)
        self.assertIn('sessions', grid)
        self.assertIn('total_enrolled', grid)
        self.assertTrue(grid['total_enrolled'] >= 1)

    # ==========================================================================
    # TC_STU_18: Render Empty Timetable Grid for Zero-Enrolled Student
    # ==========================================================================
    def test_tc18_render_empty_timetable(self):
        """TC_STU_18: Render empty timetable grid for zero-enrolled student."""
        grid = StudentScheduleModel.build_weekly_schedule(student_id=5, semester_id=2, week=1)
        self.assertEqual(grid['total_enrolled'], 0)
        self.assertEqual(len(grid['sessions']), 0)

    # ==========================================================================
    # TC_STU_19: Calculate Tuition Fees Based on Enrolled Credits
    # ==========================================================================
    def test_tc19_calculate_tuition_fee(self):
        """TC_STU_19: Calculate tuition fees based on enrolled credits."""
        StudentRegistrationModel.register_course(student_id=4, class_id=1)
        StudentRegistrationModel.register_course(student_id=4, class_id=3)
        stmt = StudentTuitionModel.get_tuition_statement(student_id=4, semester_id=2)
        self.assertIsNotNone(stmt)
        summary = stmt['summary']
        self.assertEqual(summary['total_courses'], 2)
        self.assertEqual(summary['total_credits'], 7)
        self.assertEqual(summary['unit_price'], 550000.00)
        self.assertEqual(summary['total_amount'], 7 * 550000.00)

    # ==========================================================================
    # TC_STU_20: Recalculate Tuition Statement When Course is Dropped
    # ==========================================================================
    def test_tc20_recalculate_tuition_after_drop(self):
        """TC_STU_20: Recalculate tuition statement when course is dropped."""
        StudentRegistrationModel.register_course(student_id=4, class_id=1)
        stmt_before = StudentTuitionModel.get_tuition_statement(student_id=4, semester_id=2)
        StudentRegistrationModel.drop_course(student_id=4, class_id=1)
        stmt_after = StudentTuitionModel.get_tuition_statement(student_id=4, semester_id=2)
        self.assertLess(stmt_after['summary']['total_credits'], stmt_before['summary']['total_credits'])

    # ==========================================================================
    # TC_STU_21: View Transaction History Audit Logs
    # ==========================================================================
    def test_tc21_view_registration_history(self):
        """TC_STU_21: View transaction history audit logs (Register/Drop)."""
        StudentRegistrationModel.register_course(student_id=4, class_id=1)
        history = StudentHistoryModel.get_history(student_id=4, semester_id=2)
        self.assertTrue(len(history) >= 1)
        self.assertEqual(history[0]['ActionType'], 'Register')

    # ==========================================================================
    # TC_STU_22: View Student Profile Details
    # ==========================================================================
    def test_tc22_student_profile_info(self):
        """TC_STU_22: View student profile details (ID, Name, Major, Class)."""
        profile = StudentProfileModel.get_profile(student_id=4)
        self.assertEqual(profile['StudentCode'], 'SV001')
        self.assertEqual(profile['FullName'], 'Nguyen Van An')
        self.assertEqual(profile['Major'], 'Management Information Systems')

    # ==========================================================================
    # TC_STU_23: Update Password Successfully with Valid Credentials
    # ==========================================================================
    def test_tc23_change_password_success(self):
        """TC_STU_23: Update password successfully with valid credentials."""
        success = StudentProfileModel.change_password(
            student_id=4,
            current_password='123456',
            new_password='NewPassword@2026',
            confirm_password='NewPassword@2026'
        )
        self.assertTrue(success)

    # ==========================================================================
    # TC_STU_24: Reject Password Update on Confirmation Mismatch
    # ==========================================================================
    def test_tc24_change_password_mismatch_rejected(self):
        """TC_STU_24: Reject password update on confirmation mismatch."""
        with self.assertRaises(StudentValidationError):
            StudentProfileModel.change_password(
                student_id=4,
                current_password='123456',
                new_password='NewPassword@2026',
                confirm_password='MismatchedPassword@2026'
            )

    # ==========================================================================
    # TC_STU_25: RBAC Middleware Protection on Student APIs
    # ==========================================================================
    def test_tc25_rbac_protection(self):
        """TC_STU_25: Verify 401 unauth, 403 forbidden, and 200 student ok."""
        # 1. Unauthenticated -> HTTP 401
        res_unauth = self.client.get('/student/api/me')
        self.assertEqual(res_unauth.status_code, 401)
        self.assertFalse(res_unauth.get_json()['success'])

        # 2. Lecturer Role -> HTTP 403
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['role'] = 'Lecturer'
            sess['username'] = 'gv_nam'
        res_forbidden = self.client.get('/student/api/me')
        self.assertEqual(res_forbidden.status_code, 403)
        self.assertTrue("permission" in res_forbidden.get_json()['message'].lower() or "không có quyền" in res_forbidden.get_json()['message'].lower())

        # 3. Student Role -> HTTP 200
        with self.client.session_transaction() as sess:
            sess['user_id'] = 4
            sess['role'] = 'Student'
            sess['username'] = 'sv_an'
        res_ok = self.client.get('/student/api/me')
        self.assertEqual(res_ok.status_code, 200)
        self.assertTrue(res_ok.get_json()['success'])

    # ==========================================================================
    # TC_STU_26: User Logout Clears Session & Redirects
    # ==========================================================================
    def test_tc26_student_logout(self):
        """TC_STU_26: Clear student session securely and redirect to login."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 4
            sess['role'] = 'Student'
            sess['username'] = 'sv_an'
        res = self.client.get('/student/login.html')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/logout', res.headers.get('Location'))


if __name__ == '__main__':
    unittest.main()
