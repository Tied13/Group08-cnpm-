from flask import Flask
from config import Config
from models.db import close_db, init_sql_server_db
from controllers.auth_controller import auth_bp
from controllers.admin_controller import admin_bp
from controllers.lecturer_controller import lecturer_bp
from controllers.student_controller import student_bp

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config.from_object(Config)

app.teardown_appcontext(close_db)

app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(lecturer_bp)
app.register_blueprint(student_bp)

if __name__ == '__main__':
    init_sql_server_db()
    print("Khởi chạy hệ thống Course Registration MVC...")
    print("Truy cập website tại: http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
