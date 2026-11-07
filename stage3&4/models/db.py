import pyodbc
from flask import g
from config import Config

def init_sql_server_db():
    """Tự động kiểm tra và tạo Database, Bảng & Dữ liệu mẫu trên SQL Server"""
    master_conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={Config.DB_SERVER};"
        f"DATABASE=master;"
        f"Trusted_Connection=yes;"
        f"TrustServerCertificate=yes;"
    )
    
    try:
        conn = pyodbc.connect(master_conn_str, autocommit=True)
        cursor = conn.cursor()
        cursor.execute(f"""
            IF NOT EXISTS (SELECT * FROM sys.databases WHERE name = '{Config.DB_NAME}')
            BEGIN
                CREATE DATABASE [{Config.DB_NAME}];
            END
        """)
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[!] Kiểm tra database master: {e}")

    try:
        conn = pyodbc.connect(Config.DB_CONNECTION_STRING, autocommit=True)
        cursor = conn.cursor()
        
        # Bảng Users
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Users')
            BEGIN
                CREATE TABLE Users (
                    Id INT IDENTITY(1,1) PRIMARY KEY,
                    Username NVARCHAR(50) UNIQUE NOT NULL,
                    Password NVARCHAR(255) NOT NULL,
                    FullName NVARCHAR(100) NOT NULL,
                    Role NVARCHAR(20) CHECK (Role IN ('admin', 'lecturer', 'student')) NOT NULL,
                    Email NVARCHAR(100),
                    CreatedAt DATETIME DEFAULT GETDATE()
                );
                INSERT INTO Users (Username, Password, FullName, Role) VALUES 
                ('admin', '123', N'Quản trị viên', 'admin'),
                ('gv01', '123', N'Giảng viên Nguyễn Văn A', 'lecturer'),
                ('sv01', '123', N'Sinh viên Trần Văn B', 'student');
            END
        """)
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[!] Khởi tạo bảng Users: {e}")

def get_db():
    if 'db' not in g:
        g.db = pyodbc.connect(Config.DB_CONNECTION_STRING)
    return g.db

def query_db(query, args=(), one=False):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(query, args)
    columns = [col[0] for col in cursor.description] if cursor.description else []
    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    cursor.close()
    return (results[0] if results else None) if one else results

def execute_db(query, args=()):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(query, args)
    conn.commit()
    cursor.close()

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()
