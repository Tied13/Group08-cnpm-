"""
tests/test_admin.py
===================
Bộ Test Cases & Unit Test cho PHÂN HỆ ADMIN (Stage 4 - Testing & Quality).
Người phụ trách: Thành viên 3 - Hồng Tân (Backend Developer: Admin Module).

================================================================================
BẢNG THIẾT KẾ TEST CASES (TEST CASE SPECIFICATION)
================================================================================
| Mã TC     | Tên Test Case                                            | Đầu vào (Input)                                              | Kết quả kỳ vọng (Expected Output)                                           |
|-----------|----------------------------------------------------------|--------------------------------------------------------------|-----------------------------------------------------------------------------|
| TC_ADM_01 | Tạo môn học mới hợp lệ                                   | CourseCode='IT415', Credits=3, Prerequisite=IT101            | Tạo thành công (HTTP 201), đồng bộ bảng CoursePrerequisites                 |
| TC_ADM_02 | Tạo môn học trùng mã code (CourseCode)                   | CourseCode='IT101' (đã tồn tại trong CSDL)                   | Báo lỗi AdminConflictError (HTTP 409), không tạo bản ghi trùng              |
| TC_ADM_03 | Cập nhật môn học với vòng lặp môn tiên quyết             | IT101 đặt tiên quyết là IT102 (trong khi IT102 cần IT101)    | Báo lỗi AdminValidationError (HTTP 400), chặn vòng lặp tiên quyết           |
| TC_ADM_04 | Xếp lớp học phần bị trùng phòng học cùng ca & thứ        | Cùng Semester=2, DayOfWeek=2, TimeSlot=1, Room='A101'        | Báo lỗi AdminConflictError (HTTP 409) trùng phòng học                       |
| TC_ADM_05 | Xếp lớp học phần bị trùng lịch giảng viên cùng ca & thứ  | Cùng Semester=2, DayOfWeek=2, TimeSlot=1, LecturerId=2       | Báo lỗi AdminConflictError (HTTP 409) trùng ca giảng viên                   |
| TC_ADM_06 | Mở lớp học phần hợp lệ (không trùng phòng, không trùng GV)| Room='B202', DayOfWeek=4, TimeSlot=2, LecturerId=2           | Mở lớp thành công (HTTP 201), Status='Open', CurrentEnrollment=0            |
| TC_ADM_07 | Hủy lớp học phần có sĩ số < 15 sinh viên (Transaction)   | Lớp có 5 SV đang Enrolled (< 15 SV)                          | Classes.Status='Cancelled', cả 5 bản ghi Enrollments chuyển sang 'Cancelled'|
| TC_ADM_08 | Chặn hủy lớp học phần có sĩ số >= 15 sinh viên           | Lớp có 15 SV đang Enrolled (>= 15 SV)                        | Báo lỗi AdminValidationError (HTTP 400), giữ nguyên Status='Open'           |
| TC_ADM_09 | Đảm bảo tính toàn vẹn Transaction khi hủy lớp gặp sự cố  | Giả lập lỗi DB ở bước cập nhật Enrollments                   | Rollback toàn bộ: lớp vẫn giữ trạng thái 'Open', không bị mất đồng bộ       |
| TC_ADM_10 | Thêm tài khoản SV/GV & Mở khóa tài khoản bị khóa         | Tạo SV mới; Mở khóa tài khoản có Status='Locked', Fails=5    | Mật khẩu được băm; khi mở khóa Status='Active' và FailedLoginCount=0        |
| TC_ADM_11 | Cấu hình đợt đăng ký & kiểm tra ràng buộc ngày tháng     | StartDate < EndDate (hợp lệ) và StartDate >= EndDate (lỗi)   | Lưu đợt mới Active, đóng đợt cũ; báo lỗi 400 nếu ngày kết thúc <= bắt đầu   |
| TC_ADM_12 | Báo cáo thống kê tỷ lệ lấp đầy & tín chỉ sinh viên       | Học kỳ hiện hành có lớp học phần và sinh viên đăng ký        | Tính đúng FillRate (%) từng lớp và tổng tín chỉ / trạng thái từng sinh viên |
| TC_ADM_13 | Kiểm tra phân quyền RBAC trên các API `/admin/*`         | Truy cập khi chưa đăng nhập (401) hoặc role='Student' (403)  | Chặn truy cập trái phép với mã HTTP 401 / 403                               |
================================================================================

Cách chạy bộ kiểm thử:
    cd stage3&4
    python -m unittest discover -s tests -v
hoặc:
    python -m unittest tests/test_admin.py -v
"""

import copy
import os
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import patch

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
                {'Id': 1, 'UserCode': 'ADM001', 'Username': 'admin', 'PasswordHash': 'hash_admin',
                 'FullName': 'System Administrator', 'Email': 'admin@uth.edu.vn', 'Phone': '0901000001',
                 'Role': 'Admin', 'Status': 'Active', 'FailedLoginCount': 0, 'CreatedAt': '2026-09-01'},
                {'Id': 2, 'UserCode': 'GV001', 'Username': 'gv_quynh', 'PasswordHash': 'hash_gv1',
                 'FullName': 'Luu Quynh', 'Email': 'quynh.gv@uth.edu.vn', 'Phone': '0901000002',
                 'Role': 'Lecturer', 'Status': 'Active', 'FailedLoginCount': 0, 'CreatedAt': '2026-09-01'},
                {'Id': 3, 'UserCode': 'GV002', 'Username': 'gv_duc', 'PasswordHash': 'hash_gv2',
                 'FullName': 'Anh Duc', 'Email': 'duc.gv@uth.edu.vn', 'Phone': '0901000003',
                 'Role': 'Lecturer', 'Status': 'Active', 'FailedLoginCount': 0, 'CreatedAt': '2026-09-01'},
                {'Id': 4, 'UserCode': 'SV001', 'Username': 'sv_toan', 'PasswordHash': 'hash_sv1',
                 'FullName': 'Khanh Toan', 'Email': 'toan.sv@uth.edu.vn', 'Phone': '0901000004',
                 'Role': 'Student', 'Status': 'Active', 'FailedLoginCount': 0, 'CreatedAt': '2026-09-01'},
                {'Id': 5, 'UserCode': 'SV002', 'Username': 'sv_vuong', 'PasswordHash': 'hash_sv2',
                 'FullName': 'The Vuong', 'Email': 'vuong.sv@uth.edu.vn', 'Phone': '0901000005',
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
class AdminModuleUnitTest(unittest.TestCase):

    def setUp(self):
        self.fake_db = FakeDatabase()
        self.cursor_patcher = patch.object(Database, 'get_cursor', side_effect=self.fake_db.get_cursor)
        self.cursor_patcher.start()

        # Tạo Flask test app để kiểm thử cả tầng Controller/API
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

    # ------------------------------------------------------------------
    # 1. TEST QUẢN LÝ MÔN HỌC & TRÙNG MÃ CODE (Yêu cầu bắt buộc Stage 4)
    # ------------------------------------------------------------------
    def test_tc01_create_course_success_with_prerequisite(self):
        """TC_ADM_01: Tạo môn học mới hợp lệ và gắn môn tiên quyết."""
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

    def test_tc02_create_course_duplicate_code_rejected(self):
        """TC_ADM_02 (Trọng tâm Stage 4): Tạo môn học trùng mã code phải bị chặn (HTTP 409)."""
        with self.assertRaises(AdminConflictError) as ctx:
            AdminCourseModel.create_course(
                course_code='it101',  # Trùng mã IT101 (không phân biệt hoa/thường)
                course_name='Duplicate Course',
                credits=3,
            )
        self.assertIn('IT101', ctx.exception.message)
        self.assertEqual(ctx.exception.status_code, 409)

        # Kiểm tra qua cả API endpoint POST /admin/api/courses
        self._login_as_admin()
        resp = self.client.post('/admin/api/courses', json={
            'course_code': 'IT101',
            'course_name': 'Another Duplicate',
            'credits': 3,
        })
        self.assertEqual(resp.status_code, 409)
        body = resp.get_json()
        self.assertFalse(body['success'])
        self.assertIn('IT101', body['message'])

    def test_tc03_update_course_circular_prerequisite_rejected(self):
        """TC_ADM_03: Chặn vòng lặp môn tiên quyết (IT101 phụ thuộc IT102 trong khi IT102 phụ thuộc IT101)."""
        with self.assertRaises(AdminValidationError):
            AdminCourseModel.update_course(
                course_id=1,
                course_code='IT101',
                course_name='Introduction to Programming',
                credits=3,
                prerequisite_course_id=2,
            )

    # ------------------------------------------------------------------
    # 2. TEST XẾP LỚP TRÙNG PHÒNG / TRÙNG CA GIẢNG VIÊN (Yêu cầu bắt buộc Stage 4)
    # ------------------------------------------------------------------
    def test_tc04_create_class_room_conflict_rejected(self):
        """TC_ADM_04 (Trọng tâm Stage 4): Xếp lớp bị trùng phòng học trong cùng Thứ & Ca học phải báo lỗi."""
        # Lớp IT101_01 đang dùng phòng A101 vào Thứ 2 (DayOfWeek=2), Ca 1 (TimeSlotId=1), Học kỳ 2
        with self.assertRaises(AdminConflictError) as ctx:
            AdminClassModel.create_class(
                course_id=2,
                class_code='IT102_02',
                semester_id=2,
                room='A101',           # Trùng phòng A101
                day_of_week='Monday',  # Trùng Thứ 2
                time_slot_id=1,        # Trùng Ca 1
                max_capacity=40,
                lecturer_id=3,         # Khác giảng viên nhưng vẫn trùng phòng
            )
        self.assertIn('Trùng phòng học', ctx.exception.message)
        self.assertIn('IT101_01', ctx.exception.message)

    def test_tc05_create_class_lecturer_conflict_rejected(self):
        """TC_ADM_05 (Trọng tâm Stage 4): Xếp lớp bị trùng ca của giảng viên trong cùng thời điểm phải báo lỗi."""
        # Giảng viên GV001 (Id=2) đang dạy lớp IT101_01 vào Thứ 2 (DayOfWeek=2), Ca 1 (TimeSlotId=1)
        with self.assertRaises(AdminConflictError) as ctx:
            AdminClassModel.create_class(
                course_id=2,
                class_code='IT102_03',
                semester_id=2,
                room='B202',           # Khác phòng học
                day_of_week=2,         # Trùng Thứ 2
                time_slot_id=1,        # Trùng Ca 1
                max_capacity=40,
                lecturer_id=2,         # Trùng giảng viên GV001
            )
        self.assertIn('Trùng lịch giảng viên', ctx.exception.message)
        self.assertIn('IT101_01', ctx.exception.message)

    def test_tc06_create_class_valid_schedule_success(self):
        """TC_ADM_06: Mở lớp học phần thành công khi phòng học và giảng viên đều trống lịch."""
        created = AdminClassModel.create_class(
            course_id=2,
            class_code='IT102_05',
            semester_id=2,
            room='B202',
            day_of_week='Thursday',
            time_slot_id=2,
            max_capacity=40,
            lecturer_ref='GV001 - Luu Quynh',
        )
        self.assertEqual(created['ClassCode'], 'IT102_05')
        self.assertEqual(created['Status'], 'Open')
        self.assertEqual(created['DayOfWeek'], 5)

    # ------------------------------------------------------------------
    # 3. TEST HỦY LỚP HỌC PHẦN < 15 SV & TRANSACTION (Yêu cầu bắt buộc Stage 4)
    # ------------------------------------------------------------------
    def test_tc07_cancel_class_under_15_students_updates_class_and_all_enrollments(self):
        """
        TC_ADM_07 (Trọng tâm Stage 4):
        Hủy lớp học phần < 15 SV phải:
          1. Đổi trạng thái lớp trong bảng Classes sang 'Cancelled'.
          2. Tự động chuyển toàn bộ bản ghi trong bảng Enrollments của lớp sang 'Cancelled'.
        """
        self._login_as_admin()
        resp = self.client.post('/admin/api/classes/10/cancel')
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['data']['Status'], 'Cancelled')
        self.assertEqual(payload['data']['AffectedStudents'], 3)

        # Kiểm tra bảng Classes: trạng thái phải là Cancelled, CurrentEnrollment về 0
        cancelled_class = next(cl for cl in self.fake_db.state['classes'] if cl['Id'] == 10)
        self.assertEqual(cancelled_class['Status'], 'Cancelled')
        self.assertEqual(cancelled_class['CurrentEnrollment'], 0)

        # Kiểm tra bảng Enrollments: toàn bộ 3 sinh viên trong lớp đều chuyển sang Cancelled
        class_enrollments = [e for e in self.fake_db.state['enrollments'] if e['ClassId'] == 10]
        self.assertEqual(len(class_enrollments), 3)
        self.assertTrue(all(e['Status'] == 'Cancelled' for e in class_enrollments))
        self.assertTrue(all(e['CancelledAt'] is not None for e in class_enrollments))

        # Kiểm tra lịch sử & tính lại học phí cho cả 3 sinh viên
        self.assertEqual(len(self.fake_db.state['history']), 3)
        self.assertEqual(len(self.fake_db.state['tuition_recalcs']), 3)

    def test_tc08_cancel_class_with_15_or_more_students_rejected(self):
        """TC_ADM_08: Không cho phép hủy lớp học phần đã đủ sĩ số tối thiểu (>= 15 SV)."""
        with self.assertRaises(AdminValidationError) as ctx:
            AdminClassModel.cancel_class(class_id=11, admin_user_id=1)
        self.assertIn('15', ctx.exception.message)

        unchanged_class = next(cl for cl in self.fake_db.state['classes'] if cl['Id'] == 11)
        self.assertEqual(unchanged_class['Status'], 'Open')

    def test_tc09_cancel_class_transaction_rollback_on_error(self):
        """TC_ADM_09: Nếu bước cập nhật Enrollments gặp lỗi, trạng thái lớp phải được rollback về 'Open'."""
        self.fake_db.state['fail_on_tag'] = '/* q:cancel_enrollments */'
        with self.assertRaises(RuntimeError):
            AdminClassModel.cancel_class(class_id=10, admin_user_id=1)

        # Nhờ transaction rollback, lớp IT101_01 vẫn ở trạng thái Open và 3 SV vẫn Enrolled
        cls = next(cl for cl in self.fake_db.state['classes'] if cl['Id'] == 10)
        self.assertEqual(cls['Status'], 'Open')
        self.assertEqual(cls['CurrentEnrollment'], 3)
        self.assertTrue(all(e['Status'] == 'Enrolled' for e in self.fake_db.state['enrollments']))

    # ------------------------------------------------------------------
    # 4. TEST QUẢN LÝ TÀI KHOẢN & CẤU HÌNH ĐỢT ĐĂNG KÝ & RBAC
    # ------------------------------------------------------------------
    def test_tc10_create_user_and_unlock_locked_account(self):
        """TC_ADM_10: Thêm tài khoản mới và mở khóa tài khoản bị khóa do nhập sai mật khẩu 5 lần."""
        new_user = AdminUserModel.create_user(
            role='Student',
            user_code='SV2026099',
            full_name='Hong Tan Test',
            email='tan.sv@uth.edu.vn',
            department='Software Engineering',
            password='Password123',
        )
        self.assertEqual(new_user['UserCode'], 'SV2026099')
        self.assertEqual(new_user['Status'], 'Active')

        # Tài khoản SV002 (Id=5) đang bị Locked với FailedLoginCount=5 -> Mở khóa
        unlocked = AdminUserModel.set_user_status(user_id=5, status='Active')
        self.assertEqual(unlocked['Status'], 'Active')
        sv002 = next(u for u in self.fake_db.state['users'] if u['Id'] == 5)
        self.assertEqual(sv002['Status'], 'Active')
        self.assertEqual(sv002['FailedLoginCount'], 0)

    def test_tc11_save_registration_period_validation(self):
        """TC_ADM_11: Thiết lập đợt đăng ký mới và chặn trường hợp ngày kết thúc <= ngày bắt đầu."""
        with self.assertRaises(AdminValidationError):
            AdminPeriodModel.save_period(
                semester_id=2,
                start_date='2026-12-10T08:00',
                end_date='2026-12-01T08:00',
            )

        saved = AdminPeriodModel.save_period(
            semester_id=2,
            start_date='2026-10-01T08:00',
            end_date='2026-12-20T17:00',
        )
        self.assertTrue(saved['IsActive'])
        # Đợt cũ phải tự động chuyển về IsActive = 0
        old_period = next(p for p in self.fake_db.state['periods'] if p['Id'] == 1)
        self.assertEqual(old_period['IsActive'], 0)

    def test_tc12_reports_section_fill_rate_and_student_credits(self):
        """TC_ADM_12: Báo cáo thống kê tỷ lệ lấp đầy lớp học phần và tín chỉ theo sinh viên."""
        report = AdminReportModel.full_report(semester_id=2)
        self.assertEqual(report['Summary']['TotalSections'], 2)
        self.assertEqual(report['Summary']['TotalEnrollments'], 18)  # 3 + 15

        sec_it101 = next(s for s in report['Sections'] if s['ClassCode'] == 'IT101_01')
        self.assertEqual(sec_it101['FillRate'], 6.0)  # 3 / 50 = 6.0%

        stu_sv001 = next(st for st in report['Students'] if st['StudentCode'] == 'SV001')
        self.assertEqual(stu_sv001['TotalCredits'], 3)
        self.assertEqual(stu_sv001['Compliance'], 'Below Minimum')  # 3 < 12 tín chỉ

    def test_tc13_rbac_blocks_non_admin_requests(self):
        """TC_ADM_13: Chặn truy cập API Admin khi chưa đăng nhập (401) hoặc đăng nhập bằng tài khoản Student (403)."""
        unauth_resp = self.client.get('/admin/api/users')
        self.assertEqual(unauth_resp.status_code, 401)

        with self.client.session_transaction() as sess:
            sess['user_id'] = 4
            sess['username'] = 'sv_toan'
            sess['role'] = 'Student'
        forbidden_resp = self.client.get('/admin/api/users')
        self.assertEqual(forbidden_resp.status_code, 403)


if __name__ == '__main__':
    unittest.main(verbosity=2)
