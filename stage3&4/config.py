import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'course_system_secret_key_2026'
    
    # Cấu hình SQL Server Management Studio
    DB_SERVER = r'localhost\SQLEXPRESS'
    DB_NAME = 'CourseRegistrationDB'
    
    # Kết nối Windows Authentication mặc định
    DB_CONNECTION_STRING = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_NAME};"
        f"Trusted_Connection=yes;"
        f"TrustServerCertificate=yes;"
    )
