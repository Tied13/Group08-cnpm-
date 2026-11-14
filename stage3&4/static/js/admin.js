/* ==========================================================================
   static/js/admin.js
   Script giao dien PHAN HE ADMIN (System Management Console)

   - Ket noi cac form / bang co san trong templates/adminView/*.html voi API
     /admin/api/... (controllers/admin_controller.py).
   - Khong sua HTML: script tu nhan dien trang dua tren id cua phan tu.
   ========================================================================== */

const ADMIN_API = '/admin/api';
const MIN_CLASS_ENROLLMENT = 15;
const DEFAULT_PAGE_SIZE = 10;

const DAY_LABELS = {
  2: 'Monday', 3: 'Tuesday', 4: 'Wednesday', 5: 'Thursday',
  6: 'Friday', 7: 'Saturday', 8: 'Sunday',
};
const DAY_VALUES = {
  monday: 2, tuesday: 3, wednesday: 4, thursday: 5,
  friday: 6, saturday: 7, sunday: 8,
};

/* Trang thai du lieu cua tung trang */
const adminState = {
  users: [],
  courses: [],
  classes: [],
  lecturers: [],
  timeslots: [],
  semesters: [],
  periods: [],
  report: null,
  pendingCancelClass: null,
  editingCourseId: null,
  pages: {},
};

/* ==========================================================================
   1. TIEN ICH CHUNG
   ========================================================================== */
function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function $id(id) {
  return document.getElementById(id);
}

function valueOf(id) {
  const el = $id(id);
  return el ? el.value.trim() : '';
}

/** Goi API admin, tra ve data; nem Error(message) khi that bai. */
async function adminApi(path, options = {}) {
  const { method = 'GET', body } = options;
  const init = { method, headers: { Accept: 'application/json' }, credentials: 'same-origin' };
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(`${ADMIN_API}${path}`, init);
  } catch (err) {
    throw new Error('Không thể kết nối đến máy chủ. Vui lòng thử lại.');
  }

  let json = null;
  try {
    json = await response.json();
  } catch (err) {
    json = null;
  }

  if (response.status === 401) {
    window.location.href = '/login';
    throw new Error((json && json.message) || 'Phiên đăng nhập đã hết hạn.');
  }
  if (!response.ok || !json || json.success === false) {
    throw new Error((json && json.message) || `Yêu cầu thất bại (HTTP ${response.status}).`);
  }
  return { data: json.data, message: json.message };
}

/** Hien thong bao tren thanh .toast-banner co san cua tung trang. */
function showAdminToast(toastId, message, type = 'success') {
  let box = toastId ? $id(toastId) : null;
  if (!box) {
    box = $id('admin-floating-toast');
    if (!box) {
      box = document.createElement('div');
      box.id = 'admin-floating-toast';
      box.className = 'toast-banner hidden';
      box.style.position = 'fixed';
      box.style.top = '16px';
      box.style.right = '16px';
      box.style.zIndex = '9999';
      box.style.maxWidth = '420px';
      document.body.appendChild(box);
    }
  }
  box.textContent = message;
  box.classList.remove('hidden', 'toast-success', 'toast-danger', 'toast-warning');
  box.classList.add(`toast-${type}`);
  box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  clearTimeout(box._hideTimer);
  box._hideTimer = setTimeout(() => box.classList.add('hidden'), 5000);
}

function formatDateTime(iso) {
  if (!iso) return '--';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function toDateTimeLocal(iso) {
  if (!iso) return '';
  return String(iso).slice(0, 16);
}

function badge(text, variant) {
  return `<span class="badge badge-${variant}">${escapeHtml(text)}</span>`;
}

function statusBadge(status) {
  const map = {
    Active: 'success',
    Locked: 'danger',
    Open: 'success',
    Closed: 'warning',
    Cancelled: 'danger',
    Upcoming: 'indigo',
    Ended: 'warning',
    Inactive: 'danger',
    Compliant: 'success',
    'Below Minimum': 'warning',
    'Over Limit': 'danger',
    'No Registration': 'indigo',
  };
  return badge(status, map[status] || 'indigo');
}

function setEmptyState(emptyId, isEmpty) {
  const el = $id(emptyId);
  if (el) el.classList.toggle('hidden', !isEmpty);
}

/* ---------------- Phan trang dung chung ---------------- */
function getPageState(key) {
  if (!adminState.pages[key]) adminState.pages[key] = { page: 1, size: DEFAULT_PAGE_SIZE };
  return adminState.pages[key];
}

function paginate(list, key) {
  const state = getPageState(key);
  const totalPages = Math.max(1, Math.ceil(list.length / state.size));
  if (state.page > totalPages) state.page = totalPages;
  const start = (state.page - 1) * state.size;
  return list.slice(start, start + state.size);
}

function renderPagination(containerId, key, totalItems, rerender) {
  const container = $id(containerId);
  if (!container) return;
  const state = getPageState(key);
  if (totalItems === 0) {
    container.innerHTML = '';
    return;
  }
  const totalPages = Math.max(1, Math.ceil(totalItems / state.size));
  const from = (state.page - 1) * state.size + 1;
  const to = Math.min(state.page * state.size, totalItems);

  const pages = [];
  for (let p = 1; p <= totalPages; p += 1) {
    if (p === 1 || p === totalPages || Math.abs(p - state.page) <= 1) {
      pages.push(p);
    } else if (pages[pages.length - 1] !== '...') {
      pages.push('...');
    }
  }

  container.innerHTML = `
    <div class="pagination-bar">
      <div class="pagination-info">Showing <strong>${from}–${to}</strong> of <strong>${totalItems}</strong></div>
      <div class="pagination-controls">
        <select class="page-size-select" data-role="size">
          ${[5, 10, 20, 50].map((n) => `<option value="${n}" ${n === state.size ? 'selected' : ''}>${n} / page</option>`).join('')}
        </select>
        <button class="page-btn" data-page="${state.page - 1}" ${state.page <= 1 ? 'disabled' : ''}>&lsaquo;</button>
        ${pages.map((p) => (p === '...'
          ? '<span class="page-dots">…</span>'
          : `<button class="page-btn ${p === state.page ? 'active' : ''}" data-page="${p}">${p}</button>`)).join('')}
        <button class="page-btn" data-page="${state.page + 1}" ${state.page >= totalPages ? 'disabled' : ''}>&rsaquo;</button>
      </div>
    </div>`;

  container.querySelectorAll('button[data-page]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.page = Number(btn.dataset.page);
      rerender();
    });
  });
  const sizeSelect = container.querySelector('select[data-role="size"]');
  sizeSelect.addEventListener('change', () => {
    state.size = Number(sizeSelect.value);
    state.page = 1;
    rerender();
  });
}

/** Nap danh sach hoc ky vao <select>, mac dinh chon hoc ky hien hanh. */
async function loadSemesterOptions(selectId) {
  const select = $id(selectId);
  if (!select) return null;
  if (!adminState.semesters.length) {
    const { data } = await adminApi('/semesters');
    adminState.semesters = data || [];
  }
  const previous = select.value;
  select.innerHTML = adminState.semesters
    .map((s) => `<option value="${s.Id}">${escapeHtml(s.SemesterName)}${s.IsCurrent ? ' • Current' : ''}</option>`)
    .join('');
  const keep = adminState.semesters.find((s) => String(s.Id) === previous);
  const current = adminState.semesters.find((s) => s.IsCurrent) || adminState.semesters[0];
  if (keep) select.value = String(keep.Id);
  else if (current) select.value = String(current.Id);
  return select.value || null;
}

/** Hien thi ten admin dang dang nhap tren chip goc phai. */
async function loadAdminIdentity() {
  const chip = document.querySelector('.user-profile-chip');
  if (!chip) return;
  try {
    const { data } = await adminApi('/me');
    if (data && data.Username) {
      const span = chip.querySelector('span');
      if (span) span.textContent = `Username: ${data.Username}`;
    }
  } catch (err) {
    /* bo qua - khong anh huong chuc nang chinh */
  }
}

/* ==========================================================================
   2. TRANG QUAN LY TAI KHOAN (admin-users.html)
   ========================================================================== */
async function loadUserAccounts() {
  try {
    const { data } = await adminApi('/users');
    adminState.users = data || [];
    const total = $id('top-total-accounts');
    if (total) total.textContent = `${adminState.users.length} Users`;
    renderUsersTable();
  } catch (err) {
    showAdminToast('user-toast', err.message, 'danger');
  }
}

function getFilteredUsers() {
  const keyword = valueOf('user-search').toLowerCase();
  const role = valueOf('role-filter');
  const status = valueOf('status-filter');
  return adminState.users.filter((u) => {
    if (role && u.Role !== role) return false;
    if (status && u.Status !== status) return false;
    if (!keyword) return true;
    return [u.UserCode, u.FullName, u.Email, u.Username]
      .some((field) => String(field || '').toLowerCase().includes(keyword));
  });
}

function filterUsers() {
  getPageState('users').page = 1;
  renderUsersTable();
}

function renderUsersTable() {
  const tbody = $id('users-tbody');
  if (!tbody) return;
  const list = getFilteredUsers();
  const pageItems = paginate(list, 'users');

  tbody.innerHTML = pageItems.map((u) => {
    const isLocked = u.Status === 'Locked';
    const failed = u.FailedLoginCount ? ` <small style="color: var(--text-muted)">(${u.FailedLoginCount} failed)</small>` : '';
    return `
      <tr>
        <td><strong>${escapeHtml(u.UserCode)}</strong></td>
        <td>${escapeHtml(u.FullName)}</td>
        <td>${badge(u.Role, u.Role === 'Student' ? 'teal' : 'indigo')}</td>
        <td>${escapeHtml(u.Department || '--')}</td>
        <td>${escapeHtml(u.Email)}</td>
        <td><code style="font-size: 0.75rem">${escapeHtml(u.PasswordHashPreview || '')}</code></td>
        <td>${statusBadge(u.Status)}${failed}</td>
        <td>
          <div class="action-group">
            <button class="btn btn-soft btn-sm" onclick="openEditUser(${u.Id})">Edit</button>
            <button class="btn ${isLocked ? 'btn-teal' : 'btn-danger-soft'} btn-sm"
                    onclick="toggleUserStatus(${u.Id})">${isLocked ? 'Unlock' : 'Lock'}</button>
          </div>
        </td>
      </tr>`;
  }).join('');

  setEmptyState('users-empty', list.length === 0);
  renderPagination('users-pagination', 'users', list.length, renderUsersTable);
}

async function handleCreateUser(event) {
  event.preventDefault();
  const form = event.target;
  const payload = {
    role: valueOf('new-role'),
    user_code: valueOf('new-id'),
    full_name: valueOf('new-name'),
    email: valueOf('new-email'),
    department: valueOf('new-dept'),
    password: $id('new-pw') ? $id('new-pw').value : '',
  };
  try {
    const { message } = await adminApi('/users', { method: 'POST', body: payload });
    showAdminToast('user-toast', message, 'success');
    form.reset();
    await loadUserAccounts();
  } catch (err) {
    showAdminToast('user-toast', err.message, 'danger');
  }
}

async function toggleUserStatus(userId) {
  const user = adminState.users.find((u) => u.Id === userId);
  if (!user) return;
  const action = user.Status === 'Locked' ? 'MỞ KHÓA' : 'KHÓA';
  if (!window.confirm(`Bạn có chắc muốn ${action} tài khoản ${user.UserCode} - ${user.FullName}?`)) return;
  try {
    const { message } = await adminApi(`/users/${userId}/toggle-status`, { method: 'POST' });
    showAdminToast('user-toast', message, 'success');
    await loadUserAccounts();
  } catch (err) {
    showAdminToast('user-toast', err.message, 'danger');
  }
}

function openEditUser(userId) {
  const user = adminState.users.find((u) => u.Id === userId);
  const modal = $id('edit-user-modal');
  if (!user || !modal) return;
  modal.dataset.userId = String(user.Id);
  $id('edit-id').value = user.UserCode;
  $id('edit-role').value = user.Role;
  $id('edit-role').disabled = true; // khong cho doi vai tro sau khi tao
  $id('edit-name').value = user.FullName || '';
  $id('edit-dept').value = user.Department || '';
  $id('edit-email').value = user.Email || '';
  modal.classList.remove('hidden');
}

function closeEditUser() {
  const modal = $id('edit-user-modal');
  if (modal) modal.classList.add('hidden');
}

async function saveEditedUser(event) {
  event.preventDefault();
  const modal = $id('edit-user-modal');
  const userId = modal ? modal.dataset.userId : null;
  if (!userId) return;
  const payload = {
    full_name: valueOf('edit-name'),
    email: valueOf('edit-email'),
    department: valueOf('edit-dept'),
  };
  try {
    const { message } = await adminApi(`/users/${userId}`, { method: 'PUT', body: payload });
    closeEditUser();
    showAdminToast('user-toast', message, 'success');
    await loadUserAccounts();
  } catch (err) {
    showAdminToast('user-toast', err.message, 'danger');
  }
}

/* ==========================================================================
   3. TRANG QUAN LY MON HOC (admin-courses.html)
   ========================================================================== */
function courseLabel(course) {
  return `${course.CourseCode} — ${course.CourseName}`;
}

function buildPrereqOptions(excludeId, selectedId) {
  const options = ['<option value="">None (No Prerequisite)</option>'];
  adminState.courses
    .filter((c) => c.Id !== excludeId)
    .forEach((c) => {
      options.push(`<option value="${c.Id}" ${c.Id === selectedId ? 'selected' : ''}>${escapeHtml(courseLabel(c))}</option>`);
    });
  return options.join('');
}

async function loadAdminCourses() {
  try {
    const { data } = await adminApi('/courses');
    adminState.courses = data || [];
    const top = $id('top-base-courses');
    if (top) top.textContent = `${adminState.courses.length} Courses`;
    const prereq = $id('c-prereq');
    if (prereq) prereq.innerHTML = buildPrereqOptions(null, null);
    renderCoursesTable();
  } catch (err) {
    showAdminToast('course-toast', err.message, 'danger');
  }
}

function renderCoursesTable() {
  const tbody = $id('courses-tbody');
  if (!tbody) return;
  const list = adminState.courses;
  const pageItems = paginate(list, 'courses');

  tbody.innerHTML = pageItems.map((c) => `
    <tr>
      <td><strong>${escapeHtml(c.CourseCode)}</strong></td>
      <td>${escapeHtml(c.CourseName)}</td>
      <td>${escapeHtml(c.Credits)}</td>
      <td>${c.PrerequisiteCode ? escapeHtml(`${c.PrerequisiteCode} — ${c.PrerequisiteName}`) : '<span style="color: var(--text-muted)">None</span>'}</td>
      <td>${escapeHtml(c.ActiveSections)}</td>
      <td>${escapeHtml(c.RegisteredStudents)}</td>
      <td>
        <div class="action-group">
          <button class="btn btn-soft btn-sm" onclick="openEditCourse(${c.Id})">Edit</button>
          <button class="btn btn-danger-soft btn-sm" onclick="deleteCourse(${c.Id})">Delete</button>
        </div>
      </td>
    </tr>`).join('');

  setEmptyState('courses-empty', list.length === 0);
  renderPagination('courses-pagination', 'courses', list.length, renderCoursesTable);
}

async function handleCreateCourse(event) {
  event.preventDefault();
  const form = event.target;
  const payload = {
    course_code: valueOf('c-code'),
    course_name: valueOf('c-name'),
    credits: valueOf('c-credits'),
    prerequisite_course_id: valueOf('c-prereq') || null,
  };
  try {
    const { message } = await adminApi('/courses', { method: 'POST', body: payload });
    showAdminToast('course-toast', message, 'success');
    form.reset();
    await loadAdminCourses();
  } catch (err) {
    showAdminToast('course-toast', err.message, 'danger');
  }
}

/** Template khong co modal sua mon hoc -> tao dong bang JS (dung lai class CSS co san). */
function ensureCourseEditModal() {
  let modal = $id('edit-course-modal');
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = 'edit-course-modal';
  modal.className = 'modal-overlay hidden';
  modal.innerHTML = `
    <div class="modal-box">
      <h3>Edit Base Course</h3>
      <form onsubmit="saveEditedCourse(event)">
        <div class="form-group">
          <label for="edit-c-code">Course Code</label>
          <input type="text" id="edit-c-code" required />
        </div>
        <div class="form-group">
          <label for="edit-c-name">Course Name</label>
          <input type="text" id="edit-c-name" required />
        </div>
        <div class="form-group">
          <label for="edit-c-credits">Number of Credits</label>
          <input type="number" id="edit-c-credits" min="1" max="10" required />
        </div>
        <div class="form-group">
          <label for="edit-c-prereq">Prerequisite Course</label>
          <select id="edit-c-prereq"></select>
        </div>
        <div class="modal-actions">
          <button type="button" class="btn btn-soft" onclick="closeEditCourse()">Cancel</button>
          <button type="submit" class="btn btn-primary">Save Changes</button>
        </div>
      </form>
    </div>`;
  document.body.appendChild(modal);
  return modal;
}

function openEditCourse(courseId) {
  const course = adminState.courses.find((c) => c.Id === courseId);
  if (!course) return;
  const modal = ensureCourseEditModal();
  adminState.editingCourseId = courseId;
  $id('edit-c-code').value = course.CourseCode;
  $id('edit-c-name').value = course.CourseName;
  $id('edit-c-credits').value = course.Credits;
  $id('edit-c-prereq').innerHTML = buildPrereqOptions(course.Id, course.PrerequisiteCourseId);
  modal.classList.remove('hidden');
}

function closeEditCourse() {
  const modal = $id('edit-course-modal');
  if (modal) modal.classList.add('hidden');
  adminState.editingCourseId = null;
}

async function saveEditedCourse(event) {
  event.preventDefault();
  const courseId = adminState.editingCourseId;
  if (!courseId) return;
  const payload = {
    course_code: valueOf('edit-c-code'),
    course_name: valueOf('edit-c-name'),
    credits: valueOf('edit-c-credits'),
    prerequisite_course_id: valueOf('edit-c-prereq') || null,
  };
  try {
    const { message } = await adminApi(`/courses/${courseId}`, { method: 'PUT', body: payload });
    closeEditCourse();
    showAdminToast('course-toast', message, 'success');
    await loadAdminCourses();
  } catch (err) {
    showAdminToast('course-toast', err.message, 'danger');
  }
}

async function deleteCourse(courseId) {
  const course = adminState.courses.find((c) => c.Id === courseId);
  if (!course) return;
  if (!window.confirm(`Xóa môn học ${courseLabel(course)}?`)) return;
  try {
    const { message } = await adminApi(`/courses/${courseId}`, { method: 'DELETE' });
    showAdminToast('course-toast', message, 'success');
    await loadAdminCourses();
  } catch (err) {
    showAdminToast('course-toast', err.message, 'danger');
  }
}

async function handleManualOverride(event) {
  event.preventDefault();
  const form = event.target;
  const payload = {
    student_code: valueOf('override-student'),
    class_code: valueOf('override-section'),
    action: valueOf('override-action'),
  };
  const verb = payload.action === 'ADD' ? 'THÊM' : 'XÓA';
  if (!window.confirm(`${verb} sinh viên ${payload.student_code} ${payload.action === 'ADD' ? 'vào' : 'khỏi'} lớp ${payload.class_code}?`)) return;
  try {
    const { message } = await adminApi('/enrollments/override', { method: 'POST', body: payload });
    showAdminToast('course-toast', message, 'success');
    form.reset();
    await loadAdminCourses();
  } catch (err) {
    showAdminToast('course-toast', err.message, 'danger');
  }
}

/* ==========================================================================
   4. TRANG MO / HUY LOP HOC PHAN (admin-classes.html)
   ========================================================================== */
function ensureDatalist(inputId, listId, options) {
  const input = $id(inputId);
  if (!input) return;
  let list = $id(listId);
  if (!list) {
    list = document.createElement('datalist');
    list.id = listId;
    document.body.appendChild(list);
  }
  list.innerHTML = options.map((o) => `<option value="${escapeHtml(o)}"></option>`).join('');
  input.setAttribute('list', listId);
  input.setAttribute('autocomplete', 'off');
}

async function initClassesPage() {
  try {
    await loadSemesterOptions('classes-sem');
    const [courses, timeslots, lecturers, classrooms] = await Promise.all([
      adminApi('/courses'),
      adminApi('/timeslots'),
      adminApi('/lecturers'),
      adminApi('/classrooms'),
    ]);
    adminState.courses = courses.data || [];
    adminState.timeslots = timeslots.data || [];
    adminState.lecturers = (lecturers.data || []).filter((l) => l.Status === 'Active');

    const courseSelect = $id('sec-course');
    if (courseSelect) {
      courseSelect.innerHTML = adminState.courses
        .map((c) => `<option value="${c.Id}">${escapeHtml(`${c.CourseCode} — ${c.CourseName} (${c.Credits} Cr)`)}</option>`)
        .join('');
    }
    const slotSelect = $id('sec-slot');
    if (slotSelect) {
      slotSelect.innerHTML = adminState.timeslots
        .map((t) => `<option value="${t.Id}">${escapeHtml(t.SlotName)}</option>`)
        .join('');
    }
    ensureDatalist('sec-lecturer', 'admin-lecturer-options',
      adminState.lecturers.map((l) => `${l.UserCode} - ${l.FullName}`));
    ensureDatalist('sec-room', 'admin-room-options',
      (classrooms.data || []).map((r) => r.RoomCode));
  } catch (err) {
    showAdminToast('class-toast', err.message, 'danger');
  }
  await loadAdminClasses();
}

async function loadAdminClasses() {
  const semesterId = valueOf('classes-sem');
  try {
    const query = semesterId ? `?semester_id=${encodeURIComponent(semesterId)}` : '';
    const { data } = await adminApi(`/classes${query}`);
    adminState.classes = data || [];
    renderClassesTable();
  } catch (err) {
    showAdminToast('class-toast', err.message, 'danger');
  }
}

function renderClassesTable() {
  const tbody = $id('admin-classes-tbody');
  if (!tbody) return;
  const list = adminState.classes;
  const pageItems = paginate(list, 'classes');

  tbody.innerHTML = pageItems.map((c) => {
    const current = c.CurrentEnrollment || 0;
    const max = c.MaxCapacity || 0;
    const percent = max ? Math.min(100, Math.round((current * 100) / max)) : 0;
    const fillClass = current < MIN_CLASS_ENROLLMENT ? 'low' : (percent >= 80 ? 'high' : '');
    const lecturer = c.LecturerCode ? `${c.LecturerCode} - ${c.LecturerName}` : 'Unassigned';
    const action = c.CanCancel
      ? `<button class="btn btn-danger btn-sm" onclick="openCancelSectionModal(${c.Id})">Cancel Class</button>`
      : `<button class="btn btn-disabled btn-sm" disabled title="${c.Status === 'Cancelled' ? 'Already cancelled' : 'Meets minimum enrollment'}">Cancel Class</button>`;
    return `
      <tr>
        <td><strong>${escapeHtml(c.ClassCode)}</strong></td>
        <td>${escapeHtml(`${c.CourseCode} — ${c.CourseName}`)}</td>
        <td>${escapeHtml(lecturer)}</td>
        <td>${escapeHtml(c.DayName || DAY_LABELS[c.DayOfWeek] || '')} • ${escapeHtml(c.SlotName)}<br>
            <small style="color: var(--text-muted)">Room ${escapeHtml(c.Room)}</small></td>
        <td>${current} / ${max}
            <div class="capacity-bar-wrap"><div class="capacity-bar-fill ${fillClass}" style="width: ${percent}%"></div></div></td>
        <td>${escapeHtml(c.MinCapacity || MIN_CLASS_ENROLLMENT)} students</td>
        <td>${statusBadge(c.Status)}</td>
        <td>${action}</td>
      </tr>`;
  }).join('');

  setEmptyState('classes-empty', list.length === 0);
  renderPagination('classes-pagination', 'classes', list.length, renderClassesTable);
}

function resolveLecturerInput(text) {
  const normalized = text.trim().toLowerCase();
  if (!normalized) return null;
  return adminState.lecturers.find((l) => {
    const full = `${l.UserCode} - ${l.FullName}`.toLowerCase();
    return full === normalized
      || String(l.UserCode).toLowerCase() === normalized.split(' - ')[0]
      || String(l.FullName).toLowerCase() === normalized;
  }) || null;
}

async function handleCreateSection(event) {
  event.preventDefault();
  const form = event.target;
  const lecturerText = valueOf('sec-lecturer');
  const lecturer = resolveLecturerInput(lecturerText);
  const dayRaw = valueOf('sec-day');
  const payload = {
    semester_id: valueOf('classes-sem') || null,
    course_id: valueOf('sec-course'),
    class_code: valueOf('sec-code'),
    max_capacity: valueOf('sec-cap'),
    room: valueOf('sec-room'),
    day_of_week: DAY_VALUES[dayRaw.toLowerCase()] || dayRaw,
    time_slot_id: valueOf('sec-slot'),
    lecturer_id: lecturer ? lecturer.Id : null,
    lecturer: lecturerText,
  };
  try {
    const { message } = await adminApi('/classes', { method: 'POST', body: payload });
    showAdminToast('class-toast', message, 'success');
    form.reset();
    const courseSelect = $id('sec-course');
    if (courseSelect && courseSelect.options.length) courseSelect.selectedIndex = 0;
    await loadAdminClasses();
  } catch (err) {
    showAdminToast('class-toast', err.message, 'danger');
  }
}

function openCancelSectionModal(classId) {
  const target = adminState.classes.find((c) => c.Id === classId);
  const modal = $id('cancel-sec-modal');
  if (!target || !modal) return;
  adminState.pendingCancelClass = target;
  const label = $id('cancel-sec-target');
  if (label) {
    label.textContent = `${target.ClassCode} — ${target.CourseName} (${target.CurrentEnrollment}/${target.MaxCapacity} students registered)`;
  }
  modal.classList.remove('hidden');
}

function closeCancelSectionModal() {
  const modal = $id('cancel-sec-modal');
  if (modal) modal.classList.add('hidden');
  adminState.pendingCancelClass = null;
}

async function confirmCancelSection() {
  const target = adminState.pendingCancelClass;
  if (!target) return;
  try {
    const { message } = await adminApi(`/classes/${target.Id}/cancel`, { method: 'POST' });
    closeCancelSectionModal();
    showAdminToast('class-toast', message, 'success');
    await loadAdminClasses();
  } catch (err) {
    closeCancelSectionModal();
    showAdminToast('class-toast', err.message, 'danger');
  }
}

/* ==========================================================================
   5. TRANG CAU HINH DOT DANG KY (admin-period.html)
   ========================================================================== */
async function initPeriodPage() {
  try {
    await loadSemesterOptions('sem-select');
  } catch (err) {
    showAdminToast('period-toast', err.message, 'danger');
  }
  await loadPeriodData();
}

async function loadPeriodData() {
  const semesterId = valueOf('sem-select');
  const semester = adminState.semesters.find((s) => String(s.Id) === semesterId);
  const displaySem = $id('display-sem');
  if (displaySem && semester) displaySem.textContent = semester.SemesterName;

  try {
    const query = semesterId ? `?semester_id=${encodeURIComponent(semesterId)}` : '';
    const [current, all] = await Promise.all([
      adminApi(`/periods/current${query}`),
      adminApi('/periods'),
    ]);
    const period = current.data ? current.data.Period : null;

    $id('display-start').textContent = period ? formatDateTime(period.StartDate) : 'Not configured';
    $id('display-end').textContent = period ? formatDateTime(period.EndDate) : 'Not configured';
    const windowStatus = $id('window-status');
    if (windowStatus) windowStatus.textContent = period ? period.WindowStatus : 'Not configured';
    if ($id('start-dt')) $id('start-dt').value = period ? toDateTimeLocal(period.StartDate) : '';
    if ($id('end-dt')) $id('end-dt').value = period ? toDateTimeLocal(period.EndDate) : '';

    adminState.periods = all.data || [];
    renderPeriodLog();
  } catch (err) {
    showAdminToast('period-toast', err.message, 'danger');
  }
}

function renderPeriodLog() {
  const tbody = $id('period-tbody');
  if (!tbody) return;
  const list = adminState.periods;
  const pageItems = paginate(list, 'periods');

  tbody.innerHTML = pageItems.map((p) => {
    const toggle = p.IsActive
      ? `<button class="btn btn-danger-soft btn-sm" onclick="togglePeriodActive(${p.Id}, false)">Close</button>`
      : `<button class="btn btn-soft btn-sm" onclick="togglePeriodActive(${p.Id}, true)">Reopen</button>`;
    return `
      <tr>
        <td><strong>${escapeHtml(p.SemesterCode)}</strong></td>
        <td>${escapeHtml(p.SemesterName)}<br><small style="color: var(--text-muted)">${escapeHtml(p.PeriodName)}</small></td>
        <td>${formatDateTime(p.StartDate)}</td>
        <td>${formatDateTime(p.EndDate)}</td>
        <td>System Administrator</td>
        <td><div class="action-group">${statusBadge(p.WindowStatus)} ${toggle}</div></td>
      </tr>`;
  }).join('');

  setEmptyState('period-empty', list.length === 0);
  renderPagination('period-pagination', 'periods', list.length, renderPeriodLog);
}

async function handleSavePeriod(event) {
  event.preventDefault();
  const start = valueOf('start-dt');
  const end = valueOf('end-dt');
  if (start && end && new Date(end) <= new Date(start)) {
    showAdminToast('period-toast', 'Ngày kết thúc phải sau ngày bắt đầu.', 'warning');
    return;
  }
  const payload = {
    semester_id: valueOf('sem-select') || null,
    start_date: start,
    end_date: end,
  };
  try {
    const { message } = await adminApi('/periods', { method: 'POST', body: payload });
    showAdminToast('period-toast', message, 'success');
    await loadPeriodData();
  } catch (err) {
    showAdminToast('period-toast', err.message, 'danger');
  }
}

async function togglePeriodActive(periodId, makeActive) {
  const verb = makeActive ? 'MỞ LẠI' : 'ĐÓNG';
  if (!window.confirm(`Bạn có chắc muốn ${verb} đợt đăng ký này?`)) return;
  try {
    const { message } = await adminApi(`/periods/${periodId}/active`, {
      method: 'POST',
      body: { is_active: makeActive },
    });
    showAdminToast('period-toast', message, 'success');
    await loadPeriodData();
  } catch (err) {
    showAdminToast('period-toast', err.message, 'danger');
  }
}

/* ==========================================================================
   6. TRANG BAO CAO THONG KE (admin-reports.html)
   ========================================================================== */
async function initReportsPage() {
  try {
    await loadSemesterOptions('report-sem');
  } catch (err) {
    showAdminToast(null, err.message, 'danger');
  }
  await loadReportData();
}

async function loadReportData() {
  const semesterId = valueOf('report-sem');
  try {
    const query = semesterId ? `?semester_id=${encodeURIComponent(semesterId)}` : '';
    const { data } = await adminApi(`/reports${query}`);
    adminState.report = data;
    const s = data.Summary || {};
    $id('rep-total-sections').textContent = `${s.TotalSections || 0} Sections`;
    $id('rep-total-enrollments').textContent = `${s.TotalEnrollments || 0} Enrollments`;
    $id('rep-avg-fill').textContent = `${Number(s.AverageFillRate || 0).toFixed(1)}%`;
    $id('rep-avg-credits').textContent = `${Number(s.AverageCredits || 0).toFixed(1)} Credits`;
    getPageState('sectionReport').page = 1;
    getPageState('studentReport').page = 1;
    updateReportView();
  } catch (err) {
    adminState.report = null;
    showAdminToast(null, err.message, 'danger');
    updateReportView();
  }
}

function updateReportView() {
  const type = valueOf('report-type') || 'section';
  const bySection = $id('view-by-section');
  const byStudent = $id('view-by-student');
  if (bySection) bySection.classList.toggle('hidden', type !== 'section');
  if (byStudent) byStudent.classList.toggle('hidden', type !== 'student');
  const indicator = $id('mode-indicator');
  if (indicator) indicator.textContent = type === 'section' ? 'By Course / Section' : 'By Student';
  if (type === 'section') renderSectionReport();
  else renderStudentReport();
}

function filterReportTable() {
  getPageState('sectionReport').page = 1;
  getPageState('studentReport').page = 1;
  updateReportView();
}

function toggleNoReportData(isEmpty) {
  const notice = $id('no-report-data');
  if (notice) notice.classList.toggle('hidden', !isEmpty);
}

function renderSectionReport() {
  const tbody = $id('section-report-tbody');
  if (!tbody) return;
  const keyword = valueOf('report-search').toLowerCase();
  const all = (adminState.report && adminState.report.Sections) || [];
  const list = all.filter((s) => !keyword || [s.ClassCode, s.CourseCode, s.CourseName, s.LecturerName]
    .some((f) => String(f || '').toLowerCase().includes(keyword)));
  const pageItems = paginate(list, 'sectionReport');

  tbody.innerHTML = pageItems.map((s) => {
    const rate = Number(s.FillRate || 0);
    const fillClass = (s.CurrentEnrollment || 0) < MIN_CLASS_ENROLLMENT ? 'low' : (rate >= 80 ? 'high' : '');
    return `
      <tr>
        <td><strong>${escapeHtml(s.ClassCode)}</strong></td>
        <td>${escapeHtml(s.CourseCode)}</td>
        <td>${escapeHtml(s.CourseName)}</td>
        <td>${escapeHtml(s.LecturerName || 'Unassigned')}</td>
        <td>${escapeHtml(s.CurrentEnrollment)}</td>
        <td>${escapeHtml(s.MaxCapacity)}</td>
        <td>${rate.toFixed(1)}%
            <div class="capacity-bar-wrap"><div class="capacity-bar-fill ${fillClass}" style="width: ${Math.min(100, rate)}%"></div></div></td>
        <td>${statusBadge(s.Status)}</td>
      </tr>`;
  }).join('');

  toggleNoReportData(all.length === 0);
  renderPagination('section-rep-pagination', 'sectionReport', list.length, renderSectionReport);
}

function renderStudentReport() {
  const tbody = $id('student-report-tbody');
  if (!tbody) return;
  const keyword = valueOf('report-search').toLowerCase();
  const all = (adminState.report && adminState.report.Students) || [];
  const list = all.filter((s) => !keyword || [s.StudentCode, s.FullName, s.Major, (s.Classes || []).join(' ')]
    .some((f) => String(f || '').toLowerCase().includes(keyword)));
  const pageItems = paginate(list, 'studentReport');

  tbody.innerHTML = pageItems.map((s) => `
    <tr>
      <td><strong>${escapeHtml(s.StudentCode)}</strong></td>
      <td>${escapeHtml(s.FullName)}</td>
      <td>${escapeHtml(s.Major || '--')}</td>
      <td>${(s.Classes || []).length ? escapeHtml(s.Classes.join(', ')) : '<span style="color: var(--text-muted)">None</span>'}</td>
      <td>${escapeHtml(s.CourseCount)}</td>
      <td><strong>${escapeHtml(s.TotalCredits)}</strong></td>
      <td>${statusBadge(s.Compliance)}
          <small style="color: var(--text-muted)">(${escapeHtml(s.MinCredits)}–${escapeHtml(s.MaxCredits)})</small></td>
    </tr>`).join('');

  toggleNoReportData(all.length === 0);
  renderPagination('student-rep-pagination', 'studentReport', list.length, renderStudentReport);
}

/* ==========================================================================
   7. KHOI TAO - tu nhan dien trang dang mo
   ========================================================================== */
document.addEventListener('DOMContentLoaded', () => {
  loadAdminIdentity();

  if ($id('users-tbody')) loadUserAccounts();
  if ($id('courses-tbody')) loadAdminCourses();
  if ($id('admin-classes-tbody')) initClassesPage();
  if ($id('period-tbody')) initPeriodPage();
  if ($id('section-report-tbody')) initReportsPage();

  // Dong modal khi bam ra ngoai vung noi dung
  document.addEventListener('click', (event) => {
    if (!event.target.classList || !event.target.classList.contains('modal-overlay')) return;
    if (event.target.id === 'edit-user-modal') closeEditUser();
    if (event.target.id === 'edit-course-modal') closeEditCourse();
    if (event.target.id === 'cancel-sec-modal') closeCancelSectionModal();
  });
});
