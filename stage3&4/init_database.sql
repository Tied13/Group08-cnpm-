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
   PART 4: SEED DATA
   ========================================================================== */

INSERT INTO dbo.Users (UserCode, Username, PasswordHash, FullName, Email, Phone, Role, Status, FailedLoginCount)
VALUES
(N'ADM001', N'admin',    N'scrypt:32768:8:1$admin123', N'System Administrator', N'admin@uth.edu.vn',   N'0901000001', N'Admin',    N'Active', 0),
(N'GV001',  N'gv_quynh', N'scrypt:32768:8:1$pass123',  N'Luu Quynh',           N'quynh.gv@uth.edu.vn',N'0901000002', N'Lecturer', N'Active', 0),
(N'GV002',  N'gv_duc',   N'scrypt:32768:8:1$pass123',  N'Anh Duc',             N'duc.gv@uth.edu.vn',  N'0901000003', N'Lecturer', N'Active', 0),
(N'SV001',  N'sv_toan',  N'scrypt:32768:8:1$pass123',  N'Khanh Toan',          N'toan.sv@uth.edu.vn', N'0901000004', N'Student',  N'Active', 0),
(N'SV002',  N'sv_vuong', N'scrypt:32768:8:1$pass123',  N'The Vuong',           N'vuong.sv@uth.edu.vn',N'0901000005', N'Student',  N'Active', 0);

INSERT INTO dbo.Admins (UserId, AdminCode, OfficeDepartment) VALUES (1, N'ADM001', N'Academic Affairs Office');
INSERT INTO dbo.Lecturers (UserId, LecturerCode, Department, AcademicDegree) VALUES 
(2, N'GV001', N'Management Information Systems', N'Master'),
(3, N'GV002', N'Software Engineering', N'Doctorate');
INSERT INTO dbo.Students (UserId, StudentCode, AdministrativeClass, Major, Faculty, EnrollmentYear) VALUES
(4, N'SV001', N'MIS2301', N'Management Information Systems', N'Faculty of Information Technology', 2023),
(5, N'SV002', N'MIS2301', N'Management Information Systems', N'Faculty of Information Technology', 2023);

INSERT INTO dbo.Semesters (SemesterCode, SemesterName, AcademicYear, StartDate, EndDate, CreditUnitPrice, IsCurrent)
VALUES 
(N'SEM2_2025_2026', N'Semester 2 (2025-2026)', N'2025-2026', '2026-01-15', '2026-06-15', 520000, 0),
(N'SEM1_2026_2027', N'Semester 1 (2026-2027)', N'2026-2027', '2026-09-01', '2027-01-31', 550000, 1);

INSERT INTO dbo.RegistrationPeriods (SemesterId, PeriodName, StartDate, EndDate, MinCredits, MaxCredits, IsActive)
VALUES 
(2, N'Official Course Registration Period - Fall 2026', '2026-09-01 00:00:00', '2026-12-31 23:59:59', 12, 25, 1);

INSERT INTO dbo.Courses (CourseCode, CourseName, Credits, TheoryHours, PracticeHours, Department, PrerequisiteCourseId)
VALUES
(N'IT101', N'Introduction to Programming',        3, 30, 15, N'Computer Science', NULL),
(N'IT102', N'Data Structures and Algorithms',      4, 45, 15, N'Computer Science', 1),
(N'IS201', N'Database Systems',                    3, 30, 15, N'Information Systems', NULL),
(N'IS301', N'Systems Analysis and Design',         3, 30, 15, N'Information Systems', 3);

INSERT INTO dbo.Classrooms (RoomCode, Building, Capacity, RoomType)
VALUES 
(N'A101', N'Building A', 50, N'Theory'),
(N'B202', N'Building B', 45, N'Theory');

INSERT INTO dbo.TimeSlots (SlotNumber, SlotName, StartTime, EndTime)
VALUES
(1, N'Slot 1 (07:00 - 09:30)', '07:00:00', '09:30:00'),
(2, N'Slot 2 (09:45 - 12:15)', '09:45:00', '12:15:00'),
(3, N'Slot 3 (13:00 - 15:30)', '13:00:00', '15:30:00');

INSERT INTO dbo.Classes (ClassCode, CourseId, SemesterId, LecturerId, ClassroomId, Room, TimeSlotId, DayOfWeek, MinCapacity, MaxCapacity, CurrentEnrollment, Status)
VALUES
(N'IT101_01', 1, 2, 2, 1, N'A101', 1, 2, 15, 50, 0, 'Open'),
(N'IS301_01', 4, 2, 3, 2, N'B202', 2, 3, 15, 50, 0, 'Open');
GO