# HỆ THỐNG ĐĂNG KÝ HỌC PHẦN (NHÓM 08 - CNPM)

## 2. Hướng dẫn khởi chạy bằng Docker

Tất cả các cấu hình Docker nằm gọn trong thư mục `Docker/`:

- `Docker/docker-compose.yml`: Quản lý SQL Server 2022, dịch vụ tự động tạo database (`db-init`), và ứng dụng Web.
- `Docker/Dockerfile.web`: Đóng gói ứng dụng Flask Web (Python 3.11 + ODBC Driver 18).

### Các bước chạy:

1. Mở Terminal (PowerShell hoặc CMD) và vào thư mục `Docker`:

   ```bash

   ```

2. Khởi chạy toàn bộ hệ thống:

   ```bash
   docker compose up -d
   ```

3. Xem log tiến trình (theo dõi quá trình SQL Server bật và nạp database):

   ```bash
   docker compose logs -f
   ```

4. Truy cập ứng dụng web:
   - Mở trình duyệt web: [http://localhost:5000](http://localhost:5000)

5. Dừng hệ thống khi không dùng nữa:
   ```bash
   docker compose down
   ```
   _(Nếu muốn xóa sạch database để dựng lại từ đầu: `docker compose down -v`)_

---

## 3. Quản lý CSDL không cần SSMS

Thay vì cài đặt phần mềm SSMS nặng nề, bạn có thể dùng **Azure Data Studio**, **DBeaver** hoặc tiện ích mở rộng **SQL Server (mssql)** ngay trong VS Code:

- **Server**: `localhost,1433`
- **Authentication**: `SQL Login`
- **Username**: `sa`
- **Password**: `StrongPass@2026`
- **Database**: `CourseRegistrationDB`
- **Trust server certificate**: `True` (Tích chọn)

---

## 4. Danh sách tài khoản đăng nhập mẫu (Mật khẩu: `123456`)

| Vai trò                   | Tên đăng nhập (Username)  | Họ và tên                |
| :------------------------ | :------------------------ | :----------------------- |
| **Quản trị viên**         | `admin`                   | Nguyễn Văn Quản          |
| **Quản trị viên**         | `admin_daotao`            | Trần Thị Bích Loan       |
| **Giảng viên**            | `gv_nam`                  | TS. Lê Hoàng Nam         |
| **Giảng viên**            | `gv_mai`                  | ThS. Trần Phương Mai     |
| **Sinh viên**             | `sv_an`                   | Nguyễn Văn An            |
| **Sinh viên**             | `sv_binh`                 | Trần Hải Bình            |
| _(Tất cả tài khoản khác)_ | `sv_chau`, `sv_dung`, ... | Mật khẩu đều là `123456` |
