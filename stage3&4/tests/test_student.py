"""
tests/test_student.py
=====================
Bộ Test Cases & Unit Test cho PHÂN HỆ SINH VIÊN (Stage 4 - Testing & Quality).
Hệ thống Đăng ký Môn học (Course Registration System).

================================================================================
BẢNG THIẾT KẾ TEST CASES (TEST CASE SPECIFICATION)
================================================================================
| Mã TC     | Tên Test Case                                             | Đầu vào (Input)                                        | Kết quả kỳ vọng (Expected Output)                                           |
|-----------|-----------------------------------------------------------|--------------------------------------------------------|-----------------------------------------------------------------------------|
| TC_STU_01 | Hiển thị danh mục lớp học phần đang mở                    | SemesterId=2, StudentId=4                             | Danh sách lớp kèm tình trạng chỗ trống, môn tiên quyết, khả năng đăng ký     |
| TC_STU_02 | ĐK thất bại do Lớp hết chỗ (CurrentEnrollment >= Max)     | ClassId=1 (CurrentEnrollment=50, MaxCapacity=50)       | Báo lỗi StudentConflictError (HTTP 409), sĩ số không tăng                  |
| TC_STU_03 | ĐK thất bại do Chưa hoàn thành môn tiên quyết             | Môn IT102 cần tiên quyết IT101 nhưng SV chưa học/qua   | Báo lỗi StudentValidationError (HTTP 400), chặn đăng ký                     |
| TC_STU_04 | ĐK thành công khi Đã hoàn thành môn tiên quyết            | Môn IT102, SV đã hoàn thành IT101 (IsPassed=1)         | Đăng ký thành công (HTTP 201), tạo Enrollment 'Enrolled'                   |
| TC_STU_05 | ĐK thất bại do Trùng lịch học (DayOfWeek & TimeSlot)      | Lớp trùng Thứ 2, Ca 1 với lớp đã ghi danh trong kỳ    | Báo lỗi StudentConflictError (HTTP 409), chỉ rõ lớp và ca học bị trùng     |
| TC_STU_06 | ĐK thất bại do Vượt quá 25 tín chỉ tối đa                 | Tổng tín chỉ hiện tại 23 TC + môn mới 4 TC = 27 TC     | Báo lỗi StudentValidationError (HTTP 400), giới hạn tối đa 25 TC           |
| TC_STU_07 | ĐK môn học thành công & Tăng biến đếm sĩ số lên 1         | Thỏa mãn đủ 4 điều kiện nghiêm ngặt                    | CurrentEnrollment tăng +1, lưu Enrollments 'Enrolled', audit log 'Register' |
| TC_STU_08 | Chặn đăng ký trùng 2 lớp của cùng một môn học             | Đã đăng ký IT101_01, tiếp tục đăng ký IT101_02         | Báo lỗi StudentConflictError (HTTP 409) trùng môn học trong kỳ             |
| TC_STU_09 | Chặn đăng ký khi Đợt đăng ký môn học đã đóng              | Cổng đăng ký IsActive=0 hoặc ngoài khoảng thời gian    | Báo lỗi StudentValidationError (HTTP 400) đợt đăng ký đóng                 |
| TC_STU_10 | Hủy đăng ký môn học thành công & Giảm sĩ số đi 1          | SV đang Enrolled hủy lớp trong thời gian mở cổng       | CurrentEnrollment giảm -1, Enrollment -> 'Cancelled', audit log 'Drop'      |
| TC_STU_11 | Render Thời khóa biểu dạng lưới tuần                      | SV có các lớp Enrolled trong tuần                      | Phân bố chính xác các ca học theo Thứ (Thứ 2 - CN) và Ca học (Slot 1..N)   |
| TC_STU_12 | Tự động tính toán tổng học phí theo đơn giá tín chỉ      | Tổng 7 tín chỉ, Đơn giá 550.000 VNĐ                    | Tổng tiền = 7 * 550.000 = 3.850.000 VNĐ, bảng kê chi tiết từng môn         |
| TC_STU_13 | Kiểm tra phân quyền RBAC trên các API `/student/*`        | Chưa đăng nhập (401) hoặc role='Lecturer' (403)        | Chặn truy cập trái phép với mã HTTP 401 / 403                               |
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

# Đảm bảo import được các module trong thư mục stage3&4
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
# FAKE IN-MEMORY DATABASE ENGINE (Dành cho Unit Test độc lập)
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
                {'Id': 4, 'UserCode': 'SV001', 'Username': 'sv_toan', 'FullName': 'Khanh Toan', 'Email': 'toan@uth.edu.vn', 'Phone': '0901000004', 'Role': 'Student', 'Status': 'Active'},
                {'Id': 5, 'UserCode': 'SV002', 'Username': 'sv_vuong', 'FullName': 'The Vuong', 'Email': 'vuong@uth.edu.vn', 'Phone': '0901000005', 'Role': 'Student', 'Status': 'Active'},
                {'Id': 2, 'UserCode': 'GV001', 'Username': 'gv_quynh', 'FullName': 'Luu Quynh', 'Email': 'quynh@uth.edu.vn', 'Phone': '0901000002', 'Role': 'Lecturer', 'Status': 'Active'},
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
                {'Id': 1, 'SlotNumber': 1, 'SlotName': 'Ca 1 (07:00 - 09:30)', 'StartTime': '07:00:00', 'EndTime': '09:30:00'},
                {'Id': 2, 'SlotNumber': 2, 'SlotName': 'Ca 2 (09:45 - 12:15)', 'StartTime': '09:45:00', 'EndTime': '12:15:00'},
                {'Id': 3, 'SlotNumber': 3, 'SlotName': 'Ca 3 (13:00 - 15:30)', 'StartTime': '13:00:00', 'EndTime': '15:30:00'},
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
                {'Id': 5, 'ClassCode': 'IS301_01', 'CourseId': 301, 'SemesterId': 2, 'LecturerId': 2, 'Room': 'C301', 'TimeSlotId': 3, 'DayOfWeek': 5, 'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 50, 'Status': 'Closed'}, # Lớp đầy chỗ
            ],
            'enrollments': [
                # SV 4 đã học xong môn IT101 và qua môn (IsPassed=1) ở kỳ trước
                {'Id': 1, 'StudentId': 4, 'ClassId': 99, 'Status': 'Completed', 'IsPassed': 1, 'FinalGrade': 8.5, 'EnrolledAt': '2026-01-20T08:00:00', 'CancelledAt': None},
            ],
            'history': [],
            'tuitions': [],
        }


# ==========================================================================
# TEST SUITE CHÍNH
# ==========================================================================
class TestStudentModule(unittest.TestCase):

    def setUp(self):
        self.state = FakeStudentDB.create_initial_state()
        # Đưa lớp của môn IT101 vào lịch sử học tập của SV 4
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

        # Tạo Flask Test Client
        app = Flask(__name__)
        app.secret_key = 'test_secret_student'
        app.register_blueprint(student_bp)
        self.app = app
        self.client = app.test_client()

    def tearDown(self):
        patch.stopall()

    def _run_query_all(self, sql, params=None):
        cur = FakeStudentCursor(self.state)
        cur.execute(sql, params)
        if not cur.description:
            return []
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def _run_query_one(self, sql, params=None):
        res = self._run_query_all(sql, params)
        return res[0] if res else None

    def _run_execute(self, sql, params=None):
        cur = FakeStudentCursor(self.state)
        cur.execute(sql, params)
        return cur.rowcount

    # --------------------------------------------------------------------------
    # TC_STU_01: Hiển thị danh mục các lớp học phần đang mở trong đợt đăng ký
    # --------------------------------------------------------------------------
    def test_tc01_get_available_classes(self):
        data = StudentCourseModel.get_available_classes(student_id=4, semester_id=2)
        classes = data['classes']
        self.assertTrue(len(classes) > 0)
        self.assertEqual(data['current_credits'], 0)
        self.assertEqual(data['min_credits'], 12)
        self.assertEqual(data['max_credits'], 25)

        # Lớp IT101_01 còn chỗ trống
        it101 = next(c for c in classes if c['ClassCode'] == 'IT101_01')
        self.assertTrue(it101['CanRegister'])
        self.assertEqual(it101['RemainingSeats'], 40)
        self.assertFalse(it101['IsFull'])

        # Lớp IS301_01 đã đủ sĩ số
        is301 = next(c for c in classes if c['ClassCode'] == 'IS301_01')
        self.assertFalse(is301['CanRegister'])
        self.assertTrue(is301['IsFull'])
        self.assertIn("đủ chỗ", is301['ReasonDisabled'])

    # --------------------------------------------------------------------------
    # TC_STU_02: Điều kiện 1: Chặn đăng ký khi lớp học phần đã hết chỗ trống
    # --------------------------------------------------------------------------
    def test_tc02_reject_registration_when_class_is_full(self):
        # ClassId=5 (IS301_01) có CurrentEnrollment=50, MaxCapacity=50
        with self.assertRaises(StudentConflictError) as ctx:
            StudentRegistrationModel.register_course(student_id=4, class_id=5)
        self.assertIn("đã hết chỗ trống", str(ctx.exception))

    # --------------------------------------------------------------------------
    # TC_STU_03: Điều kiện 2: Chặn đăng ký khi chưa hoàn thành môn tiên quyết
    # --------------------------------------------------------------------------
    def test_tc03_reject_registration_when_prerequisite_not_met(self):
        # SV 5 chưa từng học môn tiên quyết IS201, cố tình đăng ký IS301 (cần tiên quyết IS201)
        # Giả sử mở thêm 1 lớp IS301_02 còn chỗ trống
        self.state['classes'].append({
            'Id': 6, 'ClassCode': 'IS301_02', 'CourseId': 301, 'SemesterId': 2,
            'LecturerId': 2, 'Room': 'C302', 'TimeSlotId': 2, 'DayOfWeek': 6,
            'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 10, 'Status': 'Open'
        })
        with self.assertRaises(StudentValidationError) as ctx:
            StudentRegistrationModel.register_course(student_id=5, class_id=6)
        self.assertIn("chưa hoàn thành môn học tiên quyết", str(ctx.exception))

    # --------------------------------------------------------------------------
    # TC_STU_04: Điều kiện 2: Cho phép đăng ký khi đã hoàn thành môn tiên quyết
    # --------------------------------------------------------------------------
    def test_tc04_allow_registration_when_prerequisite_completed(self):
        # SV 4 đã hoàn thành IT101 (IsPassed=1 trong setUp), đăng ký IT102 (ClassId=3)
        res = StudentRegistrationModel.register_course(student_id=4, class_id=3)
        self.assertTrue(res['success'])
        self.assertEqual(res['data']['class_code'], 'IT102_01')
        self.assertEqual(res['data']['credits'], 4)

    # --------------------------------------------------------------------------
    # TC_STU_05: Điều kiện 3: Chặn đăng ký khi trùng ngày học và ca học
    # --------------------------------------------------------------------------
    def test_tc05_reject_registration_when_schedule_conflicts(self):
        # Bước 1: SV 4 đăng ký lớp IT101_01 (Thứ 2, Ca 1)
        res1 = StudentRegistrationModel.register_course(student_id=4, class_id=1)
        self.assertTrue(res1['success'])

        # Bước 2: SV 4 cố tình đăng ký tiếp lớp IS201_01 (Cũng học Thứ 2, Ca 1)
        with self.assertRaises(StudentConflictError) as ctx:
            StudentRegistrationModel.register_course(student_id=4, class_id=4)
        self.assertIn("Trùng lịch học với lớp IT101_01", str(ctx.exception))

    # --------------------------------------------------------------------------
    # TC_STU_06: Điều kiện 4: Chặn đăng ký khi vượt quá 25 tín chỉ tối đa
    # --------------------------------------------------------------------------
    def test_tc06_reject_registration_when_exceeding_max_credits(self):
        # Giả lập SV 4 đã đăng ký 20 tín chỉ
        # Thêm 2 lớp đã Enrolled tổng 20 tín chỉ vào CSDL
        self.state['courses'].append({'Id': 501, 'CourseCode': 'M1', 'CourseName': 'M1', 'Credits': 10, 'PrerequisiteCourseId': None})
        self.state['courses'].append({'Id': 502, 'CourseCode': 'M2', 'CourseName': 'M2', 'Credits': 10, 'PrerequisiteCourseId': None})
        self.state['classes'].append({'Id': 51, 'ClassCode': 'M1_01', 'CourseId': 501, 'SemesterId': 2, 'LecturerId': 2, 'Room': 'R1', 'TimeSlotId': 1, 'DayOfWeek': 6, 'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 10, 'Status': 'Open'})
        self.state['classes'].append({'Id': 52, 'ClassCode': 'M2_01', 'CourseId': 502, 'SemesterId': 2, 'LecturerId': 2, 'Room': 'R2', 'TimeSlotId': 2, 'DayOfWeek': 7, 'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 10, 'Status': 'Open'})
        self.state['enrollments'].append({'Id': 101, 'StudentId': 4, 'ClassId': 51, 'Status': 'Enrolled', 'EnrolledAt': '2026-11-13T08:00:00', 'CancelledAt': None})
        self.state['enrollments'].append({'Id': 102, 'StudentId': 4, 'ClassId': 52, 'Status': 'Enrolled', 'EnrolledAt': '2026-11-13T08:00:00', 'CancelledAt': None})

        # Hiện tại đã có 20 tín chỉ. Đăng ký thêm môn BIG99 (10 tín chỉ) -> Tổng 30 tín chỉ > 25 tín chỉ
        self.state['classes'].append({'Id': 53, 'ClassCode': 'BIG99_01', 'CourseId': 999, 'SemesterId': 2, 'LecturerId': 2, 'Room': 'R3', 'TimeSlotId': 3, 'DayOfWeek': 3, 'MinCapacity': 15, 'MaxCapacity': 50, 'CurrentEnrollment': 5, 'Status': 'Open'})

        with self.assertRaises(StudentValidationError) as ctx:
            StudentRegistrationModel.register_course(student_id=4, class_id=53)
        self.assertIn("vượt quá giới hạn tối đa", str(ctx.exception))

    # --------------------------------------------------------------------------
    # TC_STU_07: ĐK thành công & Tăng biến đếm CurrentEnrollment của lớp lên 1
    # --------------------------------------------------------------------------
    def test_tc07_successful_registration_increments_enrollment_and_logs(self):
        class_id = 1
        prev_enrollment = next(c['CurrentEnrollment'] for c in self.state['classes'] if c['Id'] == class_id)

        res = StudentRegistrationModel.register_course(student_id=4, class_id=class_id)
        self.assertTrue(res['success'])

        # 1. Sĩ số lớp tăng lên 1
        new_enrollment = next(c['CurrentEnrollment'] for c in self.state['classes'] if c['Id'] == class_id)
        self.assertEqual(new_enrollment, prev_enrollment + 1)

        # 2. Bản ghi Enrollments được tạo với Status = 'Enrolled'
        enr = next((e for e in self.state['enrollments'] if e['StudentId'] == 4 and e['ClassId'] == class_id), None)
        self.assertIsNotNone(enr)
        self.assertEqual(enr['Status'], 'Enrolled')

        # 3. Ghi log kiểm toán vào RegistrationHistory (ActionType = 'Register')
        hist = [h for h in self.state['history'] if h['StudentId'] == 4 and h['ClassId'] == class_id and h['ActionType'] == 'Register']
        self.assertEqual(len(hist), 1)

        # 4. Học phí được tự động tính toán
        tuition = next((t for t in self.state['tuitions'] if t['StudentId'] == 4 and t['SemesterId'] == 2), None)
        self.assertIsNotNone(tuition)
        self.assertEqual(tuition['TotalCredits'], 3)

    # --------------------------------------------------------------------------
    # TC_STU_08: Chặn đăng ký trùng 2 lớp của cùng một môn học trong kỳ
    # --------------------------------------------------------------------------
    def test_tc08_prevent_duplicate_course_registration(self):
        # Đăng ký lớp IT101_01
        StudentRegistrationModel.register_course(student_id=4, class_id=1)

        # Cố tình đăng ký lớp IT101_02 (Cùng môn IT101 nhưng khác ca học Thứ 3, Ca 2)
        with self.assertRaises(StudentConflictError) as ctx:
            StudentRegistrationModel.register_course(student_id=4, class_id=2)
        self.assertIn("Bạn đã đăng ký một lớp khác (IT101_01) của môn học này", str(ctx.exception))

    # --------------------------------------------------------------------------
    # TC_STU_09: Chặn đăng ký khi đợt đăng ký môn học đã đóng hoặc hết hạn
    # --------------------------------------------------------------------------
    def test_tc09_reject_registration_when_period_is_closed(self):
        # Đóng đợt đăng ký
        self.state['periods'][0]['IsActive'] = 0

        with self.assertRaises(StudentValidationError) as ctx:
            StudentRegistrationModel.register_course(student_id=4, class_id=1)
        self.assertIn("không có đợt đăng ký môn học nào đang mở", str(ctx.exception))

    # --------------------------------------------------------------------------
    # TC_STU_10: Hủy môn học thành công, giảm CurrentEnrollment và đổi Status Cancelled
    # --------------------------------------------------------------------------
    def test_tc10_drop_course_decrements_enrollment_and_marks_cancelled(self):
        # Đăng ký trước lớp IT101_01
        StudentRegistrationModel.register_course(student_id=4, class_id=1)
        enrollment_after_reg = next(c['CurrentEnrollment'] for c in self.state['classes'] if c['Id'] == 1)

        # Thực hiện hủy môn học
        res = StudentRegistrationModel.drop_course(student_id=4, class_id=1)
        self.assertTrue(res['success'])

        # 1. Sĩ số lớp giảm đi 1
        enrollment_after_drop = next(c['CurrentEnrollment'] for c in self.state['classes'] if c['Id'] == 1)
        self.assertEqual(enrollment_after_drop, enrollment_after_reg - 1)

        # 2. Bản ghi Enrollments cập nhật Status = 'Cancelled'
        enr = next(e for e in self.state['enrollments'] if e['StudentId'] == 4 and e['ClassId'] == 1)
        self.assertEqual(enr['Status'], 'Cancelled')
        self.assertIsNotNone(enr['CancelledAt'])

        # 3. Ghi nhận audit log ActionType = 'Drop'
        hist = [h for h in self.state['history'] if h['StudentId'] == 4 and h['ClassId'] == 1 and h['ActionType'] == 'Drop']
        self.assertEqual(len(hist), 1)

        # 4. Học phí được tự động tính lại (0 tín chỉ)
        tuition = next(t for t in self.state['tuitions'] if t['StudentId'] == 4 and t['SemesterId'] == 2)
        self.assertEqual(tuition['TotalCredits'], 0)

    # --------------------------------------------------------------------------
    # TC_STU_11: Render Thời khóa biểu theo dạng lưới tuần
    # --------------------------------------------------------------------------
    def test_tc11_render_weekly_timetable(self):
        # Đăng ký 2 môn học: IT101_01 (Thứ 2, Ca 1) và IT102_01 (Thứ 4, Ca 2)
        StudentRegistrationModel.register_course(student_id=4, class_id=1)
        StudentRegistrationModel.register_course(student_id=4, class_id=3)

        grid = StudentScheduleModel.build_weekly_schedule(student_id=4, semester_id=2, week=1)
        self.assertEqual(grid['total_enrolled'], 2)
        self.assertEqual(grid['total_credits'], 7)
        self.assertEqual(len(grid['slots']), 3)

        sessions = grid['sessions']
        self.assertEqual(len(sessions), 2)
        # Kiểm tra lớp 1: Thứ 2 (DayOfWeek=2), Ca 1 (TimeSlotId=1)
        s1 = next(s for s in sessions if s['ClassCode'] == 'IT101_01')
        self.assertEqual(s1['DayOfWeek'], 2)
        self.assertEqual(s1['TimeSlotId'], 1)

        # Kiểm tra lớp 2: Thứ 4 (DayOfWeek=4), Ca 2 (TimeSlotId=2)
        s2 = next(s for s in sessions if s['ClassCode'] == 'IT102_01')
        self.assertEqual(s2['DayOfWeek'], 4)
        self.assertEqual(s2['TimeSlotId'], 2)

    # --------------------------------------------------------------------------
    # TC_STU_12: Tự động tính toán tổng học phí dựa trên đơn giá tín chỉ
    # --------------------------------------------------------------------------
    def test_tc12_calculate_tuition_fee(self):
        # Đăng ký IT101_01 (3 TC) + IT102_01 (4 TC) = 7 TC
        # Đơn giá học kỳ 2: 550.000 VNĐ / TC
        StudentRegistrationModel.register_course(student_id=4, class_id=1)
        StudentRegistrationModel.register_course(student_id=4, class_id=3)

        stmt = StudentTuitionModel.get_tuition_statement(student_id=4, semester_id=2)
        summary = stmt['summary']
        self.assertEqual(summary['total_courses'], 2)
        self.assertEqual(summary['total_credits'], 7)
        self.assertEqual(summary['unit_price'], 550000.00)
        expected_total = 7 * 550000.00
        self.assertEqual(summary['total_amount'], expected_total)
        self.assertEqual(len(stmt['items']), 2)

        # Chi tiết môn IT101
        it101_item = next(i for i in stmt['items'] if i['course_code'] == 'IT101')
        self.assertEqual(it101_item['credits'], 3)
        self.assertEqual(it101_item['subtotal'], 3 * 550000.00)

        # Chi tiết môn IT102
        it102_item = next(i for i in stmt['items'] if i['course_code'] == 'IT102')
        self.assertEqual(it102_item['credits'], 4)
        self.assertEqual(it102_item['subtotal'], 4 * 550000.00)

    # --------------------------------------------------------------------------
    # TC_STU_13: Kiểm tra phân quyền RBAC trên API `/student/*`
    # --------------------------------------------------------------------------
    def test_tc13_rbac_protection(self):
        # 1. Chưa đăng nhập truy cập API -> HTTP 401
        res_unauth = self.client.get('/student/api/me')
        self.assertEqual(res_unauth.status_code, 401)
        self.assertFalse(res_unauth.get_json()['success'])

        # 2. Giảng viên (Role='Lecturer') truy cập API sinh viên -> HTTP 403
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['role'] = 'Lecturer'
            sess['username'] = 'gv_quynh'

        res_forbidden = self.client.get('/student/api/me')
        self.assertEqual(res_forbidden.status_code, 403)
        self.assertIn("không có quyền truy cập", res_forbidden.get_json()['message'])

        # 3. Sinh viên hợp lệ -> HTTP 200
        with self.client.session_transaction() as sess:
            sess['user_id'] = 4
            sess['role'] = 'Student'
            sess['username'] = 'sv_toan'

        res_ok = self.client.get('/student/api/me')
        self.assertEqual(res_ok.status_code, 200)
        self.assertTrue(res_ok.get_json()['success'])


if __name__ == '__main__':
    unittest.main()
