/* ==========================================================================
   static/js/lecturer.js  -  PHAN HE GIANG VIEN (Faculty & Lecturer Portal)

   Chuc nang: xem lich day theo tuan, xem danh sach lop phu trach, xem danh sach
   sinh vien theo lop va xuat CSV, doi mat khau.
   Goi API: /lecturer/api/... (controllers/lecturer_controller.py).
   File dung chung cho 4 trang lecturer-*.html; moi trang tu nhan biet bang id phan tu.
   ========================================================================== */

const LEC_API = '/lecturer/api';
const LEC_PAGE_SIZE_OPTIONS = [5, 10, 20];

const lecState = {
  semesterId: null,
  classes: [],            // lop duoc phan cong (trang classes / schedule)
  filtered: [],
  students: [],           // sinh vien cua lop dang chon
  studentsFiltered: [],
  week: null,             // tuan dang xem (null = tuan hien tai)
  totalWeeks: 1,
  paging: {},             // trang hien tai / so dong moi trang theo tung bang
};

/* ------------------------------ TIEN ICH ------------------------------ */
function lecEl(id) { return document.getElementById(id); }

function lecEscape(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function lecSetText(id, text) {
  const el = lecEl(id);
  if (el) el.textContent = text;
}

function lecFormatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
}

function lecFormatDateTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const pad = (n) => String(n).padStart(2, '0');
  return `${lecFormatDate(iso)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/* Thong bao dang banner co san trong template (export-toast / pw-toast) */
let lecBannerTimer = null;
function lecBanner(bannerId, message, type = 'success') {
  const el = lecEl(bannerId);
  if (!el) {
    if (typeof showToast === 'function') showToast(message, type);  // main.js
    return;
  }
  el.textContent = message;
  el.className = `toast-banner toast-${type === 'danger' ? 'danger' : 'success'}`;
  clearTimeout(lecBannerTimer);
  lecBannerTimer = setTimeout(() => el.classList.add('hidden'), 4000);
}

async function lecGet(path) {
  try {
    const res = await fetch(`${LEC_API}${path}`, { headers: { Accept: 'application/json' } });
    if (res.status === 401) { window.location.href = '/login'; return null; }
    return await res.json();
  } catch (err) {
    console.error('API Error:', err);
    if (typeof showToast === 'function') showToast('Lỗi kết nối đến máy chủ!', 'danger');
    return null;
  }
}

/* ------------------------------ PHAN TRANG ------------------------------ */
function lecPaginate(key, items, containerId, renderRows) {
  const box = lecEl(containerId);
  const p = lecState.paging[key] || (lecState.paging[key] = { page: 1, size: 10 });
  const pages = Math.max(1, Math.ceil(items.length / p.size));
  p.page = Math.min(Math.max(p.page, 1), pages);
  const start = (p.page - 1) * p.size;
  renderRows(items.slice(start, start + p.size), start);

  if (!box) return;
  if (items.length === 0) { box.innerHTML = ''; return; }
  const from = start + 1;
  const to = Math.min(start + p.size, items.length);
  const sizeOpts = LEC_PAGE_SIZE_OPTIONS
    .map((n) => `<option value="${n}" ${n === p.size ? 'selected' : ''}>${n} / trang</option>`).join('');
  let btns = '';
  for (let i = 1; i <= pages; i++) {
    btns += `<button type="button" class="page-btn ${i === p.page ? 'active' : ''}" data-page="${i}">${i}</button>`;
  }
  box.innerHTML = `
    <div class="pagination-bar">
      <div class="pagination-info">Hiển thị <strong>${from}-${to}</strong> / <strong>${items.length}</strong></div>
      <div class="pagination-controls">
        <select class="page-size-select">${sizeOpts}</select>
        <button type="button" class="page-btn" data-page="${p.page - 1}" ${p.page === 1 ? 'disabled' : ''}>&lsaquo;</button>
        ${btns}
        <button type="button" class="page-btn" data-page="${p.page + 1}" ${p.page === pages ? 'disabled' : ''}>&rsaquo;</button>
      </div>
    </div>`;
  box.querySelectorAll('.page-btn').forEach((b) => b.addEventListener('click', () => {
    p.page = parseInt(b.dataset.page, 10);
    lecPaginate(key, items, containerId, renderRows);
  }));
  box.querySelector('.page-size-select').addEventListener('change', (e) => {
    p.size = parseInt(e.target.value, 10);
    p.page = 1;
    lecPaginate(key, items, containerId, renderRows);
  });
}

/* ------------------------- DUNG CHUNG: USER + HOC KY ------------------------- */
async function lecLoadProfileChip() {
  const res = await lecGet('/me');
  if (!res || !res.success) return null;
  const me = res.data;
  const chip = document.querySelector('.user-profile-chip');
  if (chip) {
    const strong = chip.querySelector('strong');
    const span = chip.querySelector('span');
    if (strong) strong.textContent = me.FullName;
    if (span) span.textContent = `ID: ${me.LecturerCode || me.UserCode}`;
  }
  return me;
}

async function lecLoadSemesters(selectId) {
  const select = lecEl(selectId);
  const res = await lecGet('/semesters');
  if (!res || !res.success) return null;
  const { semesters, current_semester_id: currentId } = res.data;
  if (select) {
    select.innerHTML = semesters
      .map((s) => `<option value="${s.Id}">${lecEscape(s.SemesterName)}</option>`).join('');
    const wanted = new URLSearchParams(location.search).get('semester_id');
    select.value = wanted || currentId || (semesters[0] && semesters[0].Id) || '';
    lecState.semesterId = parseInt(select.value, 10) || null;
  }
  return res.data;
}

function lecStatusBadge(status) {
  if (status === 'Cancelled') return '<span class="badge badge-warning">Cancelled</span>';
  if (status === 'Closed') return '<span class="badge badge-indigo">Closed</span>';
  return '<span class="badge badge-success">Open</span>';
}

/* ========================================================================
   TRANG 1: lecturer-classes.html  (Xem lop phu trach)
   ======================================================================== */
async function loadAssignedClasses() {
  const select = lecEl('semester-select');
  if (select) lecState.semesterId = parseInt(select.value, 10) || null;
  const res = await lecGet(`/classes?semester_id=${lecState.semesterId || ''}`);
  if (!res || !res.success) return;
  lecState.classes = res.data.classes;
  const s = res.data.summary;
  lecSetText('top-class-count', `${s.total_sections} Classes`);
  lecSetText('stat-sections', `${s.total_sections} Sections`);
  lecSetText('stat-credits', `${s.total_credits} Credits`);
  lecSetText('stat-students', `${s.total_students} Students`);
  lecSetText('stat-courses', `${s.distinct_courses} Distinct Courses`);
  lecState.paging.classes = { page: 1, size: 10 };
  filterAssignedClasses();
}

function filterAssignedClasses() {
  const q = ((lecEl('class-search') || {}).value || '').trim().toLowerCase();
  const day = (lecEl('day-filter') || {}).value || '';
  const enr = (lecEl('enrollment-filter') || {}).value || '';
  lecState.filtered = lecState.classes.filter((c) => {
    const hay = `${c.ClassCode} ${c.CourseCode} ${c.CourseName} ${c.Room}`.toLowerCase();
    if (q && !hay.includes(q)) return false;
    if (day && c.DayName !== day) return false;
    if (enr === 'active' && !(c.EnrolledCount > 0)) return false;
    if (enr === 'empty' && c.EnrolledCount !== 0) return false;
    return true;
  });
  if (lecState.paging.classes) lecState.paging.classes.page = 1;
  renderAssignedClasses();
}

function renderAssignedClasses() {
  const tbody = lecEl('assigned-classes-tbody');
  if (!tbody) return;
  const empty = lecEl('no-filter-match');
  if (empty) empty.classList.toggle('hidden', lecState.filtered.length > 0);
  lecPaginate('classes', lecState.filtered, 'classes-pagination', (rows) => {
    tbody.innerHTML = rows.map((c) => `
      <tr>
        <td><strong>${lecEscape(c.ClassCode)}</strong></td>
        <td>${lecEscape(c.CourseCode)}</td>
        <td>${lecEscape(c.CourseName)}</td>
        <td>${lecEscape(c.Credits)}</td>
        <td>${lecEscape(c.DayName)} &bull; ${lecEscape(c.TimeRange)}</td>
        <td>${lecEscape(c.Room)}</td>
        <td>${lecEscape(c.EnrolledCount)} / ${lecEscape(c.MaxCapacity)}</td>
        <td>${lecStatusBadge(c.ClassStatus)}</td>
        <td>
          <button type="button" class="btn btn-soft btn-sm" onclick="openClassDetail(${c.Id})">Details</button>
          <a class="btn btn-primary btn-sm" href="lecturer-students.html?class_id=${c.Id}&semester_id=${c.SemesterId}">Students</a>
        </td>
      </tr>`).join('');
  });
}

async function openClassDetail(classId) {
  const c = lecState.classes.find((x) => x.Id === classId);
  if (!c) return;
  const sem = lecEl('semester-select');
  lecSetText('modal-sec-title', `Class Section ${c.ClassCode}`);
  lecSetText('modal-sec-badge', c.ClassStatus);
  lecSetText('d-section', c.ClassCode);
  lecSetText('d-course', `${c.CourseCode} - ${c.CourseName}`);
  lecSetText('d-credits', c.Credits);
  lecSetText('d-day', c.DayName);
  lecSetText('d-time', `${c.SlotName} (${c.TimeRange})`);
  lecSetText('d-room', c.Room);
  lecSetText('d-dates', (sem && sem.options[sem.selectedIndex]) ? sem.options[sem.selectedIndex].text : '');
  lecSetText('d-enrolled', `${c.EnrolledCount} / ${c.MaxCapacity}`);
  lecSetText('d-prereq', c.PrerequisiteCode ? `${c.PrerequisiteCode} - ${c.PrerequisiteName}` : 'None');
  const link = lecEl('modal-roster-link');
  if (link) link.href = `lecturer-students.html?class_id=${c.Id}&semester_id=${c.SemesterId}`;
  const modal = lecEl('class-detail-modal');
  if (modal) modal.classList.remove('hidden');
}

function closeClassDetail() {
  const modal = lecEl('class-detail-modal');
  if (modal) modal.classList.add('hidden');
}

/* ========================================================================
   TRANG 2: lecturer-schedule.html  (Lich day theo tuan)
   ======================================================================== */
function onSemesterChange() {
  lecState.week = null;
  loadSchedulePage();
}
function prevWeek() { if (lecState.week && lecState.week > 1) { lecState.week -= 1; loadWeeklyGrid(); } }
function nextWeek() { if (lecState.week && lecState.week < lecState.totalWeeks) { lecState.week += 1; loadWeeklyGrid(); } }
function resetToCurrentWeek() { lecState.week = null; loadWeeklyGrid(); }

async function loadSchedulePage() {
  const select = lecEl('semester-select');
  if (select) lecState.semesterId = parseInt(select.value, 10) || null;

  // Bang tong hop cac lop duoc phan cong
  const res = await lecGet(`/classes?semester_id=${lecState.semesterId || ''}`);
  if (res && res.success) {
    lecState.classes = res.data.classes;
    const s = res.data.summary;
    lecSetText('assigned-count', s.total_sections);
    lecSetText('stat-classes', `${s.total_sections} Classes`);
    lecSetText('stat-credits', `${s.total_credits} Credits`);
    lecSetText('stat-students', `${s.total_students} Students`);
    lecSetText('stat-days', `${s.teaching_days} Days`);
    renderScheduleSummary();
  }
  await loadWeeklyGrid();
}

function renderScheduleSummary() {
  const tbody = lecEl('summary-tbody');
  if (!tbody) return;
  const empty = lecEl('summary-empty');
  if (empty) empty.classList.toggle('hidden', lecState.classes.length > 0);
  const sem = lecEl('semester-select');
  const semText = (sem && sem.options[sem.selectedIndex]) ? sem.options[sem.selectedIndex].text : '';
  lecPaginate('summary', lecState.classes, 'summary-pagination', (rows) => {
    tbody.innerHTML = rows.map((c) => `
      <tr>
        <td><strong>${lecEscape(c.ClassCode)}</strong></td>
        <td>${lecEscape(c.CourseCode)}</td>
        <td>${lecEscape(c.CourseName)}</td>
        <td>${lecEscape(c.Credits)}</td>
        <td>${lecEscape(semText)}</td>
        <td>${lecEscape(c.DayName)} &bull; ${lecEscape(c.TimeRange)}</td>
        <td>${lecEscape(c.Room)}</td>
        <td>${lecEscape(c.EnrolledCount)} / ${lecEscape(c.MaxCapacity)}</td>
        <td><a class="btn btn-primary btn-sm" href="lecturer-students.html?class_id=${c.Id}&semester_id=${c.SemesterId}">View Roster</a></td>
      </tr>`).join('');
  });
}

async function loadWeeklyGrid() {
  const board = lecEl('lecturer-timetable-board');
  const loading = lecEl('timetable-loading');
  const emptyNote = lecEl('timetable-empty');
  if (loading) loading.classList.remove('hidden');
  if (emptyNote) emptyNote.classList.add('hidden');

  const weekParam = lecState.week ? `&week=${lecState.week}` : '';
  const res = await lecGet(`/schedule?semester_id=${lecState.semesterId || ''}${weekParam}`);
  if (loading) loading.classList.add('hidden');
  if (!res || !res.success) {
    if (board) board.innerHTML = '';
    if (emptyNote) { emptyNote.textContent = (res && res.message) || 'Không tải được lịch giảng dạy.'; emptyNote.classList.remove('hidden'); }
    return;
  }

  const data = res.data;
  lecState.week = data.week.week;
  lecState.totalWeeks = data.week.total_weeks;
  lecSetText('current-week-display', `Week ${data.week.week} / ${data.week.total_weeks}`);
  lecSetText('week-date-range',
    `Viewing weekly teaching schedule: ${lecFormatDate(data.week.week_start)} - ${lecFormatDate(data.week.week_end)}`);

  // Chi hien thi Chu nhat neu thuc su co buoi day vao Chu nhat
  const hasSunday = data.sessions.some((s) => s.DayOfWeek === 8);
  const days = data.days.filter((d) => d.day <= 7 || hasSunday);
  board.style.gridTemplateColumns = `115px repeat(${days.length}, 1fr)`;

  let html = '<div class="tt-col-header">Time Slot</div>';
  html += days.map((d) =>
    `<div class="tt-col-header">${lecEscape(d.name)}<br><small>${lecFormatDate(d.date)}</small></div>`).join('');

  data.slots.forEach((slot, idx) => {
    html += `<div class="tt-time-slot"><strong>Slot ${lecEscape(slot.SlotNumber)}</strong><span>${lecEscape(slot.StartTime)} - ${lecEscape(slot.EndTime)}</span></div>`;
    days.forEach((d) => {
      const found = data.sessions.filter((s) => s.DayOfWeek === d.day && s.TimeSlotId === slot.Id);
      const cards = found.map((s) => `
        <div class="tt-card ${idx % 2 ? 'indigo' : ''}">
          <strong>${lecEscape(s.CourseCode)} &bull; ${lecEscape(s.ClassCode)}</strong>
          <span>${lecEscape(s.CourseName)}</span>
          <span>Room: ${lecEscape(s.Room)}</span>
          <span>${lecEscape(s.EnrolledCount)} / ${lecEscape(s.MaxCapacity)} students</span>
        </div>`).join('');
      html += `<div class="tt-cell">${cards}</div>`;
    });
  });
  board.innerHTML = html;
  if (emptyNote) {
    emptyNote.textContent = 'No teaching sessions scheduled for this week.';
    emptyNote.classList.toggle('hidden', data.sessions.length > 0);
  }
}

/* ========================================================================
   TRANG 3: lecturer-students.html  (Danh sach SV + xuat CSV)
   ======================================================================== */
async function loadStudentRoster() {
  const semSelect = lecEl('sem-select');
  const secSelect = lecEl('section-select');

  if (semSelect) lecState.semesterId = parseInt(semSelect.value, 10) || null;
  // onchange cua ca 2 dropdown cung goi ham nay -> nhan biet doi hoc ky bang cach so sanh
  const semesterChanged = lecState.loadedSemesterId !== undefined
    && lecState.loadedSemesterId !== lecState.semesterId;

  // Doi hoc ky (hoac lan dau) -> nap lai danh sach lop cua hoc ky do
  if (semesterChanged || !lecState.classesLoaded) {
    const res = await lecGet(`/classes?semester_id=${lecState.semesterId || ''}`);
    if (!res || !res.success) return;
    lecState.classes = res.data.classes;
    lecState.classesLoaded = true;
    lecState.loadedSemesterId = lecState.semesterId;
    const wanted = new URLSearchParams(location.search).get('class_id');
    secSelect.innerHTML = lecState.classes.length
      ? lecState.classes.map((c) =>
          `<option value="${c.Id}">${lecEscape(c.ClassCode)} - ${lecEscape(c.CourseName)}</option>`).join('')
      : '<option value="">-- No assigned classes --</option>';
    if (wanted && !semesterChanged && lecState.classes.some((c) => String(c.Id) === wanted)) {
      secSelect.value = wanted;
    }
  }

  const classId = parseInt(secSelect.value, 10);
  if (!classId) {
    lecState.students = [];
    lecState.studentsFiltered = [];
    lecSetText('top-section-code', '--');
    renderStudents();
    return;
  }

  const res = await lecGet(`/classes/${classId}/students`);
  if (!res || !res.success) {
    if (res) lecBanner('export-toast', res.message, 'danger');
    return;
  }
  lecState.students = res.data.students;
  lecSetText('top-section-code', res.data.class.ClassCode);
  lecSetText('roster-heading', `Enrolled Student List - ${res.data.class.ClassCode}`);
  lecSetText('roster-meta', `${res.data.total} student(s) - ${res.data.class.CourseName}`);
  const search = lecEl('student-search');
  if (search) search.value = '';
  filterStudents();
}

function filterStudents() {
  const q = ((lecEl('student-search') || {}).value || '').trim().toLowerCase();
  lecState.studentsFiltered = lecState.students.filter((s) =>
    !q || `${s.StudentCode} ${s.FullName} ${s.Email}`.toLowerCase().includes(q));
  if (lecState.paging.students) lecState.paging.students.page = 1;
  renderStudents();
}

function renderStudents() {
  const tbody = lecEl('student-tbody');
  if (!tbody) return;
  const noStudents = lecState.students.length === 0;
  const emptyMsg = lecEl('empty-roster-msg');
  if (emptyMsg) emptyMsg.classList.toggle('hidden', !noStudents);
  lecPaginate('students', lecState.studentsFiltered, 'student-pagination', (rows, offset) => {
    tbody.innerHTML = rows.map((s, i) => `
      <tr>
        <td>${offset + i + 1}</td>
        <td><strong>${lecEscape(s.StudentCode)}</strong></td>
        <td>${lecEscape(s.FullName)}</td>
        <td>${lecEscape(s.Major)}</td>
        <td>${lecEscape(s.Email)}</td>
        <td>${lecEscape(s.Phone || '')}</td>
        <td>${lecEscape(lecFormatDateTime(s.EnrolledAt))}</td>
        <td><span class="badge badge-success">${lecEscape(s.EnrollmentStatus)}</span></td>
      </tr>`).join('');
  });
}

/* Xuat CSV: goi endpoint server, tai file ve qua Blob (de hien loi dang thong bao) */
async function exportStudentCSV() {
  const classId = parseInt((lecEl('section-select') || {}).value, 10);
  if (!classId) {
    lecBanner('export-toast', 'Vui lòng chọn lớp học phần trước khi xuất.', 'danger');
    return;
  }
  try {
    const res = await fetch(`${LEC_API}/classes/${classId}/export`);
    if (!res.ok) {
      let msg = 'Xuất file thất bại.';
      try { msg = (await res.json()).message || msg; } catch (e) { /* khong phai JSON */ }
      lecBanner('export-toast', msg, 'danger');
      return;
    }
    const disposition = res.headers.get('Content-Disposition') || '';
    const match = /filename="?([^";]+)"?/.exec(disposition);
    const filename = match ? match[1] : `students_${classId}.csv`;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    lecBanner('export-toast', `Đã xuất file ${filename}`, 'success');
  } catch (err) {
    console.error(err);
    lecBanner('export-toast', 'Lỗi kết nối đến máy chủ!', 'danger');
  }
}

/* ========================================================================
   TRANG 4: lecturer-profile.html  (Ho so + doi mat khau)
   ======================================================================== */
function lecFillProfile(me) {
  const map = {
    'Lecturer ID': me.LecturerCode,
    'Full Name': me.FullName,
    'System Role': me.Role,
    'Academic Degree / Rank': me.AcademicDegree,
    'Department / Faculty': me.Department,
    'Institutional Email': me.Email,
  };
  document.querySelectorAll('.two-col-grid .info-item').forEach((item) => {
    const label = item.querySelector('span');
    const value = item.querySelector('strong');
    if (label && value && Object.prototype.hasOwnProperty.call(map, label.textContent.trim())) {
      value.textContent = map[label.textContent.trim()] || '';
    }
  });
}

async function handleLecturerPassword(event) {
  event.preventDefault();
  const current = lecEl('cur-pw').value;
  const next = lecEl('new-pw').value;
  const confirm = lecEl('cfm-pw').value;
  if (next !== confirm) {
    lecBanner('pw-toast', 'Mật khẩu xác nhận không khớp.', 'danger');
    return;
  }
  try {
    const res = await fetch(`${LEC_API}/change-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: current, new_password: next, confirm_password: confirm }),
    });
    const data = await res.json();
    if (data.success) {
      lecBanner('pw-toast', data.message || 'Đổi mật khẩu thành công.', 'success');
      event.target.reset();
    } else {
      lecBanner('pw-toast', data.message || 'Đổi mật khẩu thất bại.', 'danger');
    }
  } catch (err) {
    console.error(err);
    lecBanner('pw-toast', 'Lỗi kết nối đến máy chủ!', 'danger');
  }
}

/* ------------------------------ KHOI TAO TRANG ------------------------------ */
document.addEventListener('DOMContentLoaded', async () => {
  const me = await lecLoadProfileChip();

  if (lecEl('assigned-classes-tbody')) {              // trang Classes
    await lecLoadSemesters('semester-select');
    await loadAssignedClasses();
  } else if (lecEl('lecturer-timetable-board')) {     // trang Schedule
    await lecLoadSemesters('semester-select');
    await loadSchedulePage();
  } else if (lecEl('student-tbody')) {                // trang Students
    await lecLoadSemesters('sem-select');
    await loadStudentRoster();
  } else if (lecEl('cur-pw') && me) {                 // trang Profile
    lecFillProfile(me);
  }
});
