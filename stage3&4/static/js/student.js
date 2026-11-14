/* ==========================================================================
   static/js/student.js  -  PHÂN HỆ SINH VIÊN (Student Portal)
   Hệ thống Đăng ký Môn học (Course Registration System)

   Chức năng:
     1. Tra cứu & Đăng ký môn học (kiểm tra 4 điều kiện nghiêm ngặt).
     2. Hủy đăng ký môn học (modal xác nhận, giảm sĩ số, hoàn tín chỉ).
     3. Thời khóa biểu dạng lưới tuần & điều hướng tuần (This Week, Prev, Next).
     4. Tính toán và bảng kê học phí tự động theo đơn giá tín chỉ.
     5. Lịch sử giao dịch đăng ký môn học (Audit Log).
     6. Quản lý hồ sơ sinh viên & đổi mật khẩu tài khoản.
   ========================================================================== */

const STU_API = '/student/api';
const STU_PAGE_SIZE_OPTIONS = [5, 10, 20];

const studentState = {
    profile: null,
    semesterId: null,
    semesters: [],
    availableClasses: [],
    filteredAvailable: [],
    registeredClasses: [],
    week: null,
    totalWeeks: 1,
    cancelingClassId: null,
    paging: {},
};

/* ------------------------------ TIỆN ÍCH CHUNG ------------------------------ */
function stuEl(id) {
    return document.getElementById(id);
}

function escapeHtml(value) {
    return String(value === null || value === undefined ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function stuSetText(id, text) {
    const el = stuEl(id);
    if (el) el.textContent = text;
}

function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
}

function formatDateTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    const pad = (n) => String(n).padStart(2, '0');
    return `${formatDate(iso)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatCurrency(amount) {
    if (amount === null || amount === undefined || isNaN(amount)) return '0 VNĐ';
    return Number(amount).toLocaleString('vi-VN') + ' VNĐ';
}

function _fmt_time(val) {
    if (!val) return '';
    if (typeof val === 'string') {
        const parts = val.split(':');
        if (parts.length >= 2) return `${parts[0].padStart(2, '0')}:${parts[1].padStart(2, '0')}`;
        return val;
    }
    return String(val);
}

/* Hiển thị Toast / Banner thông báo */
let stuBannerTimer = null;
function showFeedback(bannerId, message, type = 'success') {
    const el = stuEl(bannerId);
    if (!el) {
        if (typeof showToast === 'function') {
            showToast(message, type === 'danger' ? 'danger' : 'success');
        }
        return;
    }
    el.textContent = message;
    el.className = `toast-banner toast-${type === 'danger' ? 'danger' : (type === 'warning' ? 'warning' : 'success')}`;
    el.classList.remove('hidden');
    clearTimeout(stuBannerTimer);
    stuBannerTimer = setTimeout(() => {
        el.classList.add('hidden');
    }, 5000);
}

/* API Fetch Helpers */
async function stuGet(path) {
    try {
        const res = await fetch(`${STU_API}${path}`, {
            headers: { 'Accept': 'application/json' }
        });
        if (res.status === 401) {
            window.location.href = '/login';
            return null;
        }
        return await res.json();
    } catch (err) {
        console.error('Fetch GET Error:', err);
        showFeedback('feedback-banner', 'Lỗi kết nối máy chủ!', 'danger');
        return null;
    }
}

async function stuPost(path, data) {
    try {
        const res = await fetch(`${STU_API}${path}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(data)
        });
        if (res.status === 401) {
            window.location.href = '/login';
            return null;
        }
        return await res.json();
    } catch (err) {
        console.error('Fetch POST Error:', err);
        return { success: false, message: 'Lỗi kết nối máy chủ!' };
    }
}

/* Phân trang (Pagination) */
function stuPaginate(key, items, containerId, renderRows) {
    const box = stuEl(containerId);
    const p = studentState.paging[key] || (studentState.paging[key] = { page: 1, size: 10 });
    const pages = Math.max(1, Math.ceil(items.length / p.size));
    p.page = Math.min(Math.max(p.page, 1), pages);
    const start = (p.page - 1) * p.size;
    renderRows(items.slice(start, start + p.size), start);

    if (!box) return;
    if (items.length === 0) {
        box.innerHTML = '';
        return;
    }

    const from = start + 1;
    const to = Math.min(start + p.size, items.length);
    const sizeOpts = [5, 10, 20, 50]
        .map((n) => `<option value="${n}" ${n === p.size ? 'selected' : ''}>${n} / trang</option>`)
        .join('');

    let btns = '';
    for (let i = 1; i <= pages; i++) {
        if (i === 1 || i === pages || Math.abs(i - p.page) <= 1) {
            btns += `<button type="button" class="page-btn ${i === p.page ? 'active' : ''}" data-page="${i}">${i}</button>`;
        } else if (btns.slice(-24) !== '<span class="page-dots">…</span>') {
            btns += '<span class="page-dots">…</span>';
        }
    }

    box.innerHTML = `
        <div class="pagination-bar" style="display:flex; justify-content:space-between; align-items:center; margin-top:14px; padding:8px 0; border-top:1px solid var(--border-light, #e2e8f0);">
            <div class="pagination-info" style="font-size:0.82rem; color:var(--text-muted);">
                Hiển thị <strong>${from}–${to}</strong> trên <strong>${items.length}</strong> dòng
            </div>
            <div class="pagination-controls" style="display:flex; gap:6px; align-items:center;">
                <select class="page-size-select" style="padding:4px 8px; font-size:0.82rem; border-radius:4px; border:1px solid var(--border-medium); margin-right:8px;">
                    ${sizeOpts}
                </select>
                <button type="button" class="page-btn" data-page="${p.page - 1}" ${p.page <= 1 ? 'disabled' : ''}>&lsaquo;</button>
                <div class="page-buttons" style="display:inline-flex; gap:4px;">${btns}</div>
                <button type="button" class="page-btn" data-page="${p.page + 1}" ${p.page >= pages ? 'disabled' : ''}>&rsaquo;</button>
            </div>
        </div>
    `;

    box.querySelectorAll('button.page-btn').forEach((btn) => {
        btn.onclick = () => {
            const newPage = parseInt(btn.dataset.page, 10);
            if (!isNaN(newPage) && newPage >= 1 && newPage <= pages) {
                p.page = newPage;
                stuPaginate(key, items, containerId, renderRows);
            }
        };
    });

    const sel = box.querySelector('.page-size-select');
    if (sel) {
        sel.onchange = () => {
            p.size = parseInt(sel.value, 10);
            p.page = 1;
            stuPaginate(key, items, containerId, renderRows);
        };
    }
}


/* ==========================================================================
   1. TRA CỨU & ĐĂNG KÝ MÔN HỌC (courses.html)
   ========================================================================== */

/* Nạp dropdown danh mục học kỳ */
async function loadSemestersDropdown(selectId, onSelectCallback) {
    const sel = stuEl(selectId);
    if (!sel) return;

    if (!studentState.semesters.length) {
        const res = await stuGet('/semesters');
        if (res && res.success && res.data) {
            studentState.semesters = res.data.semesters || [];
            if (!studentState.semesterId) {
                studentState.semesterId = res.data.current_semester_id;
            }
        }
    }

    if (studentState.semesters.length) {
        sel.innerHTML = studentState.semesters.map((s) => `
            <option value="${s.Id}" ${s.Id === studentState.semesterId ? 'selected' : ''}>
                ${escapeHtml(s.SemesterName)} (${escapeHtml(s.AcademicYear)}) ${s.IsCurrent ? '★ Hiện hành' : ''}
            </option>
        `).join('');
    }

    sel.onchange = () => {
        studentState.semesterId = parseInt(sel.value, 10);
        if (typeof onSelectCallback === 'function') {
            onSelectCallback();
        }
    };
}

/* Nạp toàn bộ danh mục lớp học phần & các lớp đã đăng ký */
async function loadCourseModules() {
    const semSelect = stuEl('semester');
    if (semSelect && semSelect.options.length <= 2 && !studentState.semesters.length) {
        await loadSemestersDropdown('semester', loadCourseModules);
    } else if (semSelect) {
        studentState.semesterId = parseInt(semSelect.value, 10) || studentState.semesterId;
    }

    const res = await stuGet(`/courses?semester_id=${studentState.semesterId || ''}`);
    if (!res || !res.success) {
        showFeedback('feedback-banner', (res && res.message) || 'Không tải được danh mục lớp học phần.', 'danger');
        return;
    }

    const data = res.data;
    studentState.availableClasses = data.classes || [];
    studentState.registeredClasses = data.registered_classes || [];

    // Cập nhật số tín chỉ đã đăng ký trên Top Bar
    const creditsPill = stuEl('user-registered-credits');
    if (creditsPill) {
        creditsPill.textContent = data.current_credits;
        const pillWrap = creditsPill.parentElement;
        if (pillWrap) {
            if (data.current_credits < (data.min_credits || 12)) {
                pillWrap.style.borderColor = 'var(--warning-border)';
                pillWrap.style.color = 'var(--warning)';
            } else if (data.current_credits > (data.max_credits || 25)) {
                pillWrap.style.borderColor = 'var(--danger-border)';
                pillWrap.style.color = 'var(--danger)';
            } else {
                pillWrap.style.borderColor = 'var(--success-border)';
                pillWrap.style.color = 'var(--success)';
            }
        }
    }

    filterRows();
    renderRegisteredCourses();
}

/* Lọc lớp học phần (Search & Filter) */
function filterRows() {
    const q = (stuEl('q-input')?.value || '').toLowerCase().trim();
    const day = stuEl('day-select')?.value || '';
    const seat = stuEl('seat-select')?.value || '';

    studentState.filteredAvailable = studentState.availableClasses.filter((c) => {
        // Lọc từ khóa: Mã môn, Tên môn, Lớp học phần, Giảng viên
        const matchQ = !q ||
            c.CourseCode.toLowerCase().includes(q) ||
            c.CourseName.toLowerCase().includes(q) ||
            c.ClassCode.toLowerCase().includes(q) ||
            (c.LecturerName && c.LecturerName.toLowerCase().includes(q));

        // Lọc theo ngày trong tuần
        const matchDay = !day || c.DayName === day;

        // Lọc theo tình trạng chỗ trống
        let matchSeat = true;
        if (seat === 'open') {
            matchSeat = c.RemainingSeats > 0 && !c.IsFull;
        } else if (seat === 'full') {
            matchSeat = c.RemainingSeats <= 0 || c.IsFull;
        }

        return matchQ && matchDay && matchSeat;
    });

    renderAvailableCourses();
}

/* Hiển thị bảng các lớp học phần đang mở */
function renderAvailableCourses() {
    const tbody = stuEl('available-courses-tbody');
    const emptyMsg = stuEl('empty-search');
    if (!tbody) return;

    if (!studentState.filteredAvailable.length) {
        tbody.innerHTML = '';
        if (emptyMsg) emptyMsg.classList.remove('hidden');
        return;
    }
    if (emptyMsg) emptyMsg.classList.add('hidden');

    stuPaginate('available', studentState.filteredAvailable, 'course-pagination', (rows) => {
        tbody.innerHTML = rows.map((c) => {
            // Nút hành động tương ứng với trạng thái
            let actionHtml = '';
            if (c.IsEnrolled) {
                actionHtml = `<span class="badge badge-success" style="padding:6px 10px; font-weight:700;">Đã Đăng Ký</span>`;
            } else if (c.CanRegister) {
                actionHtml = `
                    <button type="button" class="btn btn-primary btn-sm" onclick="registerCourse(${c.Id})">
                        Đăng Ký
                    </button>
                    <a href="course-details.html?class_id=${c.Id}" class="btn btn-soft btn-sm" title="Chi tiết môn học">
                        Chi tiết
                    </a>
                `;
            } else {
                actionHtml = `
                    <button type="button" class="btn btn-soft btn-sm" disabled style="opacity:0.6; cursor:not-allowed;" title="${escapeHtml(c.ReasonDisabled)}">
                        Không thể ĐK
                    </button>
                    <small style="display:block; color:var(--danger); font-size:0.72rem; margin-top:3px;">
                        ${escapeHtml(c.ReasonDisabled)}
                    </small>
                `;
            }

            // Hiển thị sĩ số và chỗ trống
            const seatBadge = c.RemainingSeats <= 0
                ? `<span class="badge badge-danger">Hết chỗ (0/${c.MaxCapacity})</span>`
                : (c.RemainingSeats <= 5
                    ? `<span class="badge badge-warning">Còn ${c.RemainingSeats}/${c.MaxCapacity}</span>`
                    : `<span class="badge badge-info">Còn ${c.RemainingSeats}/${c.MaxCapacity}</span>`);

            // Hiển thị môn tiên quyết
            const prereqDisplay = c.PrerequisiteCode
                ? (c.PrerequisiteMet
                    ? `<span style="color:var(--success); font-weight:600;">✓ ${escapeHtml(c.PrerequisiteCode)}</span>`
                    : `<span style="color:var(--danger); font-weight:600;">✗ ${escapeHtml(c.PrerequisiteCode)} (Chưa đạt)</span>`)
                : '<span style="color:var(--text-muted);">Không có</span>';

            return `
                <tr>
                    <td><strong>${escapeHtml(c.CourseCode)}</strong></td>
                    <td>
                        <a href="course-details.html?class_id=${c.Id}" style="text-decoration:none; color:inherit; font-weight:600;">
                            ${escapeHtml(c.CourseName)}
                        </a>
                    </td>
                    <td><span class="badge badge-primary">${escapeHtml(c.ClassCode)}</span></td>
                    <td><strong>${escapeHtml(c.Credits)}</strong></td>
                    <td>${escapeHtml(c.LecturerName || 'Chưa phân công')}</td>
                    <td>
                        <div style="font-size:0.84rem;">
                            <strong>${escapeHtml(c.DayNameVi)}</strong> • ${escapeHtml(c.TimeRange)}
                        </div>
                        <div style="font-size:0.76rem; color:var(--text-muted);">Phòng: ${escapeHtml(c.Room)}</div>
                    </td>
                    <td>${prereqDisplay}</td>
                    <td>${seatBadge}</td>
                    <td style="white-space:nowrap;">${actionHtml}</td>
                </tr>
            `;
        }).join('');
    });
}

/* Hiển thị bảng các môn học đã đăng ký trong kỳ */
function renderRegisteredCourses() {
    const tbody = stuEl('registered-courses-tbody');
    const emptyMsg = stuEl('empty-registered');
    if (!tbody) return;

    if (!studentState.registeredClasses.length) {
        tbody.innerHTML = '';
        if (emptyMsg) emptyMsg.classList.remove('hidden');
        return;
    }
    if (emptyMsg) emptyMsg.classList.add('hidden');

    stuPaginate('registered', studentState.registeredClasses, 'registered-pagination', (rows) => {
        tbody.innerHTML = rows.map((c) => `
            <tr>
                <td><strong>${escapeHtml(c.CourseCode)}</strong></td>
                <td><strong>${escapeHtml(c.CourseName)}</strong></td>
                <td><span class="badge badge-primary">${escapeHtml(c.ClassCode)}</span></td>
                <td><strong>${escapeHtml(c.Credits)} TC</strong></td>
                <td>${escapeHtml(c.LecturerName || 'Chưa phân công')}</td>
                <td>
                    <div style="font-size:0.84rem;">
                        <strong>${escapeHtml(c.DayNameVi)}</strong> • ${escapeHtml(c.TimeRange)}
                    </div>
                    <div style="font-size:0.76rem; color:var(--text-muted);">Phòng: ${escapeHtml(c.Room)}</div>
                </td>
                <td><span class="badge badge-success">Enrolled</span></td>
                <td>
                    <button type="button" class="btn btn-danger-soft btn-sm"
                            onclick="openCancel(${c.ClassId}, '${escapeHtml(c.CourseCode)}', '${escapeHtml(c.CourseName)}', '${escapeHtml(c.ClassCode)}')">
                        Hủy Môn
                    </button>
                </td>
            </tr>
        `).join('');
    });
}

/* Thực thi Đăng ký môn học */
async function registerCourse(classId) {
    const res = await stuPost('/register', { class_id: classId });
    if (res && res.success) {
        showFeedback('feedback-banner', res.message || 'Đăng ký môn học thành công!', 'success');
        await loadCourseModules();
    } else {
        const msg = (res && res.message) || 'Đăng ký môn học thất bại.';
        showFeedback('feedback-banner', msg, 'danger');
    }
}


/* ==========================================================================
   2. HỦY ĐĂNG KÝ MÔN HỌC (Modal & Confirm)
   ========================================================================== */
function openCancel(classId, courseCode, courseName, classCode) {
    studentState.cancelingClassId = classId;
    const targetBox = stuEl('cancel-target');
    if (targetBox) {
        targetBox.innerHTML = `
            <div style="font-size:1rem; color:var(--danger); font-weight:700;">
                [${escapeHtml(courseCode)}] ${escapeHtml(courseName)}
            </div>
            <div style="font-size:0.85rem; color:var(--text-secondary); margin-top:4px;">
                Mã lớp học phần: <strong>${escapeHtml(classCode)}</strong>
            </div>
        `;
    }
    const modal = stuEl('cancel-modal');
    if (modal) modal.classList.remove('hidden');
}

function closeCancel() {
    studentState.cancelingClassId = null;
    const modal = stuEl('cancel-modal');
    if (modal) modal.classList.add('hidden');
}

async function confirmCancel() {
    if (!studentState.cancelingClassId) return;
    const classId = studentState.cancelingClassId;
    closeCancel();

    const res = await stuPost('/drop', { class_id: classId });
    if (res && res.success) {
        showFeedback('feedback-banner', res.message || 'Hủy môn học thành công!', 'success');
        await loadCourseModules();
    } else {
        const msg = (res && res.message) || 'Hủy môn học thất bại.';
        showFeedback('feedback-banner', msg, 'danger');
    }
}


/* ==========================================================================
   3. THỜI KHÓA BIỂU DẠNG LƯỚI TUẦN (timetable.html)
   ========================================================================== */
function onSemesterChange() {
    studentState.week = null;
    loadTimetable();
}

function prevWeek() {
    if (studentState.week && studentState.week > 1) {
        studentState.week -= 1;
        loadTimetable();
    }
}

function nextWeek() {
    if (studentState.week && studentState.week < studentState.totalWeeks) {
        studentState.week += 1;
        loadTimetable();
    }
}

function resetToCurrentWeek() {
    studentState.week = null;
    loadTimetable();
}

async function loadTimetable() {
    const semSelect = stuEl('sem-tt');
    if (semSelect && semSelect.options.length <= 2 && !studentState.semesters.length) {
        await loadSemestersDropdown('sem-tt', loadTimetable);
    } else if (semSelect) {
        studentState.semesterId = parseInt(semSelect.value, 10) || studentState.semesterId;
    }

    const board = stuEl('timetable-board');
    const loading = stuEl('timetable-loading');
    const emptyNotice = stuEl('timetable-empty');

    if (loading) loading.classList.remove('hidden');
    if (emptyNotice) emptyNotice.classList.add('hidden');

    const weekParam = studentState.week ? `&week=${studentState.week}` : '';
    const res = await stuGet(`/timetable?semester_id=${studentState.semesterId || ''}${weekParam}`);

    if (loading) loading.classList.add('hidden');

    if (!res || !res.success) {
        if (board) board.innerHTML = '';
        if (emptyNotice) {
            emptyNotice.textContent = (res && res.message) || 'Không tải được thời khóa biểu.';
            emptyNotice.classList.remove('hidden');
        }
        return;
    }

    const data = res.data;
    studentState.week = data.week.week;
    studentState.totalWeeks = data.week.total_weeks;

    // Cập nhật nhãn tuần & ngày tháng
    stuSetText('current-week-display', `Tuần ${data.week.week} / ${data.week.total_weeks}`);
    stuSetText('week-date-range',
        `Lịch học trong tuần: ${formatDate(data.week.week_start)} — ${formatDate(data.week.week_end)} (Học kỳ: ${data.semester.SemesterName})`);
    stuSetText('enrolled-count', `${data.total_enrolled} Lớp (${data.total_credits} Tín chỉ)`);

    // Render lưới thời khóa biểu
    const days = data.days || [];
    const slots = data.slots || [];
    const sessions = data.sessions || [];

    if (!board) return;
    board.style.gridTemplateColumns = `115px repeat(${days.length}, 1fr)`;

    let html = '<div class="tt-col-header">Ca / Giờ học</div>';
    html += days.map((d) => `
        <div class="tt-col-header">
            ${escapeHtml(d.name_vi)}<br>
            <small style="opacity:0.85; font-weight:normal;">${formatDate(d.date)}</small>
        </div>
    `).join('');

    slots.forEach((slot, slotIdx) => {
        html += `
            <div class="tt-time-slot">
                <strong>Ca ${escapeHtml(slot.SlotNumber)}</strong>
                <span>${_fmt_time(slot.StartTime)} - ${_fmt_time(slot.EndTime)}</span>
            </div>
        `;

        days.forEach((day) => {
            const matched = sessions.filter((s) => s.DayOfWeek === day.day && s.TimeSlotId === slot.Id);
            const cardsHtml = matched.map((s, idx) => {
                const colorClass = (slotIdx + idx) % 2 === 1 ? 'green' : '';
                return `
                    <div class="tt-card ${colorClass}" style="margin-bottom:4px;">
                        <div>
                            <strong>${escapeHtml(s.CourseCode)} • ${escapeHtml(s.ClassCode)}</strong>
                            <span>${escapeHtml(s.CourseName)}</span>
                        </div>
                        <div style="font-size:0.72rem; margin-top:6px; border-top:1px dashed rgba(0,0,0,0.1); padding-top:4px;">
                            <span>📍 Phòng: <strong>${escapeHtml(s.Room)}</strong></span>
                            <span>👨‍🏫 GV: ${escapeHtml(s.LecturerName || 'TBA')}</span>
                            <span>🎖️ ${escapeHtml(s.Credits)} Tín chỉ</span>
                        </div>
                    </div>
                `;
            }).join('');

            html += `<div class="tt-cell">${cardsHtml}</div>`;
        });
    });

    board.innerHTML = html;

    if (emptyNotice) {
        emptyNotice.textContent = 'Tuần này không có buổi học nào.';
        emptyNotice.classList.toggle('hidden', sessions.length > 0);
    }
}


/* ==========================================================================
   4. BẢNG KÊ HỌC PHÍ TỰ ĐỘNG (tuition.html)
   ========================================================================== */
async function loadTuitionData() {
    const semSelect = stuEl('sem-fee');
    if (semSelect && semSelect.options.length <= 2 && !studentState.semesters.length) {
        await loadSemestersDropdown('sem-fee', loadTuitionData);
    } else if (semSelect) {
        studentState.semesterId = parseInt(semSelect.value, 10) || studentState.semesterId;
    }

    const res = await stuGet(`/tuition?semester_id=${studentState.semesterId || ''}`);
    if (!res || !res.success) {
        showFeedback('feedback-banner', (res && res.message) || 'Không tải được bảng kê học phí.', 'danger');
        return;
    }

    const data = res.data;
    const s = data.summary;

    // Cập nhật 4 thẻ thống kê
    stuSetText('stat-total-courses', `${s.total_courses} Môn học`);
    stuSetText('stat-total-credits', `${s.total_credits} Tín chỉ`);
    stuSetText('stat-rate', `${formatCurrency(s.unit_price)} / TC`);
    stuSetText('stat-total-fee', formatCurrency(s.total_amount));

    const statusBadge = stuEl('billing-status');
    if (statusBadge) {
        statusBadge.textContent = `Trạng thái: ${s.payment_status} (${s.billing_status})`;
        statusBadge.className = `badge ${s.payment_status === 'Paid' ? 'badge-success' : (s.payment_status === 'Partial' ? 'badge-warning' : 'badge-primary')}`;
    }

    // Render danh sách chi tiết từng môn
    const tbody = stuEl('tuition-tbody');
    const emptyMsg = stuEl('tuition-empty');
    if (!tbody) return;

    if (!data.items.length) {
        tbody.innerHTML = '';
        if (emptyMsg) emptyMsg.classList.remove('hidden');
        return;
    }
    if (emptyMsg) emptyMsg.classList.add('hidden');

    stuPaginate('tuition', data.items, 'tuition-pagination', (rows) => {
        tbody.innerHTML = rows.map((item) => `
            <tr>
                <td>${item.index}</td>
                <td><strong>${escapeHtml(item.course_code)}</strong></td>
                <td>${escapeHtml(item.course_name)}</td>
                <td><span class="badge badge-primary">${escapeHtml(item.class_code)}</span></td>
                <td><strong>${item.credits}</strong></td>
                <td>${formatCurrency(item.unit_price)}</td>
                <td><strong>${formatCurrency(item.subtotal)}</strong></td>
            </tr>
        `).join('');
    });
}


/* ==========================================================================
   5. LỊCH SỬ GIAO DỊCH ĐĂNG KÝ MÔN HỌC (history.html)
   ========================================================================== */
async function loadHistoryData() {
    const filter = stuEl('history-filter')?.value || 'all';
    const res = await stuGet(`/history?filter=${filter}&semester_id=${studentState.semesterId || ''}`);
    if (!res || !res.success) {
        return;
    }

    const rows = res.data || [];
    const tbody = stuEl('history-tbody');
    const emptyMsg = stuEl('history-empty');
    if (!tbody) return;

    if (!rows.length) {
        tbody.innerHTML = '';
        if (emptyMsg) emptyMsg.classList.remove('hidden');
        return;
    }
    if (emptyMsg) emptyMsg.classList.add('hidden');

    stuPaginate('history', rows, 'history-pagination', (paged) => {
        tbody.innerHTML = paged.map((h) => `
            <tr>
                <td><code>#${h.TransactionId}</code></td>
                <td>${formatDateTime(h.ActionTime)}</td>
                <td><strong>${escapeHtml(h.CourseCode)}</strong></td>
                <td>${escapeHtml(h.CourseName)}</td>
                <td><span class="badge badge-primary">${escapeHtml(h.ClassCode)}</span></td>
                <td><strong>${escapeHtml(h.Credits)} TC</strong></td>
                <td>
                    <span class="badge ${h.StatusClass}">
                        ${h.StatusBadge}
                    </span>
                </td>
            </tr>
        `).join('');
    });
}


/* ==========================================================================
   6. QUẢN LÝ HỒ SƠ & ĐỔI MẬT KHẨU (profile.html)
   ========================================================================== */
async function loadProfileData() {
    const res = await stuGet('/me');
    if (!res || !res.success) return;
    const p = res.data.profile;
    studentState.profile = p;

    // Cập nhật thông tin trong profile.html
    const infoItems = document.querySelectorAll('.info-list .info-item');
    if (infoItems.length >= 6) {
        infoItems[0].querySelector('strong').textContent = p.StudentCode || p.UserCode;
        infoItems[1].querySelector('strong').textContent = p.FullName;
        infoItems[2].querySelector('strong').textContent = p.Role;
        infoItems[3].querySelector('strong').textContent = `${p.Faculty} • ${p.Major}`;
        infoItems[4].querySelector('strong').textContent = `Khóa ${p.EnrollmentYear} (${p.AdministrativeClass})`;
        infoItems[5].querySelector('strong').textContent = p.Email;
    }
}

async function updatePassword(event) {
    if (event) event.preventDefault();
    const curPw = stuEl('current-password')?.value;
    const newPw = stuEl('new-password')?.value;
    const conPw = stuEl('confirm-password')?.value;

    if (!curPw || !newPw || !conPw) {
        showFeedback('pw-feedback', 'Vui lòng điền đầy đủ các trường mật khẩu.', 'danger');
        return;
    }
    if (newPw.length < 6) {
        showFeedback('pw-feedback', 'Mật khẩu mới phải có ít nhất 6 ký tự.', 'danger');
        return;
    }
    if (newPw !== conPw) {
        showFeedback('pw-feedback', 'Mật khẩu xác nhận không khớp.', 'danger');
        return;
    }

    const res = await stuPost('/change-password', {
        current_password: curPw,
        new_password: newPw,
        confirm_password: conPw
    });

    if (res && res.success) {
        showFeedback('pw-feedback', res.message || 'Đổi mật khẩu thành công!', 'success');
        if (stuEl('current-password')) stuEl('current-password').value = '';
        if (stuEl('new-password')) stuEl('new-password').value = '';
        if (stuEl('confirm-password')) stuEl('confirm-password').value = '';
    } else {
        showFeedback('pw-feedback', (res && res.message) || 'Đổi mật khẩu thất bại.', 'danger');
    }
}


/* ==========================================================================
   7. CHI TIẾT MÔN HỌC (course-details.html)
   ========================================================================== */
async function loadCourseDetails() {
    const params = new URLSearchParams(window.location.search);
    const classId = params.get('class_id');
    if (!classId) return;

    const res = await stuGet(`/classes/${classId}`);
    if (!res || !res.success) return;
    const c = res.data;

    // Cập nhật tiêu đề trang
    const headerTitle = document.querySelector('.page-header h1');
    if (headerTitle) {
        headerTitle.textContent = `${c.CourseCode} — ${c.CourseName}`;
    }

    // Cập nhật danh sách chi tiết
    const infoItems = document.querySelectorAll('.info-list .info-item');
    if (infoItems.length >= 5) {
        infoItems[0].querySelector('strong').textContent = c.CourseCode;
        infoItems[1].querySelector('strong').textContent = c.ClassCode;
        infoItems[2].querySelector('strong').textContent = `${c.Credits} Tín chỉ`;
        infoItems[3].querySelector('strong').textContent = c.LecturerName || 'Chưa phân công';
        infoItems[4].querySelector('strong').textContent = `${c.SemesterName} (${c.AcademicYear})`;
    }

    // Nút đăng ký
    const regBtn = document.querySelector('.page-header button');
    if (regBtn) {
        if (c.IsEnrolled) {
            regBtn.textContent = 'Đã Đăng Ký Lớp Này';
            regBtn.className = 'btn btn-soft';
            regBtn.disabled = true;
        } else {
            regBtn.textContent = 'Đăng Ký Học Phần Này';
            regBtn.className = 'btn btn-primary';
            regBtn.onclick = async () => {
                const r = await stuPost('/register', { class_id: c.Id });
                const toast = stuEl('detail-toast');
                if (toast) {
                    toast.textContent = (r && r.message) || 'Kết quả đăng ký';
                    toast.className = `toast-banner toast-${r && r.success ? 'success' : 'danger'}`;
                    toast.classList.remove('hidden');
                }
                if (r && r.success) {
                    setTimeout(() => {
                        window.location.href = 'courses.html';
                    }, 1500);
                }
            };
        }
    }
}


/* ==========================================================================
   8. KHỞI TẠO TỔNG THỂ (Auto Initialization)
   ========================================================================== */
document.addEventListener('DOMContentLoaded', async () => {
    // 1. Cập nhật User Profile Chip trên Top Bar
    const userChip = document.querySelector('.user-profile-chip');
    if (userChip) {
        const res = await stuGet('/me');
        if (res && res.success && res.data.profile) {
            const p = res.data.profile;
            studentState.profile = p;
            userChip.innerHTML = `
                <strong>${escapeHtml(p.FullName)}</strong>
                <span>MSSV: ${escapeHtml(p.StudentCode || p.UserCode)}</span>
            `;
        }
    }

    // 2. Nhận diện trang hiện tại và kích hoạt hàm tương ứng
    if (stuEl('available-courses-tbody')) {
        await loadCourseModules();
    } else if (stuEl('timetable-board')) {
        await loadTimetable();
    } else if (stuEl('tuition-tbody')) {
        await loadTuitionData();
    } else if (stuEl('history-tbody')) {
        await loadHistoryData();
    } else if (stuEl('pw-feedback')) {
        await loadProfileData();
    } else if (window.location.pathname.includes('course-details')) {
        await loadCourseDetails();
    }
});
