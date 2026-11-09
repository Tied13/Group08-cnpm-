from flask import Flask, redirect, url_for
from config import Config
from models.db import close_db, init_sql_server_db
from controllers.auth_controller import auth_bp
from controllers.admin_controller import admin_bp
from controllers.lecturer_controller import lecturer_bp
from controllers.student_controller import student_bp

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config.from_object(Config)

# Dong ket noi sau moi request (neu co)
app.teardown_appcontext(close_db)

# Dang ky cac Blueprints cho he thong
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(lecturer_bp)
app.register_blueprint(student_bp)

# Route mac dinh: Chuyen huong ve trang dang nhap
@app.route('/')
def index():
    return redirect(url_for('auth_bp.login'))

if __name__ == '__main__':
    print("==================================================")
    print("Khoi chay he thong Course Registration MVC...")
    init_sql_server_db()
    print("Truy cap website tai: http://127.0.0.1:5000")
    print("==================================================")
    app.run(debug=True, port=5000)
