-- =========================================================================
-- Script: fix_accounts_password.sql
-- Muc dich: Dat lai mat khau cho tat ca tai khoan ve '123456' va mo khoa (Active)
-- Huong dan: Mo SQL Server Management Studio (SSMS), mo file nay va bam Execute (F5)
-- =========================================================================

USE CourseRegistrationDB;
GO

-- Ma bam Werkzeug scrypt chuan cho mat khau '123456'
DECLARE @CorrectHash NVARCHAR(255) = N'scrypt:32768:8:1$E6TmpjVgQDqaUiav$d79ab1a034cfa9fb797e97766269d438b521dd7718a4288eff2611315e524e6a6e4eb8a31d0777a975cb595cacd42b13b9b3a74bdb755bcbeb18c1eb4f2fcf23';

-- 1. Cap nhat tat ca tai khoan ve mat khau 123456 va mo khoa
UPDATE dbo.Users
SET PasswordHash = @CorrectHash,
    Status = 'Active',
    FailedLoginCount = 0;

PRINT N'>> Da cap nhat toan bo tai khoan ve mat khau 123456 va trang thai Active!';
GO

-- 2. Kiem tra lai tai khoan admin
SELECT Id, UserCode, Username, FullName, Role, Status, FailedLoginCount, PasswordHash
FROM dbo.Users
WHERE Username IN ('admin', 'admin_daotao');
GO
