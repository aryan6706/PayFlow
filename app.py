"""PayFlow: a focused Flask + SQLite payroll management application."""
from __future__ import annotations

import csv
import os
import secrets
import sqlite3
from datetime import datetime
from functools import wraps
from io import StringIO
from pathlib import Path

from flask import Flask, Response, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("PAYFLOW_SECRET_KEY", "change-this-before-production"),
    DATABASE=str(BASE_DIR / "instance" / "payflow.db"),
    DEFAULT_ADMIN_USERNAME=os.environ.get("PAYFLOW_ADMIN_USERNAME", "admin"),
    DEFAULT_ADMIN_PASSWORD=os.environ.get("PAYFLOW_ADMIN_PASSWORD", "admin123"),
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_code TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    department TEXT NOT NULL,
    designation TEXT NOT NULL,
    base_salary REAL NOT NULL CHECK (base_salary >= 0),
    payment_details TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS payrolls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    pay_period TEXT NOT NULL,
    base_salary REAL NOT NULL CHECK (base_salary >= 0),
    allowances REAL NOT NULL DEFAULT 0 CHECK (allowances >= 0),
    deductions REAL NOT NULL DEFAULT 0 CHECK (deductions >= 0),
    tax REAL NOT NULL DEFAULT 0 CHECK (tax >= 0),
    net_salary REAL NOT NULL CHECK (net_salary >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE RESTRICT,
    UNIQUE (employee_id, pay_period)
);
CREATE INDEX IF NOT EXISTS idx_payrolls_period ON payrolls(pay_period);
CREATE INDEX IF NOT EXISTS idx_payrolls_employee ON payrolls(employee_id);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error: BaseException | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()
    db.executescript(SCHEMA)
    existing_admin = db.execute("SELECT id FROM users WHERE username = ?", (app.config["DEFAULT_ADMIN_USERNAME"],)).fetchone()
    if existing_admin is None:
        password_hash = generate_password_hash(app.config["DEFAULT_ADMIN_PASSWORD"], method="pbkdf2:sha256")
        db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (app.config["DEFAULT_ADMIN_USERNAME"], password_hash))
    db.commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


@app.before_request
def csrf_protect():
    if request.method == "POST" and request.form.get("csrf_token") != session.get("csrf_token"):
        flash("This form has expired. Please submit it again.", "warning")
        return redirect(request.referrer or url_for("index"))


@app.context_processor
def shared_template_values():
    return {"csrf_token": csrf_token(), "current_year": datetime.now().year}


@app.template_filter("money")
def money(value: float) -> str:
    return f"₹{float(value):,.2f}"


@app.template_filter("period")
def period(value: str) -> str:
    return datetime.strptime(value, "%Y-%m").strftime("%B %Y")


def employee_form_values(form):
    values = {field: form.get(field, "").strip() for field in ("employee_code", "full_name", "department", "designation", "payment_details")}
    if not all(values.values()) or any(len(value) > 120 for value in values.values()):
        raise ValueError("Complete all employee fields using concise values.")
    base_salary = float(form.get("base_salary", ""))
    if base_salary < 0:
        raise ValueError("Base salary cannot be negative.")
    status = form.get("status", "active")
    if status not in {"active", "inactive"}:
        raise ValueError("Choose a valid employee status.")
    return (*values.values(), base_salary, status)


def payroll_form_values(form, employee):
    pay_period = form.get("pay_period", "")
    try:
        datetime.strptime(pay_period, "%Y-%m")
    except ValueError as error:
        raise ValueError("Choose a valid pay period.") from error
    allowances = float(form.get("allowances", 0) or 0)
    deductions = float(form.get("deductions", 0) or 0)
    tax = float(form.get("tax", 0) or 0)
    if min(allowances, deductions, tax) < 0:
        raise ValueError("Payroll amounts cannot be negative.")
    net_salary = employee["base_salary"] + allowances - deductions - tax
    if net_salary < 0:
        raise ValueError("Deductions and tax cannot exceed gross earnings.")
    return pay_period, allowances, deductions, tax, net_salary


@app.route("/")
def index():
    return redirect(url_for("dashboard") if session.get("user_id") else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = get_db().execute("SELECT * FROM users WHERE username = ?", (request.form.get("username", "").strip(),)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            csrf_token()
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    current_period = datetime.now().strftime("%Y-%m")
    stats = {
        "employees": db.execute("SELECT COUNT(*) FROM employees WHERE status = 'active'").fetchone()[0],
        "runs": db.execute("SELECT COUNT(*) FROM payrolls").fetchone()[0],
        "current_total": db.execute("SELECT COALESCE(SUM(net_salary), 0) FROM payrolls WHERE pay_period = ?", (current_period,)).fetchone()[0],
        "total_paid": db.execute("SELECT COALESCE(SUM(net_salary), 0) FROM payrolls").fetchone()[0],
    }
    recent = db.execute("""SELECT p.*, e.full_name, e.employee_code FROM payrolls p
                           JOIN employees e ON e.id = p.employee_id
                           ORDER BY p.created_at DESC, p.id DESC LIMIT 6""").fetchall()
    return render_template("dashboard.html", stats=stats, current_period=current_period, recent=recent)


@app.route("/employees")
@login_required
def employees():
    query = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    where, params = [], []
    if query:
        where.append("(employee_code LIKE ? OR full_name LIKE ? OR department LIKE ? OR designation LIKE ?)")
        params.extend([f"%{query}%"] * 4)
    if status in {"active", "inactive"}:
        where.append("status = ?")
        params.append(status)
    sql = "SELECT * FROM employees" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY full_name"
    return render_template("employees.html", employees=get_db().execute(sql, params).fetchall(), query=query, status=status)


@app.route("/employees/new", methods=["GET", "POST"])
@login_required
def new_employee():
    if request.method == "POST":
        try:
            get_db().execute("""INSERT INTO employees
                (employee_code, full_name, department, designation, payment_details, base_salary, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)""", employee_form_values(request.form))
            get_db().commit()
            flash("Employee created.", "success")
            return redirect(url_for("employees"))
        except (ValueError, sqlite3.IntegrityError) as error:
            flash(str(error) if isinstance(error, ValueError) else "Employee code must be unique.", "danger")
    return render_template("employee_form.html", employee=None)


@app.route("/employees/<int:employee_id>/edit", methods=["GET", "POST"])
@login_required
def edit_employee(employee_id: int):
    db = get_db()
    employee = db.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if employee is None:
        flash("Employee not found.", "danger")
        return redirect(url_for("employees"))
    if request.method == "POST":
        try:
            db.execute("""UPDATE employees SET employee_code=?, full_name=?, department=?, designation=?,
                         payment_details=?, base_salary=?, status=? WHERE id=?""", (*employee_form_values(request.form), employee_id))
            db.commit()
            flash("Employee updated.", "success")
            return redirect(url_for("employees"))
        except (ValueError, sqlite3.IntegrityError) as error:
            flash(str(error) if isinstance(error, ValueError) else "Employee code must be unique.", "danger")
    return render_template("employee_form.html", employee=employee)


@app.route("/employees/<int:employee_id>/delete", methods=["POST"])
@login_required
def delete_employee(employee_id: int):
    try:
        db = get_db()
        db.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
        db.commit()
        flash("Employee removed.", "success")
    except sqlite3.IntegrityError:
        flash("This employee has payroll history and cannot be removed. Mark them inactive instead.", "warning")
    return redirect(url_for("employees"))


@app.route("/payrolls")
@login_required
def payrolls():
    period_filter = request.args.get("period", "")
    query = request.args.get("q", "").strip()
    clauses, params = [], []
    if period_filter:
        clauses.append("p.pay_period = ?")
        params.append(period_filter)
    if query:
        clauses.append("(e.full_name LIKE ? OR e.employee_code LIKE ?)")
        params.extend([f"%{query}%", f"%{query}%"])
    sql = """SELECT p.*, e.full_name, e.employee_code, e.department FROM payrolls p
             JOIN employees e ON e.id=p.employee_id"""
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY p.pay_period DESC, e.full_name"
    return render_template("payrolls.html", payrolls=get_db().execute(sql, params).fetchall(), period_filter=period_filter, query=query)


@app.route("/payrolls/new", methods=["GET", "POST"])
@login_required
def new_payroll():
    db = get_db()
    employees = db.execute("SELECT * FROM employees WHERE status='active' ORDER BY full_name").fetchall()
    if not employees:
        flash("Add an active employee before creating a payroll record.", "warning")
        return redirect(url_for("new_employee"))
    if request.method == "POST":
        try:
            employee_id = int(request.form.get("employee_id", ""))
            employee = db.execute("SELECT * FROM employees WHERE id=? AND status='active'", (employee_id,)).fetchone()
            if employee is None:
                raise ValueError("Choose an active employee.")
            pay_period, allowances, deductions, tax, net_salary = payroll_form_values(request.form, employee)
            db.execute("""INSERT INTO payrolls (employee_id,pay_period,base_salary,allowances,deductions,tax,net_salary)
                         VALUES (?, ?, ?, ?, ?, ?, ?)""", (employee_id, pay_period, employee["base_salary"], allowances, deductions, tax, net_salary))
            db.commit()
            payroll_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            flash("Payroll record created.", "success")
            return redirect(url_for("payslip", payroll_id=payroll_id))
        except (ValueError, sqlite3.IntegrityError) as error:
            flash(str(error) if isinstance(error, ValueError) else "A payroll record already exists for this employee and period.", "danger")
    return render_template("payroll_form.html", employees=employees, current_period=datetime.now().strftime("%Y-%m"))


@app.route("/payrolls/<int:payroll_id>/payslip")
@login_required
def payslip(payroll_id: int):
    payroll = get_db().execute("""SELECT p.*,e.employee_code,e.full_name,e.department,e.designation,e.payment_details
                                  FROM payrolls p JOIN employees e ON e.id=p.employee_id WHERE p.id=?""", (payroll_id,)).fetchone()
    if payroll is None:
        flash("Payslip not found.", "danger")
        return redirect(url_for("payrolls"))
    return render_template("payslip.html", payroll=payroll)


@app.route("/payrolls/export.csv")
@login_required
def export_payrolls():
    period_filter = request.args.get("period", "")
    rows = get_db().execute("""SELECT p.pay_period,e.employee_code,e.full_name,e.department,p.base_salary,p.allowances,p.deductions,p.tax,p.net_salary
                              FROM payrolls p JOIN employees e ON e.id=p.employee_id
                              WHERE (?='' OR p.pay_period=?) ORDER BY p.pay_period,e.full_name""", (period_filter, period_filter)).fetchall()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Pay Period", "Employee Code", "Employee", "Department", "Base Salary", "Allowances", "Deductions", "Tax", "Net Salary"])
    writer.writerows([tuple(row) for row in rows])
    filename = f"payroll-{period_filter or 'all-periods'}.csv"
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})


@app.route("/reports")
@login_required
def reports():
    monthly = get_db().execute("""SELECT pay_period,COUNT(*) AS record_count,SUM(base_salary) AS gross_base,
        SUM(allowances) AS allowances,SUM(deductions + tax) AS withholdings,SUM(net_salary) AS net_total
        FROM payrolls GROUP BY pay_period ORDER BY pay_period DESC""").fetchall()
    return render_template("reports.html", monthly=monthly)


with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
