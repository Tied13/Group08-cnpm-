import os


class Config:
  """Application configuration settings."""

  SECRET_KEY = os.environ.get(
      "SECRET_KEY", "group08_course_registration_secret_key_2026"
  )

  # Cấu hình chuẩn khớp với SSMS đang mở (server là localhost)
  DB_SERVER = os.environ.get("DB_SERVER", "localhost")
  DB_DATABASE = os.environ.get("DB_DATABASE", "CourseRegistrationDB")
  DB_DRIVER = os.environ.get("DB_DRIVER", "{ODBC Driver 17 for SQL Server}")

  # Đổi thành "yes" để dùng quyền Windows Authentication (khớp với tài khoản máy tính của bạn)
  DB_TRUSTED_CONNECTION = os.environ.get("DB_TRUSTED_CONNECTION", "yes")
  DB_USER = os.environ.get("DB_USER", "")               
  DB_PASSWORD = os.environ.get("DB_PASSWORD", "") 

  @classmethod
  def get_connection_string(cls, server=None, database=None):
    # Dùng giá trị truyền vào, nếu không có thì lấy mặc định trong class
    srv = server if server is not None else cls.DB_SERVER
    db = database if database is not None else cls.DB_DATABASE
    
    driver = (
        cls.DB_DRIVER
        if cls.DB_DRIVER.startswith("{")
        else f"{{{cls.DB_DRIVER}}}"
    )

    if cls.DB_TRUSTED_CONNECTION.lower() in ("yes", "true", "1"):
      return (
          f"DRIVER={driver};"
          f"SERVER={srv};"
          f"DATABASE={db};"
          f"Trusted_Connection=yes;"
          f"TrustServerCertificate=yes;"
      )
    return (
        f"DRIVER={driver};"
        f"SERVER={srv};"
        f"DATABASE={db};"
        f"UID={cls.DB_USER};"
        f"PWD={cls.DB_PASSWORD};"
        f"TrustServerCertificate=yes;"
    )