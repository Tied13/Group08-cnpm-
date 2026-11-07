-- ==========================================================
-- SCRIPT KHỞI TẠO CƠ SỞ DỮ LIỆU ĐĂNG KÝ HỌC PHẦN (SQL SERVER)
-- ==========================================================

-- 1. TẠO DATABASE
IF NOT EXISTS (SELECT * FROM sys.databases WHERE name = 'CourseRegistrationDB')
BEGIN
    CREATE DATABASE CourseRegistrationDB;
END
GO

USE CourseRegistrationDB;
GO

-- 2. TẠO CÁC BẢNG NỀN TẢNG (TABLES)

-- Bảng Người dùng (Tài khoản truy cập hệ thống)
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Users')
BEGIN
    CREATE TABLE Users (
        Id INT IDENTITY(1,1) PRIMARY KEY,
        Username NVARCHAR(50) UNIQUE NOT NULL,
        Password NVARCHAR(255) NOT NULL,
        FullName NVARCHAR(100) NOT NULL,
        Role NVARCHAR(20) CHECK (Role IN ('admin', 'lecturer', 'student')) NOT NULL,
        Email NVARCHAR(100),
        Phone NVARCHAR(20),
        CreatedAt DATETIME DEFAULT GETDATE()
    );
END
GO

-- Bảng Học phần / Môn học (Courses)
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Courses')
BEGIN
    CREATE TABLE Courses (
        Id INT IDENTITY(1,1) PRIMARY KEY,
        CourseCode NVARCHAR(20) UNIQUE NOT NULL,
        CourseName NVARCHAR(150) NOT NULL,
        Credits INT NOT NULL,
        Description NVARCHAR(MAX)
    );
END
GO

-- Bảng Học kỳ / Giai đoạn đăng ký (Periods / Semesters)
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'RegistrationPeriods')
BEGIN
    CREATE TABLE RegistrationPeriods (
        Id INT IDENTITY(1,1) PRIMARY KEY,
        SemesterName NVARCHAR(50) NOT NULL, -- Ví dụ: Học kỳ 1 (2026 - 2027)
        StartDate DATETIME NOT NULL,
        EndDate DATETIME NOT NULL,
        Status NVARCHAR(20) DEFAULT N'Đang mở' CHECK (Status IN (N'Chưa mở', N'Đang mở', N'Đã đóng'))
    );
END
GO

-- Bảng Lớp học phần (Classes / Course Sections)
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Classes')
BEGIN
    CREATE TABLE Classes (
        Id INT IDENTITY(1,1) PRIMARY KEY,
        ClassCode NVARCHAR(30) UNIQUE NOT NULL,
        CourseId INT NOT NULL FOREIGN KEY REFERENCES Courses(Id),
        LecturerId INT NULL FOREIGN KEY REFERENCES Users(Id),
        PeriodId INT NOT NULL FOREIGN KEY REFERENCES RegistrationPeriods(Id),
        MaxCapacity INT DEFAULT 50,
        CurrentEnrollment INT DEFAULT 0,
        Room NVARCHAR(50),
        DayOfWeek INT, -- 2: Thứ 2, 3: Thứ 3,...
        StartPeriod INT, -- Tiết bắt đầu (1-10)
        EndPeriod INT    -- Tiết kết thúc
    );
END
GO

-- Bảng Đăng ký học phần (Registrations)
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Enrollments')
BEGIN
    CREATE TABLE Enrollments (
        Id INT IDENTITY(1,1) PRIMARY KEY,
        StudentId INT NOT NULL FOREIGN KEY REFERENCES Users(Id),
        ClassId INT NOT NULL FOREIGN KEY REFERENCES Classes(Id),
        EnrollmentDate DATETIME DEFAULT GETDATE(),
        Status NVARCHAR(20) DEFAULT N'Thành công' CHECK (Status IN (N'Thành công', N'Đã hủy')),
        CONSTRAINT UQ_Student_Class UNIQUE(StudentId, ClassId)
    );
END
GO

-- Bảng Học phí (Tuition)
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Tuitions')
BEGIN
    CREATE TABLE Tuitions (
        Id INT IDENTITY(1,1) PRIMARY KEY,
        StudentId INT NOT NULL FOREIGN KEY REFERENCES Users(Id),
        PeriodId INT NOT NULL FOREIGN KEY REFERENCES RegistrationPeriods(Id),
        TotalAmount DECIMAL(18, 2) DEFAULT 0,
        PaidAmount DECIMAL(18, 2) DEFAULT 0,
        Status NVARCHAR(30) DEFAULT N'Chưa thanh toán' CHECK (Status IN (N'Chưa thanh toán', N'Đã thanh toán một phần', N'Đã hoàn thành')),
        UpdatedAt DATETIME DEFAULT GETDATE()
    );
END
GO

-- 3. NẠP DỮ LIỆU MẪU (SEED DATA)

-- Tài khoản người dùng (Mật khẩu test: 123)
IF NOT EXISTS (SELECT 1 FROM Users WHERE Username = 'admin')
BEGIN
    INSERT INTO Users (Username, Password, FullName, Role, Email) VALUES 
    ('admin', '123', N'Quản trị viên Hệ thống', 'admin', 'admin@system.edu.vn'),
    ('gv01', '123', N'ThS. Nguyễn Văn A', 'lecturer', 'nguyenvana@system.edu.vn'),
    ('gv02', '123', N'TS. Lê Thị C', 'lecturer', 'lethic@system.edu.vn'),
    ('sv01', '123', N'Trần Văn B (SV CNTT)', 'student', 'tranvanb@student.edu.vn'),
    ('sv02', '123', N'Phạm Minh D (SV HTTT)', 'student', 'minhd@student.edu.vn');
END
GO

-- Danh mục Môn học
IF NOT EXISTS (SELECT 1 FROM Courses WHERE CourseCode = 'IT001')
BEGIN
    INSERT INTO Courses (CourseCode, CourseName, Credits, Description) VALUES
    ('IT001', N'Lập trình Cơ bản (Python)', 3, N'Nhập môn thuật toán và ngôn ngữ lập trình Python'),
    ('IT002', N'Cơ sở Dữ liệu & Hệ quản trị SQL', 4, N'Thiết kế CSDL quan hệ, tối ưu hóa truy vấn T-SQL'),
    ('IT003', N'Phân tích & Thiết kế Hệ thống', 3, N'Mô hình hóa nghiệp vụ BPMN, UML và kiến trúc MVC'),
    ('IT004', N'Phát triển Ứng dụng Web', 3, N'Thiết kế giao diện Front-end và Backend kết nối CSDL');
END
GO

-- Đợt đăng ký học phần
IF NOT EXISTS (SELECT 1 FROM RegistrationPeriods WHERE SemesterName LIKE N'%2026%')
BEGIN
    INSERT INTO RegistrationPeriods (SemesterName, StartDate, EndDate, Status) VALUES
    (N'Học kỳ 1 (2026 - 2027)', '2026-08-15 00:00:00', '2026-12-30 23:59:59', N'Đang mở');
END
GO

-- Lớp học phần mở trong kỳ
IF NOT EXISTS (SELECT 1 FROM Classes WHERE ClassCode = 'IT001.01')
BEGIN
    DECLARE @PeriodId INT = (SELECT TOP 1 Id FROM RegistrationPeriods WHERE SemesterName LIKE N'%2026%');
    DECLARE @Course1 INT = (SELECT Id FROM Courses WHERE CourseCode = 'IT001');
    DECLARE @Course2 INT = (SELECT Id FROM Courses WHERE CourseCode = 'IT002');
    DECLARE @GV1 INT = (SELECT Id FROM Users WHERE Username = 'gv01');
    DECLARE @GV2 INT = (SELECT Id FROM Users WHERE Username = 'gv02');

    INSERT INTO Classes (ClassCode, CourseId, LecturerId, PeriodId, MaxCapacity, CurrentEnrollment, Room, DayOfWeek, StartPeriod, EndPeriod) VALUES
    ('IT001.01', @Course1, @GV1, @PeriodId, 60, 1, N'A1-203', 2, 1, 3),
    ('IT002.01', @Course2, @GV2, @PeriodId, 50, 1, N'B2-105', 4, 4, 6);
END
GO

-- Dữ liệu đăng ký mẫu & học phí
IF NOT EXISTS (SELECT 1 FROM Enrollments WHERE StudentId = (SELECT Id FROM Users WHERE Username = 'sv01'))
BEGIN
    DECLARE @Student1 INT = (SELECT Id FROM Users WHERE Username = 'sv01');
    DECLARE @Class1 INT = (SELECT Id FROM Classes WHERE ClassCode = 'IT001.01');
    DECLARE @Class2 INT = (SELECT Id FROM Classes WHERE ClassCode = 'IT002.01');
    DECLARE @Period INT = (SELECT TOP 1 Id FROM RegistrationPeriods WHERE SemesterName LIKE N'%2026%');

    INSERT INTO Enrollments (StudentId, ClassId, Status) VALUES
    (@Student1, @Class1, N'Thành công'),
    (@Student1, @Class2, N'Thành công');

    INSERT INTO Tuitions (StudentId, PeriodId, TotalAmount, PaidAmount, Status) VALUES
    (@Student1, @Period, 4200000, 4200000, N'Đã hoàn thành');
END
GO
