import os
import pyodbc

class Config:
    """
    Cấu hình ứng dụng kết nối Microsoft SQL Server.
    - Trong Docker: Các biến được tự động gán từ docker-compose (SQL Server Authentication: sa / StrongPass@2026)
    - Chạy Local: Mặc định dùng Windows Authentication (Trusted_Connection) hoặc SQL Auth
    """
    
    # Secret key cho session
    SECRET_KEY = os.environ.get('SECRET_KEY', 'group08_course_registration_secret_key_2026')

    # Thông tin kết nối SQL Server
    DB_SERVER = os.environ.get('DB_SERVER', 'localhost')
    DB_DATABASE = os.environ.get('DB_DATABASE', 'CourseRegistrationDB')
    
    # Windows Authentication ('yes') hoặc SQL Server Authentication ('no' - dùng trong Docker)
    DB_TRUSTED_CONNECTION = os.environ.get('DB_TRUSTED_CONNECTION', 'yes')
    DB_USER = os.environ.get('DB_USER', 'sa')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', 'StrongPass@2026')

    @classmethod
    def get_best_driver(cls):
        """Tự động phát hiện driver ODBC SQL Server phù hợp nhất trên máy chủ/container."""
        custom_driver = os.environ.get('DB_DRIVER')
        if custom_driver:
            return custom_driver if custom_driver.startswith('{') else f"{{{custom_driver}}}"

        try:
            available = pyodbc.drivers()
            preferred = [
                'ODBC Driver 18 for SQL Server',
                'ODBC Driver 17 for SQL Server',
                'SQL Server Native Client 11.0',
                'SQL Server Native Client RDA 11.0',
                'SQL Server'
            ]
            for d in preferred:
                if d in available:
                    return f"{{{d}}}"
        except Exception:
            pass
        return "{ODBC Driver 18 for SQL Server}"

    @classmethod
    def get_connection_string(cls, server=None, driver=None):
        """Xây dựng chuỗi kết nối ODBC cho pyodbc."""
        drv = driver or cls.get_best_driver()
        srv = server or cls.DB_SERVER
        
        base_conn = (
            f"DRIVER={drv};"
            f"SERVER={srv};"
            f"DATABASE={cls.DB_DATABASE};"
            f"TrustServerCertificate=yes;"
        )
        
        if cls.DB_TRUSTED_CONNECTION.lower() in ('yes', 'true', '1'):
            return base_conn + "Trusted_Connection=yes;"
            
        return base_conn + f"UID={cls.DB_USER};PWD={cls.DB_PASSWORD};"
