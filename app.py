import os
import sqlite3
import csv
import io
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, Response, abort
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'payflow-secure-prod-key-7f9a2b')

# Use /tmp on Vercel/serverless; use local directory for local testing
if os.environ.get('VERCEL'):
    app.config['DATABASE'] = '/tmp/payflow.db'
else:
    app.config['DATABASE'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'payflow.db')

def get_db():
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                emp_code TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                department TEXT NOT NULL,
                designation TEXT NOT NULL,
                base_salary REAL NOT NULL CHECK(base_salary >= 0),
                bank_account TEXT NOT NULL,
                status TEXT CHECK(status IN ('Active', 'Inactive')) DEFAULT 'Active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS payroll_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                pay_period TEXT NOT NULL,
                base_salary REAL NOT NULL,
                allowances REAL DEFAULT 0.0,
                deductions REAL DEFAULT 0.0,
                tax REAL DEFAULT 0.0,
                net_salary REAL NOT NULL,
                payment_status TEXT CHECK(payment_status IN ('Pending', 'Processed', 'Paid')) DEFAULT 'Processed',
                payment_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (employee_id) REFERENCES employees (id) ON DELETE CASCADE,
                UNIQUE(employee_id, pay_period)
            );
        """)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            default_hash = generate_password_hash("admin123")
            conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ("admin", default_hash))
        conn.commit()

@app.before_request
def ensure_db():
    if not os.path.exists(app.config['DATABASE']):
        init_db()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if user and check_password_hash(user['password_hash'], password):
                session.clear()
                session['user_id'] = user['id']
                session['username'] = user['username']
                return redirect(url_for('dashboard'))

        flash("Invalid credentials.", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    with get_db() as conn:
        total_employees = conn.execute("SELECT COUNT(*) FROM employees WHERE status = 'Active'").fetchone()[0]
        
        current_period = datetime.now().strftime('%Y-%m')
        payroll_stat = conn.execute("""
            SELECT 
                COUNT(*) as records_count,
                COALESCE(SUM(net_salary), 0) as total_net,
                COALESCE(SUM(tax), 0) as total_tax
            FROM payroll_records 
            WHERE pay_period = ?
        """, (current_period,)).fetchone()

        recent_payrolls = conn.execute("""
            SELECT p.*, e.full_name, e.emp_code, e.department
            FROM payroll_records p
            JOIN employees e ON p.employee_id = e.id
            ORDER BY p.id DESC LIMIT 5
        """).fetchall()

    return render_template(
        'dashboard.html',
        total_employees=total_employees,
        current_period=current_period,
        payroll_stat=payroll_stat,
        recent_payrolls=recent_payrolls
    )

@app.route('/employees')
@login_required
def employees():
    with get_db() as conn:
        all_employees = conn.execute("SELECT * FROM employees ORDER BY emp_code ASC").fetchall()
    return render_template('employees.html', employees=all_employees)

@app.route('/employees/new', methods=['GET', 'POST'])
@login_required
def employee_create():
    if request.method == 'POST':
        emp_code = request.form.get('emp_code', '').strip().upper()
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        department = request.form.get('department', '').strip()
        designation = request.form.get('designation', '').strip()
        base_salary = float(request.form.get('base_salary', 0))
        bank_account = request.form.get('bank_account', '').strip()
        status = request.form.get('status', 'Active')

        try:
            with get_db() as conn:
                conn.execute("""
                    INSERT INTO employees (emp_code, full_name, email, department, designation, base_salary, bank_account, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (emp_code, full_name, email, department, designation, base_salary, bank_account, status))
            flash("Employee added successfully.", "success")
            return redirect(url_for('employees'))
        except sqlite3.IntegrityError:
            flash("Employee Code or Email already exists.", "danger")

    return render_template('employee_form.html', employee=None)

@app.route('/employees/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def employee_edit(id):
    with get_db() as conn:
        emp = conn.execute("SELECT * FROM employees WHERE id = ?", (id,)).fetchone()
        if not emp:
            abort(404)

        if request.method == 'POST':
            full_name = request.form.get('full_name', '').strip()
            department = request.form.get('department', '').strip()
            designation = request.form.get('designation', '').strip()
            base_salary = float(request.form.get('base_salary', 0))
            bank_account = request.form.get('bank_account', '').strip()
            status = request.form.get('status', 'Active')

            conn.execute("""
                UPDATE employees
                SET full_name = ?, department = ?, designation = ?, base_salary = ?, bank_account = ?, status = ?
                WHERE id = ?
            """, (full_name, department, designation, base_salary, bank_account, status, id))
            flash("Employee record updated.", "success")
            return redirect(url_for('employees'))

    return render_template('employee_form.html', employee=emp)

@app.route('/payrolls')
@login_required
def payrolls():
    period = request.args.get('period', datetime.now().strftime('%Y-%m'))
    with get_db() as conn:
        records = conn.execute("""
            SELECT p.*, e.emp_code, e.full_name, e.department 
            FROM payroll_records p
            JOIN employees e ON p.employee_id = e.id
            WHERE p.pay_period = ?
            ORDER BY e.emp_code ASC
        """, (period,)).fetchall()
    return render_template('payrolls.html', records=records, period=period)

@app.route('/payrolls/process', methods=['GET', 'POST'])
@login_required
def payroll_process():
    if request.method == 'POST':
        employee_id = int(request.form.get('employee_id'))
        pay_period = request.form.get('pay_period', '').strip()
        allowances = float(request.form.get('allowances', 0.0))
        deductions = float(request.form.get('deductions', 0.0))
        tax = float(request.form.get('tax', 0.0))
        payment_status = request.form.get('payment_status', 'Processed')
        payment_date = datetime.now().strftime('%Y-%m-%d')

        with get_db() as conn:
            emp = conn.execute("SELECT base_salary FROM employees WHERE id = ?", (employee_id,)).fetchone()
            if not emp:
                flash("Selected employee does not exist.", "danger")
                return redirect(url_for('payroll_process'))

            base_salary = emp['base_salary']
            net_salary = round((base_salary + allowances) - (deductions + tax), 2)

            try:
                conn.execute("""
                    INSERT INTO payroll_records (
                        employee_id, pay_period, base_salary, allowances, 
                        deductions, tax, net_salary, payment_status, payment_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (employee_id, pay_period, base_salary, allowances, deductions, tax, net_salary, payment_status, payment_date))
                flash("Payroll calculated and recorded.", "success")
                return redirect(url_for('payrolls', period=pay_period))
            except sqlite3.IntegrityError:
                flash(f"Payroll record for this employee in {pay_period} already exists.", "danger")

    with get_db() as conn:
        active_employees = conn.execute("SELECT id, emp_code, full_name, base_salary FROM employees WHERE status = 'Active' ORDER BY emp_code ASC").fetchall()

    current_period = datetime.now().strftime('%Y-%m')
    return render_template('payroll_form.html', employees=active_employees, current_period=current_period)

@app.route('/payrolls/<int:id>/payslip')
@login_required
def payslip(id):
    with get_db() as conn:
        record = conn.execute("""
            SELECT p.*, e.emp_code, e.full_name, e.email, e.department, e.designation, e.bank_account
            FROM payroll_records p
            JOIN employees e ON p.employee_id = e.id
            WHERE p.id = ?
        """, (id,)).fetchone()
        if not record:
            abort(404)
    return render_template('payslip.html', item=record)

@app.route('/reports')
@login_required
def reports():
    with get_db() as conn:
        period_summary = conn.execute("""
            SELECT 
                pay_period,
                COUNT(id) as headcount,
                SUM(base_salary) as total_base,
                SUM(allowances) as total_allowances,
                SUM(deductions) as total_deductions,
                SUM(tax) as total_tax,
                SUM(net_salary) as net_disbursed
            FROM payroll_records
            GROUP BY pay_period
            ORDER BY pay_period DESC
        """).fetchall()

        dept_summary = conn.execute("""
            SELECT 
                e.department,
                COUNT(DISTINCT e.id) as emp_count,
                COALESCE(SUM(p.net_salary), 0) as total_payroll_expenditure
            FROM employees e
            LEFT JOIN payroll_records p ON e.id = p.employee_id
            GROUP BY e.department
        """).fetchall()

    return render_template('reports.html', periods=period_summary, departments=dept_summary)

@app.route('/export/payrolls')
@login_required
def export_payrolls():
    period = request.args.get('period', datetime.now().strftime('%Y-%m'))
    with get_db() as conn:
        records = conn.execute("""
            SELECT 
                p.id, e.emp_code, e.full_name, e.department, p.pay_period,
                p.base_salary, p.allowances, p.deductions, p.tax, p.net_salary,
                p.payment_status, p.payment_date
            FROM payroll_records p
            JOIN employees e ON p.employee_id = e.id
            WHERE p.pay_period = ?
            ORDER BY e.emp_code ASC
        """, (period,)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Payroll ID', 'Employee Code', 'Full Name', 'Department', 'Period',
        'Base Salary', 'Allowances', 'Deductions', 'Tax', 'Net Salary',
        'Status', 'Payment Date'
    ])

    for row in records:
        writer.writerow(list(row))

    output.seek(0)
    filename = f"payroll_export_{period}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
