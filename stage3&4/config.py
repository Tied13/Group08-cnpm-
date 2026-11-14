import os
import pyodbc

class Config:
    """Application configuration settings with auto-driver detection for multi-machine compatibility."""
    
    # Secret key for session encryption
    SECRET_KEY = os.environ.get('SECRET_KEY', 'group08_course_registration_secret_key_2026')

    # Microsoft SQL Server settings
    DB_SERVER = os.environ.get('DB_SERVER', 'localhost')
    DB_DATABASE = os.environ.get('DB_DATABASE', 'CourseRegistrationDB')
    
    # Windows Authentication (Trusted_Connection) or SQL User Credentials
    DB_TRUSTED_CONNECTION = os.environ.get('DB_TRUSTED_CONNECTION', 'yes')
    DB_USER = os.environ.get('DB_USER', 'sa')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', 'YourPassword123')

    @classmethod
    def get_best_driver(cls):
        """Auto-detect the most suitable installed SQL Server ODBC driver on this machine."""
        custom_driver = os.environ.get('DB_DRIVER')
        if custom_driver:
            return custom_driver if custom_driver.startswith('{') else f"{{{custom_driver}}}"

        try:
            available = pyodbc.drivers()
            preferred = [
                'ODBC Driver 17 for SQL Server',
                'ODBC Driver 18 for SQL Server',
                'SQL Server Native Client 11.0',
                'SQL Server Native Client RDA 11.0',
                'SQL Server'
            ]
            for d in preferred:
                if d in available:
                    return f"{{{d}}}"
        except Exception:
            pass
        return "{ODBC Driver 17 for SQL Server}"

    @classmethod
    def get_connection_string(cls, server=None, driver=None):
        """Build and return an ODBC connection string for pyodbc."""
        drv = driver or cls.get_best_driver()
        srv = server or cls.DB_SERVER
        
        if cls.DB_TRUSTED_CONNECTION.lower() in ('yes', 'true', '1'):
            return (
                f"DRIVER={drv};"
                f"SERVER={srv};"
                f"DATABASE={cls.DB_DATABASE};"
                f"Trusted_Connection=yes;"
                f"TrustServerCertificate=yes;"
            )
        return (
            f"DRIVER={drv};"
            f"SERVER={srv};"
            f"DATABASE={cls.DB_DATABASE};"
            f"UID={cls.DB_USER};"
            f"PWD={cls.DB_PASSWORD};"
            f"TrustServerCertificate=yes;"
        )
