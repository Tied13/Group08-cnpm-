import os

class Config:
    """Application configuration settings."""
    
    # Secret key for session encryption
    SECRET_KEY = os.environ.get('SECRET_KEY', 'group08_course_registration_secret_key_2026')

    # Microsoft SQL Server settings
    DB_SERVER = os.environ.get('DB_SERVER', 'localhost')
    DB_DATABASE = os.environ.get('DB_DATABASE', 'CourseRegistrationDB')
    DB_DRIVER = os.environ.get('DB_DRIVER', '{ODBC Driver 17 for SQL Server}')
    
    # Windows Authentication (Trusted_Connection) or SQL User Credentials
    DB_TRUSTED_CONNECTION = os.environ.get('DB_TRUSTED_CONNECTION', 'yes')
    DB_USER = os.environ.get('DB_USER', 'sa')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', 'YourPassword123')

    @classmethod
    def get_connection_string(cls):
        """Build and return an ODBC connection string for pyodbc."""
        driver = cls.DB_DRIVER if cls.DB_DRIVER.startswith('{') else f"{{{cls.DB_DRIVER}}}"
        
        if cls.DB_TRUSTED_CONNECTION.lower() in ('yes', 'true', '1'):
            return (
                f"DRIVER={driver};"
                f"SERVER={cls.DB_SERVER};"
                f"DATABASE={cls.DB_DATABASE};"
                f"Trusted_Connection=yes;"
                f"TrustServerCertificate=yes;"
            )
        return (
            f"DRIVER={driver};"
            f"SERVER={cls.DB_SERVER};"
            f"DATABASE={cls.DB_DATABASE};"
            f"UID={cls.DB_USER};"
            f"PWD={cls.DB_PASSWORD};"
            f"TrustServerCertificate=yes;"
        )
