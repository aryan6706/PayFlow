"""PayFlow — a focused Flask and SQLite payroll management system."""
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

app = Flask(__name__)
ROOT = Path(__file__).resolve().parent
app.config.update(
    SECRET_KEY=os.environ.get("PAYFLOW_SECRET_KEY", "change-this-before-production"),
    DATABASE=str(ROOT / "instance" / "payflow.db"),
    ADMIN_USERNAME=os.environ.get("PAYFLOW_ADMIN_USERNAME", "admin"),
    ADMIN_PASSWORD=os.environ.get("PAYFLOW_ADMIN_PASSWORD", "admin123"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS employees (
 id INTEGER PRIMARY KEY, employee_code TEXT UNIQUE NOT NULL, full_name TEXT NOT NULL, department TEXT NOT NULL,
 designation TEXT NOT NULL, base_salary REAL NOT NULL CHECK(base_salary >= 0), payment_details TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive')), created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS payrolls (
 id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL, pay_period TEXT NOT NULL, base_salary REAL NOT NULL CHECK(base_salary >= 0),
 working_days REAL NOT NULL DEFAULT 22 CHECK(working_days > 0), paid_leave_days REAL NOT NULL DEFAULT 0 CHECK(paid_leave_days >= 0),
 unpaid_leave_days REAL NOT NULL DEFAULT 0 CHECK(unpaid_leave_days >= 0), leave_deduction REAL NOT NULL DEFAULT 0 CHECK(leave_deduction >= 0),
 overtime_hours REAL NOT NULL DEFAULT 0 CHECK(overtime_hours >= 0), overtime_rate_percent REAL NOT NULL DEFAULT 100 CHECK(overtime_rate_percent >= 0), overtime_pay REAL NOT NULL DEFAULT 0 CHECK(overtime_pay >= 0),
 allowances REAL NOT NULL DEFAULT 0 CHECK(allowances >= 0), deductions REAL NOT NULL DEFAULT 0 CHECK(deductions >= 0),
 tax_rate_percent REAL NOT NULL DEFAULT 0 CHECK(tax_rate_percent >= 0), tax REAL NOT NULL DEFAULT 0 CHECK(tax >= 0),
 gross_salary REAL NOT NULL CHECK(gross_salary >= 0), net_salary REAL NOT NULL CHECK(net_salary >= 0), created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE RESTRICT, UNIQUE(employee_id,pay_period));
CREATE INDEX IF NOT EXISTS idx_payroll_period ON payrolls(pay_period);
"""

def db():
    if "db" not in g:
        Path(app.config["DATABASE"]).parent.mkdir(exist_ok=True)
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(_error):
    connection = g.pop("db", None)
    if connection: connection.close()

def init_db():
    connection = db(); connection.executescript(SCHEMA)
    # Upgrade databases created by earlier PayFlow versions without losing payroll history.
    existing_columns = {row["name"] for row in connection.execute("PRAGMA table_info(payrolls)")}
    additions = {
        "working_days": "REAL NOT NULL DEFAULT 22",
        "paid_leave_days": "REAL NOT NULL DEFAULT 0",
        "unpaid_leave_days": "REAL NOT NULL DEFAULT 0",
        "leave_deduction": "REAL NOT NULL DEFAULT 0",
        "overtime_hours": "REAL NOT NULL DEFAULT 0",
        "overtime_rate_percent": "REAL NOT NULL DEFAULT 100",
        "overtime_pay": "REAL NOT NULL DEFAULT 0",
        "tax_rate_percent": "REAL NOT NULL DEFAULT 0",
        "gross_salary": "REAL NOT NULL DEFAULT 0",
    }
    for column, definition in additions.items():
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE payrolls ADD COLUMN {column} {definition}")
    connection.execute("UPDATE payrolls SET gross_salary = base_salary + allowances + overtime_pay WHERE gross_salary = 0")
    if not connection.execute("SELECT 1 FROM users WHERE username=?", (app.config["ADMIN_USERNAME"],)).fetchone():
        password_hash = generate_password_hash(app.config["ADMIN_PASSWORD"], method="pbkdf2:sha256")
        connection.execute("INSERT INTO users(username,password_hash) VALUES(?,?)", (app.config["ADMIN_USERNAME"], password_hash))
    connection.commit()

def csrf():
    if "csrf" not in session: session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]

@app.context_processor
def common(): return {"csrf_token": csrf(), "current_year": datetime.now().year}

@app.before_request
def guard_forms():
    if request.method == "POST" and request.form.get("csrf_token") != session.get("csrf"):
        flash("Your form expired. Please try again.", "warning"); return redirect(request.referrer or url_for("index"))

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in to continue.", "warning"); return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

@app.template_filter("money")
def money(value): return f"₹{float(value):,.2f}"

@app.template_filter("period")
def period(value): return datetime.strptime(value, "%Y-%m").strftime("%B %Y")

def employee_values(form):
    fields = [form.get(key, "").strip() for key in ("employee_code","full_name","department","designation","payment_details")]
    salary = float(form.get("base_salary", "")); status = form.get("status", "active")
    if not all(fields) or any(len(x) > 120 for x in fields): raise ValueError("Complete every employee field using concise values.")
    if salary < 0 or status not in {"active","inactive"}: raise ValueError("Use a valid salary and status.")
    return (*fields, salary, status)

def payroll_values(form, employee):
    pay_period = form.get("pay_period", "")
    try: datetime.strptime(pay_period, "%Y-%m")
    except ValueError: raise ValueError("Choose a valid pay period.")
    working_days = float(form.get("working_days", 22) or 22)
    paid_leave_days = float(form.get("paid_leave_days", 0) or 0)
    unpaid_leave_days = float(form.get("unpaid_leave_days", 0) or 0)
    overtime_hours = float(form.get("overtime_hours", 0) or 0)
    overtime_rate_percent = float(form.get("overtime_rate_percent", 150) or 150)
    allowances = float(form.get("allowances", 0) or 0)
    deductions = float(form.get("deductions", 0) or 0)
    tax_rate_percent = float(form.get("tax_rate_percent", 0) or 0)
    values = (working_days, paid_leave_days, unpaid_leave_days, overtime_hours, overtime_rate_percent, allowances, deductions, tax_rate_percent)
    if working_days <= 0 or min(values[1:]) < 0 or paid_leave_days + unpaid_leave_days > working_days:
        raise ValueError("Use valid leave, overtime, tax, and working-day values.")
    daily_rate = employee["base_salary"] / working_days
    leave_deduction = round(daily_rate * unpaid_leave_days, 2)
    hourly_rate = daily_rate / 8
    overtime_pay = round(hourly_rate * overtime_hours * (overtime_rate_percent / 100), 2)
    gross_salary = round(employee["base_salary"] + allowances + overtime_pay, 2)
    taxable_income = max(0, gross_salary - leave_deduction - deductions)
    tax = round(taxable_income * (tax_rate_percent / 100), 2)
    net = round(gross_salary - leave_deduction - deductions - tax, 2)
    return (pay_period, working_days, paid_leave_days, unpaid_leave_days, leave_deduction,
            overtime_hours, overtime_rate_percent, overtime_pay, allowances, deductions,
            tax_rate_percent, tax, gross_salary, net)

@app.route("/")
def index(): return redirect(url_for("dashboard") if session.get("user_id") else url_for("login"))

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        user = db().execute("SELECT * FROM users WHERE username=?", (request.form.get("username", "").strip(),)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear(); session["user_id"] = user["id"]; session["username"] = user["username"]; csrf(); return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    connection = db(); now = datetime.now().strftime("%Y-%m")
    stats = {"employees":connection.execute("SELECT COUNT(*) FROM employees WHERE status='active'").fetchone()[0],"runs":connection.execute("SELECT COUNT(*) FROM payrolls").fetchone()[0],"current_total":connection.execute("SELECT COALESCE(SUM(net_salary),0) FROM payrolls WHERE pay_period=?",(now,)).fetchone()[0],"total_paid":connection.execute("SELECT COALESCE(SUM(net_salary),0) FROM payrolls").fetchone()[0]}
    recent = connection.execute("SELECT p.*,e.full_name,e.employee_code FROM payrolls p JOIN employees e ON e.id=p.employee_id ORDER BY p.id DESC LIMIT 6").fetchall()
    return render_template("dashboard.html", stats=stats, current_period=now, recent=recent)

@app.route("/employees")
@login_required
def employees():
    q, status = request.args.get("q", "").strip(), request.args.get("status", "")
    clauses, params = [], []
    if q: clauses.append("(employee_code LIKE ? OR full_name LIKE ? OR department LIKE ?)"); params += [f"%{q}%"]*3
    if status in {"active","inactive"}: clauses.append("status=?"); params.append(status)
    sql = "SELECT * FROM employees" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY full_name"
    return render_template("employees.html", employees=db().execute(sql,params).fetchall(), query=q, status=status)

@app.route("/employees/new",methods=["GET","POST"])
@login_required
def new_employee():
    if request.method == "POST":
        try:
            db().execute("INSERT INTO employees(employee_code,full_name,department,designation,payment_details,base_salary,status) VALUES(?,?,?,?,?,?,?)", employee_values(request.form)); db().commit(); flash("Employee created.","success"); return redirect(url_for("employees"))
        except (ValueError,sqlite3.IntegrityError) as error: flash(str(error) if isinstance(error,ValueError) else "Employee code must be unique.","danger")
    return render_template("employee_form.html",employee=None)

@app.route("/employees/<int:employee_id>/edit",methods=["GET","POST"])
@login_required
def edit_employee(employee_id):
    employee = db().execute("SELECT * FROM employees WHERE id=?",(employee_id,)).fetchone()
    if not employee: flash("Employee not found.","danger"); return redirect(url_for("employees"))
    if request.method == "POST":
        try:
            db().execute("UPDATE employees SET employee_code=?,full_name=?,department=?,designation=?,payment_details=?,base_salary=?,status=? WHERE id=?",(*employee_values(request.form),employee_id)); db().commit(); flash("Employee updated.","success"); return redirect(url_for("employees"))
        except (ValueError,sqlite3.IntegrityError) as error: flash(str(error) if isinstance(error,ValueError) else "Employee code must be unique.","danger")
    return render_template("employee_form.html",employee=employee)

@app.route("/employees/<int:employee_id>/delete",methods=["POST"])
@login_required
def delete_employee(employee_id):
    try: db().execute("DELETE FROM employees WHERE id=?",(employee_id,)); db().commit(); flash("Employee removed.","success")
    except sqlite3.IntegrityError: flash("This employee has payroll history; mark them inactive instead.","warning")
    return redirect(url_for("employees"))

@app.route("/payrolls")
@login_required
def payrolls():
    period_filter,q=request.args.get("period",""),request.args.get("q","").strip(); clauses=[]; params=[]
    if period_filter: clauses.append("p.pay_period=?");params.append(period_filter)
    if q: clauses.append("(e.full_name LIKE ? OR e.employee_code LIKE ?)");params += [f"%{q}%"]*2
    sql="SELECT p.*,e.full_name,e.employee_code,e.department FROM payrolls p JOIN employees e ON e.id=p.employee_id"+(" WHERE "+" AND ".join(clauses) if clauses else "")+" ORDER BY p.pay_period DESC,e.full_name"
    return render_template("payrolls.html",payrolls=db().execute(sql,params).fetchall(),period_filter=period_filter,query=q)

@app.route("/payrolls/new",methods=["GET","POST"])
@login_required
def new_payroll():
    employees=db().execute("SELECT * FROM employees WHERE status='active' ORDER BY full_name").fetchall()
    if not employees: flash("Add an active employee before creating payroll.","warning");return redirect(url_for("new_employee"))
    if request.method=="POST":
        try:
            employee=db().execute("SELECT * FROM employees WHERE id=? AND status='active'",(int(request.form.get("employee_id","")),)).fetchone()
            if not employee: raise ValueError("Choose an active employee.")
            values=payroll_values(request.form,employee)
            db().execute("""INSERT INTO payrolls(employee_id,pay_period,base_salary,working_days,paid_leave_days,unpaid_leave_days,leave_deduction,overtime_hours,overtime_rate_percent,overtime_pay,allowances,deductions,tax_rate_percent,tax,gross_salary,net_salary)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(employee["id"],values[0],employee["base_salary"],*values[1:]));db().commit();payroll_id=db().execute("SELECT last_insert_rowid()").fetchone()[0];flash("Payroll record created.","success");return redirect(url_for("payslip",payroll_id=payroll_id))
        except (ValueError,sqlite3.IntegrityError) as error: flash(str(error) if isinstance(error,ValueError) else "A payroll record already exists for this employee and period.","danger")
    return render_template("payroll_form.html",employees=employees,current_period=datetime.now().strftime("%Y-%m"))

@app.route("/payrolls/<int:payroll_id>/payslip")
@login_required
def payslip(payroll_id):
    payroll=db().execute("SELECT p.*,e.employee_code,e.full_name,e.department,e.designation,e.payment_details FROM payrolls p JOIN employees e ON e.id=p.employee_id WHERE p.id=?",(payroll_id,)).fetchone()
    if not payroll: flash("Payslip not found.","danger");return redirect(url_for("payrolls"))
    return render_template("payslip.html",payroll=payroll)

@app.route("/payrolls/export.csv")
@login_required
def export_payrolls():
    period=request.args.get("period",""); rows=db().execute("SELECT p.pay_period,e.employee_code,e.full_name,e.department,p.base_salary,p.paid_leave_days,p.unpaid_leave_days,p.leave_deduction,p.overtime_hours,p.overtime_rate_percent,p.overtime_pay,p.allowances,p.deductions,p.tax_rate_percent,p.tax,p.net_salary FROM payrolls p JOIN employees e ON e.id=p.employee_id WHERE (?='' OR p.pay_period=?) ORDER BY p.pay_period,e.full_name",(period,period)).fetchall(); output=StringIO(); writer=csv.writer(output);writer.writerow(["Pay Period","Employee Code","Employee","Department","Base Salary","Paid Leave Days","Unpaid Leave Days","Leave Deduction","Overtime Hours","Overtime Rate %","Overtime Pay","Allowances","Deductions","Tax Rate %","Tax","Net Salary"]);writer.writerows(map(tuple,rows));return Response(output.getvalue(),mimetype="text/csv",headers={"Content-Disposition":f"attachment; filename=payroll-{period or 'all-periods'}.csv"})

@app.route("/reports")
@login_required
def reports():
    monthly=db().execute("SELECT pay_period,COUNT(*) record_count,SUM(base_salary) gross_base,SUM(allowances+overtime_pay) allowances,SUM(leave_deduction+deductions+tax) withholdings,SUM(net_salary) net_total FROM payrolls GROUP BY pay_period ORDER BY pay_period DESC").fetchall();return render_template("reports.html",monthly=monthly)

with app.app_context(): init_db()
if __name__ == "__main__": app.run(host="127.0.0.1",port=5000,debug=os.environ.get("FLASK_DEBUG")=="1")
