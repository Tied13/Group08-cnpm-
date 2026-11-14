/* ==========================================================================
   PROJECT: COURSE REGISTRATION SYSTEM (GROUP 08 - CNPM)
   FILE: init_database.sql
   ARCHITECTURE: 100% Class Diagram Mapping (Users, Students, Lecturers, Admins, 
                 Courses, Classes, Enrollments, Tuitions, RegistrationPeriods, etc.)
   RDBMS: Microsoft SQL Server (T-SQL)
   ========================================================================== */

USE master;
GO

IF EXISTS (SELECT name FROM sys.databases WHERE name = N'CourseRegistrationDB')
BEGIN
    ALTER DATABASE CourseRegistrationDB SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE CourseRegistrationDB;
END
GO

CREATE DATABASE CourseRegistrationDB;
GO

USE CourseRegistrationDB;
GO

/* ==========================================================================
   PART 1: RELATIONAL TABLE CREATION (3NF NORMALIZED SCHEMA)
   ========================================================================== */

-- 1. Users Table (Base User class in Class Diagram)
CREATE TABLE dbo.Users (
    Id INT IDENTITY(1,1) PRIMARY KEY,
    UserCode NVARCHAR(20) NOT NULL UNIQUE,          -- Student ID / Lecturer ID / Admin ID
    Username NVARCHAR(50) NOT NULL UNIQUE,
    PasswordHash NVARCHAR(255) NOT NULL,
    FullName NVARCHAR(100) NOT NULL,
    Email NVARCHAR(100) NOT NULL UNIQUE,
    Phone NVARCHAR(20) NULL,
    Role NVARCHAR(20) NOT NULL 
        CONSTRAINT CK_Users_Role CHECK (Role IN ('Admin', 'Lecturer', 'Student')),
    Status NVARCHAR(20) NOT NULL DEFAULT 'Active' 
        CONSTRAINT CK_Users_Status CHECK (Status IN ('Active', 'Locked')),
    FailedLoginCount INT NOT NULL DEFAULT 0 
        CONSTRAINT CK_Users_FailedLogin CHECK (FailedLoginCount >= 0),
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    UpdatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);
GO

-- 2. Students Table (Inherits from User)
CREATE TABLE dbo.Students (
    UserId INT PRIMARY KEY,
    StudentCode NVARCHAR(20) NOT NULL UNIQUE,
    AdministrativeClass NVARCHAR(30) NOT NULL,      -- Cohort / Homeroom class
    Major NVARCHAR(100) NOT NULL,
    Faculty NVARCHAR(100) NOT NULL DEFAULT 'Faculty of Information Technology',
    EnrollmentYear INT NOT NULL,
    CONSTRAINT FK_Students_Users FOREIGN KEY (UserId) 
        REFERENCES dbo.Users(Id) ON DELETE CASCADE
);
GO

-- 3. Lecturers Table (Inherits from User)
CREATE TABLE dbo.Lecturers (
    UserId INT PRIMARY KEY,
    LecturerCode NVARCHAR(20) NOT NULL UNIQUE,
    Department NVARCHAR(100) NOT NULL,
    AcademicDegree NVARCHAR(50) NOT NULL DEFAULT 'Master',
    CONSTRAINT FK_Lecturers_Users FOREIGN KEY (UserId) 
        REFERENCES dbo.Users(Id) ON DELETE CASCADE
);
GO

-- 4. Admins Table (Inherits from User)
CREATE TABLE dbo.Admins (
    UserId INT PRIMARY KEY,
    AdminCode NVARCHAR(20) NOT NULL UNIQUE,
    OfficeDepartment NVARCHAR(100) NOT NULL DEFAULT 'Academic Affairs Office',
    CONSTRAINT FK_Admins_Users FOREIGN KEY (UserId) 
        REFERENCES dbo.Users(Id) ON DELETE CASCADE
);
GO

-- 5. Semesters Table (Semester class)
CREATE TABLE dbo.Semesters (
    Id INT IDENTITY(1,1) PRIMARY KEY,
    SemesterCode NVARCHAR(20) NOT NULL UNIQUE,      -- e.g., SEM1_2026_2027
    SemesterName NVARCHAR(100) NOT NULL,
    AcademicYear NVARCHAR(20) NOT NULL,
    StartDate DATE NOT NULL,
    EndDate DATE NOT NULL,
    CreditUnitPrice DECIMAL(18,2) NOT NULL DEFAULT 550000.00 
        CONSTRAINT CK_Semesters_UnitPrice CHECK (CreditUnitPrice > 0),
    IsCurrent BIT NOT NULL DEFAULT 0,
    CONSTRAINT CK_Semesters_Dates CHECK (EndDate > StartDate)
);
GO

-- 6. RegistrationPeriods Table (RegistrationPeriod class)
CREATE TABLE dbo.RegistrationPeriods (
    Id INT IDENTITY(1,1) PRIMARY KEY,
    SemesterId INT NOT NULL,
    PeriodName NVARCHAR(150) NOT NULL,
    StartDate DATETIME2 NOT NULL,
    EndDate DATETIME2 NOT NULL,
    MinCredits INT NOT NULL DEFAULT 12 
        CONSTRAINT CK_RegPeriods_MinCredits CHECK (MinCredits >= 0),
    MaxCredits INT NOT NULL DEFAULT 25 
        CONSTRAINT CK_RegPeriods_MaxCredits CHECK (MaxCredits >= 12),
    IsActive BIT NOT NULL DEFAULT 1,
    CONSTRAINT FK_RegistrationPeriods_Semesters FOREIGN KEY (SemesterId) 
        REFERENCES dbo.Semesters(Id) ON DELETE CASCADE,
    CONSTRAINT CK_RegistrationPeriods_Dates CHECK (EndDate > StartDate),
    CONSTRAINT CK_RegistrationPeriods_CreditRange CHECK (MaxCredits >= MinCredits)
);
GO

-- 7. Courses Table (Course class)
CREATE TABLE dbo.Courses (
    Id INT IDENTITY(1,1) PRIMARY KEY,
    CourseCode NVARCHAR(20) NOT NULL UNIQUE,
    CourseName NVARCHAR(150) NOT NULL,
    Credits INT NOT NULL 
        CONSTRAINT CK_Courses_Credits CHECK (Credits BETWEEN 1 AND 10),
    TheoryHours INT NOT NULL DEFAULT 30,
    PracticeHours INT NOT NULL DEFAULT 15,
    Department NVARCHAR(100) NULL,
    PrerequisiteCourseId INT NULL,
    IsActive BIT NOT NULL DEFAULT 1,
    CONSTRAINT FK_Courses_Prerequisite FOREIGN KEY (PrerequisiteCourseId) 
        REFERENCES dbo.Courses(Id) ON DELETE NO ACTION,
    CONSTRAINT CK_Courses_SelfPrerequisite CHECK (PrerequisiteCourseId IS NULL OR PrerequisiteCourseId <> Id)
);
GO

-- 8. CoursePrerequisites Table (Supports multi-prerequisite relationships)
CREATE TABLE dbo.CoursePrerequisites (
    CourseId INT NOT NULL,
    PrerequisiteCourseId INT NOT NULL,
    IsMandatory BIT NOT NULL DEFAULT 1,
    PRIMARY KEY (CourseId, PrerequisiteCourseId),
    CONSTRAINT FK_CoursePrereq_Course FOREIGN KEY (CourseId) 
        REFERENCES dbo.Courses(Id) ON DELETE CASCADE,
    CONSTRAINT FK_CoursePrereq_Prereq FOREIGN KEY (PrerequisiteCourseId) 
        REFERENCES dbo.Courses(Id) ON DELETE NO ACTION,
    CONSTRAINT CK_CoursePrereq_NotSelf CHECK (CourseId <> PrerequisiteCourseId)
);
GO

-- 9. Classrooms Table (Classroom class)
CREATE TABLE dbo.Classrooms (
    Id INT IDENTITY(1,1) PRIMARY KEY,
    RoomCode NVARCHAR(30) NOT NULL UNIQUE,
    Building NVARCHAR(50) NOT NULL,
    Capacity INT NOT NULL DEFAULT 50 
        CONSTRAINT CK_Classrooms_Capacity CHECK (Capacity > 0),
    RoomType NVARCHAR(30) NOT NULL DEFAULT 'Theory'
);
GO

-- 10. TimeSlots Table (TimeSlot class)
CREATE TABLE dbo.TimeSlots (
    Id INT IDENTITY(1,1) PRIMARY KEY,
    SlotNumber INT NOT NULL UNIQUE,                 -- Slot 1, Slot 2, Slot 3, Slot 4
    SlotName NVARCHAR(50) NOT NULL,
    StartTime TIME NOT NULL,
    EndTime TIME NOT NULL,
    CONSTRAINT CK_TimeSlots_Time CHECK (EndTime > StartTime)
);
GO

-- 11. Classes Table (CourseClass class)
CREATE TABLE dbo.Classes (
    Id INT IDENTITY(1,1) PRIMARY KEY,
    ClassCode NVARCHAR(30) NOT NULL UNIQUE,
    CourseId INT NOT NULL,
    SemesterId INT NOT NULL,
    LecturerId INT NULL,
    ClassroomId INT NULL,
    Room NVARCHAR(30) NOT NULL,
    TimeSlotId INT NOT NULL,
    DayOfWeek INT NOT NULL                          -- 2: Monday ... 7: Saturday, 8: Sunday
        CONSTRAINT CK_Classes_DayOfWeek CHECK (DayOfWeek BETWEEN 2 AND 8),
    MinCapacity INT NOT NULL DEFAULT 15,
    MaxCapacity INT NOT NULL DEFAULT 50,
    CurrentEnrollment INT NOT NULL DEFAULT 0,
    Status NVARCHAR(20) NOT NULL DEFAULT 'Open'
        CONSTRAINT CK_Classes_Status CHECK (Status IN ('Open', 'Closed', 'Cancelled')),
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    CONSTRAINT FK_Classes_Courses FOREIGN KEY (CourseId) 
        REFERENCES dbo.Courses(Id) ON DELETE NO ACTION,
    CONSTRAINT FK_Classes_Semesters FOREIGN KEY (SemesterId) 
        REFERENCES dbo.Semesters(Id) ON DELETE NO ACTION,
    CONSTRAINT FK_Classes_Lecturers FOREIGN KEY (LecturerId) 
        REFERENCES dbo.Users(Id) ON DELETE SET NULL,
    CONSTRAINT FK_Classes_Classrooms FOREIGN KEY (ClassroomId) 
        REFERENCES dbo.Classrooms(Id) ON DELETE SET NULL,
    CONSTRAINT FK_Classes_TimeSlots FOREIGN KEY (TimeSlotId) 
        REFERENCES dbo.TimeSlots(Id) ON DELETE NO ACTION,
    CONSTRAINT CK_Classes_Capacity CHECK (CurrentEnrollment >= 0 AND CurrentEnrollment <= MaxCapacity AND MaxCapacity >= MinCapacity)
);
GO

-- 12. Enrollments Table (Enrollment class)
CREATE TABLE dbo.Enrollments (
    Id INT IDENTITY(1,1) PRIMARY KEY,
    StudentId INT NOT NULL,
    ClassId INT NOT NULL,
    EnrolledAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    CancelledAt DATETIME2 NULL,
    Status NVARCHAR(20) NOT NULL DEFAULT 'Enrolled'
        CONSTRAINT CK_Enrollments_Status CHECK (Status IN ('Enrolled', 'Cancelled', 'Completed')),
    FinalGrade DECIMAL(4,2) NULL 
        CONSTRAINT CK_Enrollments_Grade CHECK (FinalGrade IS NULL OR (FinalGrade BETWEEN 0 AND 10)),
    IsPassed BIT NOT NULL DEFAULT 0,
    CONSTRAINT FK_Enrollments_Students FOREIGN KEY (StudentId) 
        REFERENCES dbo.Users(Id) ON DELETE NO ACTION,
    CONSTRAINT FK_Enrollments_Classes FOREIGN KEY (ClassId) 
        REFERENCES dbo.Classes(Id) ON DELETE NO ACTION,
    CONSTRAINT UQ_Enrollments_Student_Class UNIQUE (StudentId, ClassId)
);
GO

-- 13. RegistrationHistory Table (RegistrationRecord class - Audit Log)
CREATE TABLE dbo.RegistrationHistory (
    Id INT IDENTITY(1,1) PRIMARY KEY,
    StudentId INT NOT NULL,
    ClassId INT NOT NULL,
    ActionType NVARCHAR(30) NOT NULL 
        CONSTRAINT CK_RegHistory_Action CHECK (ActionType IN ('Register', 'Drop', 'AdminCancelClass')),
    ActionTime DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    PerformedByUserId INT NULL,
    Note NVARCHAR(255) NULL,
    CONSTRAINT FK_RegHistory_Student FOREIGN KEY (StudentId) REFERENCES dbo.Users(Id),
    CONSTRAINT FK_RegHistory_Class FOREIGN KEY (ClassId) REFERENCES dbo.Classes(Id),
    CONSTRAINT FK_RegHistory_Actor FOREIGN KEY (PerformedByUserId) REFERENCES dbo.Users(Id)
);
GO

-- 14. Tuitions Table (TuitionInvoice class)
CREATE TABLE dbo.Tuitions (
    Id INT IDENTITY(1,1) PRIMARY KEY,
    StudentId INT NOT NULL,
    SemesterId INT NOT NULL,
    TotalCredits INT NOT NULL DEFAULT 0 
        CONSTRAINT CK_Tuitions_Credits CHECK (TotalCredits >= 0),
    UnitPrice DECIMAL(18,2) NOT NULL DEFAULT 550000.00,
    TotalAmount AS (CAST(TotalCredits * UnitPrice AS DECIMAL(18,2))) PERSISTED,
    PaidAmount DECIMAL(18,2) NOT NULL DEFAULT 0.00,
    PaymentStatus NVARCHAR(20) NOT NULL DEFAULT 'Unpaid'
        CONSTRAINT CK_Tuitions_Status CHECK (PaymentStatus IN ('Unpaid', 'Partial', 'Paid')),
    LastCalculatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    CONSTRAINT FK_Tuitions_Students FOREIGN KEY (StudentId) 
        REFERENCES dbo.Users(Id) ON DELETE NO ACTION,
    CONSTRAINT FK_Tuitions_Semesters FOREIGN KEY (SemesterId) 
        REFERENCES dbo.Semesters(Id) ON DELETE NO ACTION,
    CONSTRAINT UQ_Tuitions_Student_Semester UNIQUE (StudentId, SemesterId)
);
GO

/* ==========================================================================
   PART 2: NON-CLUSTERED PERFORMANCE INDEXES
   ========================================================================== */

CREATE NONCLUSTERED INDEX IX_Users_Username_Status ON dbo.Users(Username, Status) INCLUDE (Role, PasswordHash, FailedLoginCount);
CREATE NONCLUSTERED INDEX IX_Classes_Schedule ON dbo.Classes(SemesterId, DayOfWeek, TimeSlotId, Status) INCLUDE (CourseId, LecturerId, Room, CurrentEnrollment, MaxCapacity);
CREATE NONCLUSTERED INDEX IX_Enrollments_Student_Status ON dbo.Enrollments(StudentId, Status) INCLUDE (ClassId, IsPassed);
CREATE NONCLUSTERED INDEX IX_Enrollments_Class_Status ON dbo.Enrollments(ClassId, Status) INCLUDE (StudentId);
GO

/* ==========================================================================
   PART 3: STORED PROCEDURES & BUSINESS LOGIC
   ========================================================================== */

-- 3.1. Recalculate Tuition Invoice automatically per student per semester
CREATE OR ALTER PROCEDURE dbo.sp_RecalculateStudentTuition
    @StudentId INT,
    @SemesterId INT
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @TotalCredits INT = 0;
    DECLARE @UnitPrice DECIMAL(18,2) = 550000.00;

    SELECT @UnitPrice = CreditUnitPrice 
    FROM dbo.Semesters 
    WHERE Id = @SemesterId;

    SELECT @TotalCredits = ISNULL(SUM(co.Credits), 0)
    FROM dbo.Enrollments e
    INNER JOIN dbo.Classes cl ON e.ClassId = cl.Id
    INNER JOIN dbo.Courses co ON cl.CourseId = co.Id
    WHERE e.StudentId = @StudentId
      AND cl.SemesterId = @SemesterId
      AND e.Status = 'Enrolled'
      AND cl.Status <> 'Cancelled';

    IF EXISTS (SELECT 1 FROM dbo.Tuitions WHERE StudentId = @StudentId AND SemesterId = @SemesterId)
    BEGIN
        UPDATE dbo.Tuitions
        SET TotalCredits = @TotalCredits,
            UnitPrice = @UnitPrice,
            LastCalculatedAt = SYSDATETIME()
        WHERE StudentId = @StudentId AND SemesterId = @SemesterId;
    END
    ELSE
    BEGIN
        INSERT INTO dbo.Tuitions (StudentId, SemesterId, TotalCredits, UnitPrice)
        VALUES (@StudentId, @SemesterId, @TotalCredits, @UnitPrice);
    END
END;
GO

-- 3.2. Register Course Class (Evaluates 4 core business constraints)
CREATE OR ALTER PROCEDURE dbo.sp_RegisterCourse
    @StudentId INT,
    @ClassId INT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    BEGIN TRY
        BEGIN TRANSACTION;

        DECLARE @CourseId INT, @SemesterId INT, @DayOfWeek INT, @TimeSlotId INT;
        DECLARE @CurrentEnrollment INT, @MaxCapacity INT, @ClassStatus NVARCHAR(20);
        DECLARE @NewCourseCredits INT, @PrerequisiteCourseId INT;
        DECLARE @CurrentTotalCredits INT, @MaxAllowedCredits INT = 25;

        -- Row-level locking (UPDLOCK) prevents race conditions during concurrent registrations
        SELECT 
            @CourseId = cl.CourseId,
            @SemesterId = cl.SemesterId,
            @DayOfWeek = cl.DayOfWeek,
            @TimeSlotId = cl.TimeSlotId,
            @CurrentEnrollment = cl.CurrentEnrollment,
            @MaxCapacity = cl.MaxCapacity,
            @ClassStatus = cl.Status,
            @NewCourseCredits = co.Credits,
            @PrerequisiteCourseId = co.PrerequisiteCourseId
        FROM dbo.Classes cl WITH (UPDLOCK, ROWLOCK)
        INNER JOIN dbo.Courses co ON cl.CourseId = co.Id
        WHERE cl.Id = @ClassId;

        IF @CourseId IS NULL
            THROW 50001, N'Class not found.', 1;

        IF @ClassStatus <> 'Open'
            THROW 50002, N'Class is closed or has been cancelled.', 1;

        -- Check registration window status
        IF NOT EXISTS (
            SELECT 1 FROM dbo.RegistrationPeriods 
            WHERE SemesterId = @SemesterId AND IsActive = 1 AND SYSDATETIME() BETWEEN StartDate AND EndDate
        )
            THROW 50003, N'Course registration period is currently closed.', 1;

        -- Check if student already registered another section of this course in the current semester
        IF EXISTS (
            SELECT 1 FROM dbo.Enrollments e
            INNER JOIN dbo.Classes cl ON e.ClassId = cl.Id
            WHERE e.StudentId = @StudentId AND cl.SemesterId = @SemesterId 
              AND cl.CourseId = @CourseId AND e.Status = 'Enrolled'
        )
            THROW 50004, N'Student is already enrolled in another section of this course for this semester.', 1;

        -- Constraint 1: Class capacity check
        IF @CurrentEnrollment >= @MaxCapacity
            THROW 50005, N'Registration failed: Class capacity is full.', 1;

        -- Constraint 2: Prerequisite check
        IF @PrerequisiteCourseId IS NOT NULL
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM dbo.Enrollments e
                INNER JOIN dbo.Classes cl ON e.ClassId = cl.Id
                WHERE e.StudentId = @StudentId 
                  AND cl.CourseId = @PrerequisiteCourseId 
                  AND e.Status = 'Completed' 
                  AND e.IsPassed = 1
            )
                THROW 50006, N'Registration failed: Prerequisite course not yet completed.', 1;
        END

        -- Constraint 3: Timetable conflict check (Day & TimeSlot)
        IF EXISTS (
            SELECT 1 FROM dbo.Enrollments e
            INNER JOIN dbo.Classes cl ON e.ClassId = cl.Id
            WHERE e.StudentId = @StudentId
              AND cl.SemesterId = @SemesterId
              AND e.Status = 'Enrolled'
              AND cl.DayOfWeek = @DayOfWeek
              AND cl.TimeSlotId = @TimeSlotId
        )
            THROW 50007, N'Registration failed: Schedule conflict with an existing enrolled class.', 1;

        -- Constraint 4: Maximum credits check (<= 25 credits)
        SELECT @CurrentTotalCredits = ISNULL(SUM(co.Credits), 0)
        FROM dbo.Enrollments e
        INNER JOIN dbo.Classes cl ON e.ClassId = cl.Id
        INNER JOIN dbo.Courses co ON cl.CourseId = co.Id
        WHERE e.StudentId = @StudentId
          AND cl.SemesterId = @SemesterId
          AND e.Status = 'Enrolled';

        IF (@CurrentTotalCredits + @NewCourseCredits) > @MaxAllowedCredits
            THROW 50008, N'Registration failed: Total enrolled credits exceed maximum limit (25 credits).', 1;

        -- Upsert enrollment record
        IF EXISTS (SELECT 1 FROM dbo.Enrollments WHERE StudentId = @StudentId AND ClassId = @ClassId)
        BEGIN
            UPDATE dbo.Enrollments
            SET Status = 'Enrolled',
                EnrolledAt = SYSDATETIME(),
                CancelledAt = NULL
            WHERE StudentId = @StudentId AND ClassId = @ClassId;
        END
        ELSE
        BEGIN
            INSERT INTO dbo.Enrollments (StudentId, ClassId, Status)
            VALUES (@StudentId, @ClassId, 'Enrolled');
        END

        -- Increment class enrollment
        UPDATE dbo.Classes
        SET CurrentEnrollment = CurrentEnrollment + 1,
            Status = CASE WHEN CurrentEnrollment + 1 >= MaxCapacity THEN 'Closed' ELSE Status END
        WHERE Id = @ClassId;

        -- Audit log
        INSERT INTO dbo.RegistrationHistory (StudentId, ClassId, ActionType, PerformedByUserId, Note)
        VALUES (@StudentId, @ClassId, 'Register', @StudentId, N'Course enrolled successfully');

        -- Recalculate tuition
        EXEC dbo.sp_RecalculateStudentTuition @StudentId = @StudentId, @SemesterId = @SemesterId;

        COMMIT TRANSACTION;
        SELECT 1 AS IsSuccess, N'Course registered successfully.' AS Message;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        SELECT 0 AS IsSuccess, ERROR_MESSAGE() AS Message;
    END CATCH
END;
GO

-- 3.3. Drop Enrolled Course (Restores seat availability & recalculates tuition)
CREATE OR ALTER PROCEDURE dbo.sp_DropCourse
    @StudentId INT,
    @ClassId INT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    BEGIN TRY
        BEGIN TRANSACTION;

        DECLARE @SemesterId INT;
        SELECT @SemesterId = SemesterId FROM dbo.Classes WITH (UPDLOCK) WHERE Id = @ClassId;

        IF @SemesterId IS NULL
            THROW 50001, N'Class not found.', 1;

        -- Check registration window status
        IF NOT EXISTS (
            SELECT 1 FROM dbo.RegistrationPeriods 
            WHERE SemesterId = @SemesterId AND IsActive = 1 AND SYSDATETIME() BETWEEN StartDate AND EndDate
        )
            THROW 50011, N'Course drop period is currently closed.', 1;

        IF NOT EXISTS (
            SELECT 1 FROM dbo.Enrollments 
            WHERE StudentId = @StudentId AND ClassId = @ClassId AND Status = 'Enrolled'
        )
            THROW 50010, N'Enrollment record not found or already cancelled.', 1;

        UPDATE dbo.Enrollments
        SET Status = 'Cancelled',
            CancelledAt = SYSDATETIME()
        WHERE StudentId = @StudentId AND ClassId = @ClassId;

        UPDATE dbo.Classes
        SET CurrentEnrollment = CASE WHEN CurrentEnrollment > 0 THEN CurrentEnrollment - 1 ELSE 0 END,
            Status = CASE WHEN Status = 'Closed' THEN 'Open' ELSE Status END
        WHERE Id = @ClassId;

        INSERT INTO dbo.RegistrationHistory (StudentId, ClassId, ActionType, PerformedByUserId, Note)
        VALUES (@StudentId, @ClassId, 'Drop', @StudentId, N'Student dropped course class');

        EXEC dbo.sp_RecalculateStudentTuition @StudentId = @StudentId, @SemesterId = @SemesterId;

        COMMIT TRANSACTION;
        SELECT 1 AS IsSuccess, N'Course dropped successfully.' AS Message;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        SELECT 0 AS IsSuccess, ERROR_MESSAGE() AS Message;
    END CATCH
END;
GO

-- 3.4. Admin Cancel Under-Enrolled Class (< 15 students)
CREATE OR ALTER PROCEDURE dbo.sp_AdminCancelUnderEnrolledClass
    @ClassId INT,
    @AdminUserId INT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    BEGIN TRY
        BEGIN TRANSACTION;

        DECLARE @CurrentEnrollment INT, @MinCapacity INT, @SemesterId INT, @Status NVARCHAR(20);

        SELECT 
            @CurrentEnrollment = CurrentEnrollment,
            @MinCapacity = MinCapacity,
            @SemesterId = SemesterId,
            @Status = Status
        FROM dbo.Classes WITH (UPDLOCK)
        WHERE Id = @ClassId;

        IF @Status IS NULL
            THROW 50020, N'Course class not found.', 1;

        IF @Status = 'Cancelled'
            THROW 50021, N'Class is already cancelled.', 1;

        IF @CurrentEnrollment >= @MinCapacity
            THROW 50022, N'Cannot cancel: Class meets the minimum enrollment threshold (>= 15 students).', 1;

        DECLARE @AffectedStudents TABLE (StudentId INT);
        INSERT INTO @AffectedStudents (StudentId)
        SELECT StudentId FROM dbo.Enrollments WHERE ClassId = @ClassId AND Status = 'Enrolled';

        -- Mark class cancelled
        UPDATE dbo.Classes
        SET Status = 'Cancelled',
            CurrentEnrollment = 0
        WHERE Id = @ClassId;

        -- Cancel student enrollments
        UPDATE dbo.Enrollments
        SET Status = 'Cancelled',
            CancelledAt = SYSDATETIME()
        WHERE ClassId = @ClassId AND Status = 'Enrolled';

        INSERT INTO dbo.RegistrationHistory (StudentId, ClassId, ActionType, PerformedByUserId, Note)
        SELECT StudentId, @ClassId, 'AdminCancelClass', @AdminUserId, N'Cancelled due to under-enrollment (< 15 students)'
        FROM @AffectedStudents;

        -- Recalculate tuition for all affected students
        DECLARE @StuId INT;
        DECLARE cur_Students CURSOR LOCAL FAST_FORWARD FOR SELECT StudentId FROM @AffectedStudents;
        OPEN cur_Students;
        FETCH NEXT FROM cur_Students INTO @StuId;
        WHILE @@FETCH_STATUS = 0
        BEGIN
            EXEC dbo.sp_RecalculateStudentTuition @StudentId = @StuId, @SemesterId = @SemesterId;
            FETCH NEXT FROM cur_Students INTO @StuId;
        END
        CLOSE cur_Students;
        DEALLOCATE cur_Students;

        COMMIT TRANSACTION;
        SELECT 1 AS IsSuccess, N'Class cancelled and affected enrollments updated.' AS Message;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        SELECT 0 AS IsSuccess, ERROR_MESSAGE() AS Message;
    END CATCH
END;
GO

/* ==========================================================================
   PART 4: SEED DATA (AUTHENTIC & COMPREHENSIVE UNIVERSITY DATASET)
   Default password for all initial accounts: 123456
   ========================================================================== */

DECLARE @DefaultPasswordHash NVARCHAR(255) = N'scrypt:32768:8:1';

-- 4.1. Insert System Users (Admins, Lecturers, Students)
INSERT INTO dbo.Users (UserCode, Username, PasswordHash, FullName, Email, Phone, Role, Status, FailedLoginCount)
VALUES
-- Administrators (Id: 1, 2)
(N'ADM001', N'admin',         @DefaultPasswordHash, N'Nguyễn Văn Quản',      N'admin@uth.edu.vn',    N'0901000001', N'Admin',    N'Active', 0),
(N'ADM002', N'admin_daotao',  @DefaultPasswordHash, N'Trần Thị Bích Loan',   N'loan.ttb@uth.edu.vn', N'0901000002', N'Admin',    N'Active', 0),

-- Lecturers (Id: 3 to 10)
(N'GV001',  N'gv_nam',        @DefaultPasswordHash, N'TS. Lê Hoàng Nam',     N'nam.lh@uth.edu.vn',   N'0902000001', N'Lecturer', N'Active', 0),
(N'GV002',  N'gv_mai',        @DefaultPasswordHash, N'ThS. Trần Phương Mai', N'mai.ttp@uth.edu.vn',  N'0902000002', N'Lecturer', N'Active', 0),
(N'GV003',  N'gv_hieu',       @DefaultPasswordHash, N'PGS.TS. Nguyễn Trọng Hiếu', N'hieu.nt@uth.edu.vn', N'0902000003', N'Lecturer', N'Active', 0),
(N'GV004',  N'gv_thanh',      @DefaultPasswordHash, N'ThS. Phạm Bá Thành',   N'thanh.pb@uth.edu.vn', N'0902000004', N'Lecturer', N'Active', 0),
(N'GV005',  N'gv_lan',        @DefaultPasswordHash, N'TS. Vũ Ngọc Lan',      N'lan.vn@uth.edu.vn',   N'0902000005', N'Lecturer', N'Active', 0),
(N'GV006',  N'gv_hung',       @DefaultPasswordHash, N'ThS. Đỗ Quang Hùng',   N'hung.dq@uth.edu.vn',  N'0902000006', N'Lecturer', N'Active', 0),
(N'GV007',  N'gv_dung',       @DefaultPasswordHash, N'TS. Hoàng Anh Dũng',   N'dung.ha@uth.edu.vn',  N'0902000007', N'Lecturer', N'Active', 0),
(N'GV008',  N'gv_huong',      @DefaultPasswordHash, N'ThS. Ngô Thu Hương',   N'huong.nt@uth.edu.vn', N'0902000008', N'Lecturer', N'Active', 0),

-- Students (Id: 11 to 30)
(N'SV001',  N'sv_an',         @DefaultPasswordHash, N'Nguyễn Văn An',        N'an.sv@uth.edu.vn',    N'0903000001', N'Student',  N'Active', 0),
(N'SV002',  N'sv_binh',       @DefaultPasswordHash, N'Trần Hải Bình',        N'binh.sv@uth.edu.vn',  N'0903000002', N'Student',  N'Active', 0),
(N'SV003',  N'sv_chau',       @DefaultPasswordHash, N'Lê Minh Châu',         N'chau.sv@uth.edu.vn',  N'0903000003', N'Student',  N'Active', 0),
(N'SV004',  N'sv_dung',       @DefaultPasswordHash, N'Phạm Hoàng Dũng',      N'dung.sv@uth.edu.vn',  N'0903000004', N'Student',  N'Active', 0),
(N'SV005',  N'sv_giang',      @DefaultPasswordHash, N'Vũ Hương Giang',       N'giang.sv@uth.edu.vn', N'0903000005', N'Student',  N'Active', 0),
(N'SV006',  N'sv_ha',         @DefaultPasswordHash, N'Đặng Thu Hà',          N'ha.sv@uth.edu.vn',    N'0903000006', N'Student',  N'Active', 0),
(N'SV007',  N'sv_khoa',       @DefaultPasswordHash, N'Bùi Đăng Khoa',        N'khoa.sv@uth.edu.vn',  N'0903000007', N'Student',  N'Active', 0),
(N'SV008',  N'sv_linh',       @DefaultPasswordHash, N'Hoàng Mỹ Linh',        N'linh.sv@uth.edu.vn',  N'0903000008', N'Student',  N'Active', 0),
(N'SV009',  N'sv_minh',       @DefaultPasswordHash, N'Ngô Quang Minh',       N'minh.sv@uth.edu.vn',  N'0903000009', N'Student',  N'Active', 0),
(N'SV010',  N'sv_nga',        @DefaultPasswordHash, N'Dương Thúy Nga',       N'nga.sv@uth.edu.vn',   N'0903000010', N'Student',  N'Active', 0),
(N'SV011',  N'sv_phong',      @DefaultPasswordHash, N'Trịnh Quốc Phong',     N'phong.sv@uth.edu.vn', N'0903000011', N'Student',  N'Active', 0),
(N'SV012',  N'sv_quan',       @DefaultPasswordHash, N'Đỗ Hồng Quân',         N'quan.sv@uth.edu.vn',  N'0903000012', N'Student',  N'Active', 0),
(N'SV013',  N'sv_son',        @DefaultPasswordHash, N'Lý Thái Sơn',          N'son.sv@uth.edu.vn',   N'0903000013', N'Student',  N'Active', 0),
(N'SV014',  N'sv_trang',      @DefaultPasswordHash, N'Mai Thùy Trang',       N'trang.sv@uth.edu.vn', N'0903000014', N'Student',  N'Active', 0),
(N'SV015',  N'sv_tuan',       @DefaultPasswordHash, N'Phan Anh Tuấn',        N'tuan.sv@uth.edu.vn',  N'0903000015', N'Student',  N'Active', 0),
(N'SV016',  N'sv_uyen',       @DefaultPasswordHash, N'Lương Phương Uyên',    N'uyen.sv@uth.edu.vn',  N'0903000016', N'Student',  N'Active', 0),
(N'SV017',  N'sv_viet',       @DefaultPasswordHash, N'Nguyễn Quốc Việt',     N'viet.sv@uth.edu.vn',  N'0903000017', N'Student',  N'Active', 0),
(N'SV018',  N'sv_xuan',       @DefaultPasswordHash, N'Tạ Thanh Xuân',        N'xuan.sv@uth.edu.vn',  N'0903000018', N'Student',  N'Active', 0),
(N'SV019',  N'sv_yen',        @DefaultPasswordHash, N'Đoàn Hải Yến',         N'yen.sv@uth.edu.vn',   N'0903000019', N'Student',  N'Active', 0),
(N'SV020',  N'sv_loc',        @DefaultPasswordHash, N'Cao Vĩnh Lộc',         N'loc.sv@uth.edu.vn',   N'0903000020', N'Student',  N'Active', 0);

-- 4.2. Insert Sub-Entities (Admins, Lecturers, Students)
INSERT INTO dbo.Admins (UserId, AdminCode, OfficeDepartment) VALUES 
(1, N'ADM001', N'Academic Affairs Office'),
(2, N'ADM002', N'Office of Student Affairs');

INSERT INTO dbo.Lecturers (UserId, LecturerCode, Department, AcademicDegree) VALUES 
(3,  N'GV001', N'Management Information Systems', N'Doctorate'),
(4,  N'GV002', N'Software Engineering',           N'Master'),
(5,  N'GV003', N'Computer Science',               N'Doctorate'),
(6,  N'GV004', N'Computer Networks & Security',   N'Master'),
(7,  N'GV005', N'Artificial Intelligence',        N'Doctorate'),
(8,  N'GV006', N'Software Engineering',           N'Master'),
(9,  N'GV007', N'Fundamental Informatics',        N'Doctorate'),
(10, N'GV008', N'Management Information Systems', N'Master');

INSERT INTO dbo.Students (UserId, StudentCode, AdministrativeClass, Major, Faculty, EnrollmentYear) VALUES
(11, N'SV001', N'HT2301', N'Management Information Systems', N'Faculty of Information Technology', 2023),
(12, N'SV002', N'HT2301', N'Management Information Systems', N'Faculty of Information Technology', 2023),
(13, N'SV003', N'CN2301', N'Information Technology',         N'Faculty of Information Technology', 2023),
(14, N'SV004', N'CN2301', N'Information Technology',         N'Faculty of Information Technology', 2023),
(15, N'SV005', N'PM2301', N'Software Engineering',           N'Faculty of Information Technology', 2023),
(16, N'SV006', N'PM2301', N'Software Engineering',           N'Faculty of Information Technology', 2023),
(17, N'SV007', N'PM2301', N'Software Engineering',           N'Faculty of Information Technology', 2023),
(18, N'SV008', N'CN2302', N'Information Technology',         N'Faculty of Information Technology', 2023),
(19, N'SV009', N'CN2302', N'Information Technology',         N'Faculty of Information Technology', 2023),
(20, N'SV010', N'HT2301', N'Management Information Systems', N'Faculty of Information Technology', 2023),
(21, N'SV011', N'KT2301', N'Computer Science',               N'Faculty of Information Technology', 2023),
(22, N'SV012', N'KT2301', N'Computer Science',               N'Faculty of Information Technology', 2023),
(23, N'SV013', N'CN2301', N'Information Technology',         N'Faculty of Information Technology', 2023),
(24, N'SV014', N'CN2302', N'Information Technology',         N'Faculty of Information Technology', 2023),
(25, N'SV015', N'PM2301', N'Software Engineering',           N'Faculty of Information Technology', 2023),
(26, N'SV016', N'HT2301', N'Management Information Systems', N'Faculty of Information Technology', 2023),
(27, N'SV017', N'CN2301', N'Information Technology',         N'Faculty of Information Technology', 2023),
(28, N'SV018', N'CN2302', N'Information Technology',         N'Faculty of Information Technology', 2023),
(29, N'SV019', N'PM2301', N'Software Engineering',           N'Faculty of Information Technology', 2023),
(30, N'SV020', N'KT2301', N'Computer Science',               N'Faculty of Information Technology', 2023);

-- 4.3. Insert Semesters & Registration Periods
INSERT INTO dbo.Semesters (SemesterCode, SemesterName, AcademicYear, StartDate, EndDate, CreditUnitPrice, IsCurrent)
VALUES 
(N'SEM2_2025_2026', N'Học kỳ 2 (2025 - 2026)', N'2025-2026', '2026-01-15', '2026-06-15', 520000.00, 0),
(N'SEM1_2026_2027', N'Học kỳ 1 (2026 - 2027)', N'2026-2027', '2026-09-01', '2027-01-31', 550000.00, 1);

INSERT INTO dbo.RegistrationPeriods (SemesterId, PeriodName, StartDate, EndDate, MinCredits, MaxCredits, IsActive)
VALUES 
(2, N'Đợt Đăng ký Học phần Chính thức - Học kỳ 1 (2026 - 2027)', '2026-09-01 00:00:00', '2027-01-31 23:59:59', 12, 25, 1);

-- 4.4. Insert Courses Catalog
INSERT INTO dbo.Courses (CourseCode, CourseName, Credits, TheoryHours, PracticeHours, Department, PrerequisiteCourseId)
VALUES
(N'IT101', N'Nhập môn Lập trình',                 3, 30, 15, N'Computer Science',               NULL),
(N'IT102', N'Cấu trúc Dữ liệu & Giải thuật',       4, 45, 15, N'Computer Science',               1),
(N'IT103', N'Lập trình Hướng đối tượng',          3, 30, 15, N'Computer Science',               1),
(N'IS201', N'Cơ sở Dữ liệu',                       3, 30, 15, N'Information Systems',            NULL),
(N'IS202', N'Hệ Quản trị Cơ sở Dữ liệu',          3, 30, 15, N'Information Systems',            4),
(N'IS301', N'Phân tích & Thiết kế Hệ thống',       3, 30, 15, N'Information Systems',            4),
(N'SE201', N'Nhập môn Kỹ thuật Phần mềm',          3, 30, 15, N'Software Engineering',           3),
(N'SE301', N'Kiến trúc & Thiết kế Phần mềm',       3, 30, 15, N'Software Engineering',           7),
(N'SE302', N'Kiểm thử & Đảm bảo Chất lượng PM',    3, 30, 15, N'Software Engineering',           7),
(N'NW101', N'Mạng Máy tính Căn bản',              3, 30, 15, N'Computer Networks & Security',   NULL),
(N'NW201', N'An toàn & Bảo mật Thông tin',        3, 30, 15, N'Computer Networks & Security',   10),
(N'AI201', N'Nhập môn Trí tuệ Nhân tạo',           3, 30, 15, N'Artificial Intelligence',        2),
(N'AI301', N'Học máy & Khai phá Dữ liệu',          4, 45, 15, N'Artificial Intelligence',        12),
(N'MA101', N'Toán Rời rạc & Lý thuyết Đồ thị',    3, 30, 15, N'Fundamental Sciences',          NULL),
(N'MA102', N'Xác suất Thống kê Ứng dụng',         3, 30, 15, N'Fundamental Sciences',          NULL);

-- Insert Course Prerequisites (Supports multi-prerequisite relationships)
INSERT INTO dbo.CoursePrerequisites (CourseId, PrerequisiteCourseId, IsMandatory)
VALUES
(2, 1, 1),   -- IT102 -> IT101
(3, 1, 1),   -- IT103 -> IT101
(5, 4, 1),   -- IS202 -> IS201
(6, 4, 1),   -- IS301 -> IS201
(7, 3, 1),   -- SE201 -> IT103
(8, 7, 1),   -- SE301 -> SE201
(9, 7, 1),   -- SE302 -> SE201
(11, 10, 1), -- NW201 -> NW101
(12, 2, 1),  -- AI201 -> IT102
(13, 12, 1); -- AI301 -> AI201

-- 4.5. Insert Classrooms & TimeSlots
INSERT INTO dbo.Classrooms (RoomCode, Building, Capacity, RoomType)
VALUES 
(N'A101', N'Tòa nhà A', 50, N'Theory'),
(N'A102', N'Tòa nhà A', 50, N'Theory'),
(N'A201', N'Tòa nhà A', 60, N'Theory'),
(N'B201', N'Tòa nhà B', 45, N'Theory'),
(N'B202', N'Tòa nhà B', 45, N'Theory'),
(N'B301', N'Tòa nhà B', 40, N'Theory'),
(N'C101', N'Tòa nhà C', 35, N'Computer Lab'),
(N'C102', N'Tòa nhà C', 35, N'Network Lab');

INSERT INTO dbo.TimeSlots (SlotNumber, SlotName, StartTime, EndTime)
VALUES
(1, N'Ca 1 (07:00 - 09:30)', '07:00:00', '09:30:00'),
(2, N'Ca 2 (09:45 - 12:15)', '09:45:00', '12:15:00'),
(3, N'Ca 3 (13:00 - 15:30)', '13:00:00', '15:30:00'),
(4, N'Ca 4 (15:45 - 18:15)', '15:45:00', '18:15:00');

-- 4.6. Insert Classes (CourseClass sections)
INSERT INTO dbo.Classes (ClassCode, CourseId, SemesterId, LecturerId, ClassroomId, Room, TimeSlotId, DayOfWeek, MinCapacity, MaxCapacity, CurrentEnrollment, Status)
VALUES
-- Mon học kỳ 1 (2026 - 2027)
(N'IT101_01', 1,  2, 3,  1, N'A101', 1, 2, 15, 50, 0, 'Open'),
(N'IT101_02', 1,  2, 5,  2, N'A102', 3, 3, 15, 50, 0, 'Open'),
(N'IT102_01', 2,  2, 5,  3, N'A201', 2, 4, 15, 45, 0, 'Open'),
(N'IT102_02', 2,  2, 7,  4, N'B201', 4, 5, 15, 45, 0, 'Open'),
(N'IT103_01', 3,  2, 4,  4, N'B201', 1, 3, 15, 45, 0, 'Open'),
(N'IT103_02', 3,  2, 8,  5, N'B202', 3, 5, 15, 45, 0, 'Open'),
(N'IS201_01', 4,  2, 3,  1, N'A101', 2, 5, 15, 50, 0, 'Open'),
(N'IS201_02', 4,  2, 10, 4, N'B201', 1, 6, 15, 50, 0, 'Open'),
(N'IS202_01', 5,  2, 10, 7, N'C101', 3, 2, 15, 35, 0, 'Open'),
(N'IS301_01', 6,  2, 3,  5, N'B202', 2, 3, 15, 45, 0, 'Open'),
(N'IS301_02', 6,  2, 10, 2, N'A102', 4, 4, 15, 45, 0, 'Open'),
(N'SE201_01', 7,  2, 4,  2, N'A102', 1, 4, 15, 50, 0, 'Open'),
(N'SE201_02', 7,  2, 8,  5, N'B202', 2, 6, 15, 45, 0, 'Open'),
(N'SE301_01', 8,  2, 4,  6, N'B301', 2, 6, 15, 40, 0, 'Open'),
(N'SE302_01', 9,  2, 8,  7, N'C101', 4, 4, 15, 35, 0, 'Open'),
(N'NW101_01', 10, 2, 6,  4, N'B201', 3, 3, 15, 45, 0, 'Open'),
(N'NW101_02', 10, 2, 6,  3, N'A201', 1, 7, 15, 45, 0, 'Open'),
(N'NW201_01', 11, 2, 6,  8, N'C102', 2, 5, 15, 35, 0, 'Open'),
(N'AI201_01', 12, 2, 7,  3, N'A201', 1, 5, 15, 45, 0, 'Open'),
(N'AI301_01', 13, 2, 7,  7, N'C101', 2, 2, 15, 35, 0, 'Open'),
(N'MA101_01', 14, 2, 9,  1, N'A101', 4, 2, 15, 50, 0, 'Open'),
(N'MA102_01', 15, 2, 9,  2, N'A102', 3, 6, 15, 50, 0, 'Open');

-- 4.7. Seed Historical Completions (Học kỳ 2 2025-2026 - thỏa mãn điều kiện tiên quyết)
-- SV001 - SV020 (Id 11 - 30) đã hoàn thành môn IT101 và IS201 từ học kỳ trước
INSERT INTO dbo.Enrollments (StudentId, ClassId, EnrolledAt, Status, FinalGrade, IsPassed)
VALUES
(11, 1, '2026-01-20 08:00:00', 'Completed', 8.5, 1),
(12, 1, '2026-01-20 08:00:00', 'Completed', 7.5, 1),
(13, 1, '2026-01-20 08:00:00', 'Completed', 9.0, 1),
(14, 1, '2026-01-20 08:00:00', 'Completed', 8.0, 1),
(15, 1, '2026-01-20 08:00:00', 'Completed', 8.2, 1),
(16, 1, '2026-01-20 08:00:00', 'Completed', 7.8, 1),
(17, 1, '2026-01-20 08:00:00', 'Completed', 8.5, 1),
(18, 1, '2026-01-20 08:00:00', 'Completed', 8.0, 1),
(19, 1, '2026-01-20 08:00:00', 'Completed', 7.0, 1),
(20, 1, '2026-01-20 08:00:00', 'Completed', 9.2, 1),
(21, 1, '2026-01-20 08:00:00', 'Completed', 8.4, 1),
(22, 1, '2026-01-20 08:00:00', 'Completed', 8.0, 1),
(23, 1, '2026-01-20 08:00:00', 'Completed', 7.5, 1),
(24, 1, '2026-01-20 08:00:00', 'Completed', 8.8, 1),
(25, 1, '2026-01-20 08:00:00', 'Completed', 7.9, 1);

-- 4.8. Seed Active Registrations for Current Semester (SemesterId = 2)
-- Đăng ký một số lớp học phần mẫu cho sinh viên
INSERT INTO dbo.Enrollments (StudentId, ClassId, EnrolledAt, Status, FinalGrade, IsPassed)
VALUES
-- Class 3 (IT102_01): 16 sinh viên (>= 15 SV: Đạt chuẩn)
(11, 3, '2026-09-02 08:15:00', 'Enrolled', NULL, 0),
(12, 3, '2026-09-02 08:20:00', 'Enrolled', NULL, 0),
(13, 3, '2026-09-02 08:25:00', 'Enrolled', NULL, 0),
(14, 3, '2026-09-02 08:30:00', 'Enrolled', NULL, 0),
(15, 3, '2026-09-02 08:35:00', 'Enrolled', NULL, 0),
(16, 3, '2026-09-02 08:40:00', 'Enrolled', NULL, 0),
(17, 3, '2026-09-02 08:45:00', 'Enrolled', NULL, 0),
(18, 3, '2026-09-02 08:50:00', 'Enrolled', NULL, 0),
(19, 3, '2026-09-02 08:55:00', 'Enrolled', NULL, 0),
(20, 3, '2026-09-02 09:00:00', 'Enrolled', NULL, 0),
(21, 3, '2026-09-02 09:05:00', 'Enrolled', NULL, 0),
(22, 3, '2026-09-02 09:10:00', 'Enrolled', NULL, 0),
(23, 3, '2026-09-02 09:15:00', 'Enrolled', NULL, 0),
(24, 3, '2026-09-02 09:20:00', 'Enrolled', NULL, 0),
(25, 3, '2026-09-02 09:25:00', 'Enrolled', NULL, 0),
(26, 3, '2026-09-02 09:30:00', 'Enrolled', NULL, 0),

-- Class 5 (IT103_01): 15 sinh viên (>= 15 SV: Đạt chuẩn)
(11, 5, '2026-09-02 09:35:00', 'Enrolled', NULL, 0),
(12, 5, '2026-09-02 09:40:00', 'Enrolled', NULL, 0),
(13, 5, '2026-09-02 09:45:00', 'Enrolled', NULL, 0),
(14, 5, '2026-09-02 09:50:00', 'Enrolled', NULL, 0),
(15, 5, '2026-09-02 09:55:00', 'Enrolled', NULL, 0),
(16, 5, '2026-09-02 10:00:00', 'Enrolled', NULL, 0),
(17, 5, '2026-09-02 10:05:00', 'Enrolled', NULL, 0),
(18, 5, '2026-09-02 10:10:00', 'Enrolled', NULL, 0),
(19, 5, '2026-09-02 10:15:00', 'Enrolled', NULL, 0),
(20, 5, '2026-09-02 10:20:00', 'Enrolled', NULL, 0),
(21, 5, '2026-09-02 10:25:00', 'Enrolled', NULL, 0),
(22, 5, '2026-09-02 10:30:00', 'Enrolled', NULL, 0),
(23, 5, '2026-09-02 10:35:00', 'Enrolled', NULL, 0),
(24, 5, '2026-09-02 10:40:00', 'Enrolled', NULL, 0),
(25, 5, '2026-09-02 10:45:00', 'Enrolled', NULL, 0),

-- Class 7 (IS201_01): 18 sinh viên (>= 15 SV: Đạt chuẩn)
(11, 7, '2026-09-02 10:50:00', 'Enrolled', NULL, 0),
(12, 7, '2026-09-02 10:55:00', 'Enrolled', NULL, 0),
(13, 7, '2026-09-02 11:00:00', 'Enrolled', NULL, 0),
(14, 7, '2026-09-02 11:05:00', 'Enrolled', NULL, 0),
(15, 7, '2026-09-02 11:10:00', 'Enrolled', NULL, 0),
(16, 7, '2026-09-02 11:15:00', 'Enrolled', NULL, 0),
(17, 7, '2026-09-02 11:20:00', 'Enrolled', NULL, 0),
(18, 7, '2026-09-02 11:25:00', 'Enrolled', NULL, 0),
(19, 7, '2026-09-02 11:30:00', 'Enrolled', NULL, 0),
(20, 7, '2026-09-02 11:35:00', 'Enrolled', NULL, 0),
(21, 7, '2026-09-02 11:40:00', 'Enrolled', NULL, 0),
(22, 7, '2026-09-02 11:45:00', 'Enrolled', NULL, 0),
(23, 7, '2026-09-02 11:50:00', 'Enrolled', NULL, 0),
(24, 7, '2026-09-02 11:55:00', 'Enrolled', NULL, 0),
(25, 7, '2026-09-02 12:00:00', 'Enrolled', NULL, 0),
(26, 7, '2026-09-02 12:05:00', 'Enrolled', NULL, 0),
(27, 7, '2026-09-02 12:10:00', 'Enrolled', NULL, 0),
(28, 7, '2026-09-02 12:15:00', 'Enrolled', NULL, 0),

-- Class 10 (IS301_01): 16 sinh viên (>= 15 SV: Đạt chuẩn)
(11, 10, '2026-09-02 13:00:00', 'Enrolled', NULL, 0),
(12, 10, '2026-09-02 13:05:00', 'Enrolled', NULL, 0),
(13, 10, '2026-09-02 13:10:00', 'Enrolled', NULL, 0),
(14, 10, '2026-09-02 13:15:00', 'Enrolled', NULL, 0),
(15, 10, '2026-09-02 13:20:00', 'Enrolled', NULL, 0),
(16, 10, '2026-09-02 13:25:00', 'Enrolled', NULL, 0),
(17, 10, '2026-09-02 13:30:00', 'Enrolled', NULL, 0),
(18, 10, '2026-09-02 13:35:00', 'Enrolled', NULL, 0),
(19, 10, '2026-09-02 13:40:00', 'Enrolled', NULL, 0),
(20, 10, '2026-09-02 13:45:00', 'Enrolled', NULL, 0),
(21, 10, '2026-09-02 13:50:00', 'Enrolled', NULL, 0),
(22, 10, '2026-09-02 13:55:00', 'Enrolled', NULL, 0),
(23, 10, '2026-09-02 14:00:00', 'Enrolled', NULL, 0),
(24, 10, '2026-09-02 14:05:00', 'Enrolled', NULL, 0),
(25, 10, '2026-09-02 14:10:00', 'Enrolled', NULL, 0),
(26, 10, '2026-09-02 14:15:00', 'Enrolled', NULL, 0),

-- Class 21 (MA101_01): 5 sinh viên (< 15 SV: Dành cho Admin thử nghiệm tính năng Hủy lớp ít sinh viên)
(11, 21, '2026-09-02 14:30:00', 'Enrolled', NULL, 0),
(12, 21, '2026-09-02 14:35:00', 'Enrolled', NULL, 0),
(13, 21, '2026-09-02 14:40:00', 'Enrolled', NULL, 0),
(14, 21, '2026-09-02 14:45:00', 'Enrolled', NULL, 0),
(15, 21, '2026-09-02 14:50:00', 'Enrolled', NULL, 0),

-- Class 22 (MA102_01): 4 sinh viên (< 15 SV)
(16, 22, '2026-09-02 15:00:00', 'Enrolled', NULL, 0),
(17, 22, '2026-09-02 15:05:00', 'Enrolled', NULL, 0),
(18, 22, '2026-09-02 15:10:00', 'Enrolled', NULL, 0),
(19, 22, '2026-09-02 15:15:00', 'Enrolled', NULL, 0);

-- Đồng bộ biến CurrentEnrollment cho các lớp học phần
UPDATE c
SET c.CurrentEnrollment = (
    SELECT COUNT(*) 
    FROM dbo.Enrollments e 
    WHERE e.ClassId = c.Id AND e.Status = 'Enrolled'
)
FROM dbo.Classes c;

-- 4.9. Ghi nhận Nhật ký Đăng ký mẫu (RegistrationHistory)
INSERT INTO dbo.RegistrationHistory (StudentId, ClassId, ActionType, ActionTime, PerformedByUserId, Note)
SELECT StudentId, ClassId, 'Register', EnrolledAt, StudentId, N'Đăng ký trực tuyến thành công'
FROM dbo.Enrollments
WHERE Status = 'Enrolled';

-- 4.10. Tự động tính toán Bảng kê Học phí (Tuitions) cho sinh viên
DECLARE @CurrentStudentId INT = 11;
WHILE @CurrentStudentId <= 30
BEGIN
    EXEC dbo.sp_RecalculateStudentTuition @StudentId = @CurrentStudentId, @SemesterId = 2;
    SET @CurrentStudentId = @CurrentStudentId + 1;
END;
GO
