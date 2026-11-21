from flask import Flask, redirect, url_for
from config import Config
from models.db import close_db, init_sql_server_db
from controllers.auth_controller import auth_bp
from controllers.admin_controller import admin_bp
from controllers.lecturer_controller import lecturer_bp
from controllers.student_controller import student_bp

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config.from_object(Config)

# Contract after each request (if any)
app.teardown_appcontext(close_db)

# Register Blueprints for the system
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(lecturer_bp)
app.register_blueprint(student_bp)

# Redirect to the login page
@app.route('/')
def index():
    return redirect(url_for('auth.login'))

if __name__ == '__main__':
    print("==================================================")
    print("Launch the Course Registration system ...")
    init_sql_server_db()
    print("Access the website at: http://127.0.0.1:5000 (hoac http://localhost:5000)")
    print("==================================================")
    app.run(host='0.0.0.0', debug=True, port=5000)

