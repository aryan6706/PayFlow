from datetime import datetime
from functools import wraps
import os
import secrets
import sqlite3

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "PAYFLOW_SECRET_KEY",
    "mits-du-payflow-demo-key-change-before-deployment",
)

app.config["DATABASE"] = os.path.join(
    "/tmp",
    "payroll.db",
)

app.config["ADMIN_USERNAME"] = os.environ.get(
    "PAYFLOW_ADMIN_USERNAME",
    "admin",
)

app.config["ADMIN_PASSWORD_HASH"] = generate_password_hash(
    os.environ.get("PAYFLOW_ADMIN_PASSWORD", "admin123"),
    method="pbkdf2:sha256",
)


# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")

    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)

    if db is not None:
        db.close()


def init_db():
    db = get_db()

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            designation TEXT NOT NULL,
            basic_salary REAL NOT NULL CHECK(basic_salary >= 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS payrolls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            pay_month TEXT NOT NULL,
            basic_salary REAL NOT NULL,

            working_days INTEGER NOT NULL DEFAULT 26,
            present_days INTEGER NOT NULL DEFAULT 26,
            leave_days INTEGER NOT NULL DEFAULT 0,

            allowances REAL NOT NULL DEFAULT 0,

            -- Total deductions retained for compatibility
            deductions REAL NOT NULL DEFAULT 0,

            -- Automated deduction components
            pf_rate REAL NOT NULL DEFAULT 12,
            pf_amount REAL NOT NULL DEFAULT 0,
            professional_tax REAL NOT NULL DEFAULT 200,
            other_deductions REAL NOT NULL DEFAULT 0,

            overtime_hours REAL NOT NULL DEFAULT 0,
            overtime_rate REAL NOT NULL DEFAULT 0,
            overtime_pay REAL NOT NULL DEFAULT 0,

            net_salary REAL NOT NULL,

            generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (employee_id) REFERENCES employees(id),
            UNIQUE(employee_id, pay_month)
        );
        """
    )

    # -----------------------------------------------------
    # Migration for older PayFlow databases
    # -----------------------------------------------------

    columns = {
        row["name"]
        for row in db.execute(
            "PRAGMA table_info(payrolls)"
        ).fetchall()
    }

    migrations = [
        (
            "working_days",
            "ALTER TABLE payrolls ADD COLUMN "
            "working_days INTEGER NOT NULL DEFAULT 26",
        ),
        (
            "present_days",
            "ALTER TABLE payrolls ADD COLUMN "
            "present_days INTEGER NOT NULL DEFAULT 26",
        ),
        (
            "leave_days",
            "ALTER TABLE payrolls ADD COLUMN "
            "leave_days INTEGER NOT NULL DEFAULT 0",
        ),
        (
            "pf_rate",
            "ALTER TABLE payrolls ADD COLUMN "
            "pf_rate REAL NOT NULL DEFAULT 12",
        ),
        (
            "pf_amount",
            "ALTER TABLE payrolls ADD COLUMN "
            "pf_amount REAL NOT NULL DEFAULT 0",
        ),
        (
            "professional_tax",
            "ALTER TABLE payrolls ADD COLUMN "
            "professional_tax REAL NOT NULL DEFAULT 200",
        ),
        (
            "other_deductions",
            "ALTER TABLE payrolls ADD COLUMN "
            "other_deductions REAL NOT NULL DEFAULT 0",
        ),
    ]

    for column_name, sql in migrations:
        if column_name not in columns:
            db.execute(sql)

    db.commit()


# ---------------------------------------------------------
# AUTHENTICATION
# ---------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapped


# ---------------------------------------------------------
# TEMPLATE HELPERS
# ---------------------------------------------------------

def money(value):
    return f"₹{value:,.2f}"


app.jinja_env.filters["money"] = money

app.jinja_env.filters["month_name"] = (
    lambda value: datetime.strptime(
        value,
        "%Y-%m"
    ).strftime("%B %Y")
)


@app.context_processor
def inject_template_utilities():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(24)

    return {
        "csrf_token": session["csrf_token"],
        "current_year": datetime.now().year,
    }


# ---------------------------------------------------------
# CSRF PROTECTION
# ---------------------------------------------------------

@app.before_request
def protect_forms():
    if (
        request.method == "POST"
        and request.form.get("csrf_token")
        != session.get("csrf_token")
    ):
        flash(
            "Your form session expired. Please try again.",
            "warning",
        )

        return redirect(
            request.referrer or url_for("index")
        )


# ---------------------------------------------------------
# VALIDATION HELPERS
# ---------------------------------------------------------

def valid_text(value):
    """Require a short, non-blank text value."""
    return bool(
        value
        and value.strip()
        and len(value.strip()) <= 100
    )


def employee_values(form):
    """Read and validate employee data before SQLite."""

    values = tuple(
        form.get(field, "").strip()
        for field in (
            "employee_code",
            "name",
            "department",
            "designation",
        )
    )

    salary = float(
        form.get("basic_salary", "")
    )

    if (
        not all(valid_text(value) for value in values)
        or salary < 0
    ):
        raise ValueError

    return (*values, salary)


# ---------------------------------------------------------
# PAYROLL CALCULATION
# ---------------------------------------------------------

def payroll_values(form, employee):
    """
    Calculate payroll using attendance, allowances,
    automated deductions, other deductions and overtime.

    PF and Professional Tax are configurable demo rules.
    They are not intended to represent legal/tax compliance.
    """

    pay_month = form.get("pay_month", "")

    working_days = int(
        form.get("working_days", 26) or 26
    )

    present_days = int(
        form.get("present_days", 26) or 26
    )

    leave_days = int(
        form.get("leave_days", 0) or 0
    )

    allowances = float(
        form.get("allowances", 0) or 0
    )

    pf_rate = float(
        form.get("pf_rate", 12) or 12
    )

    professional_tax = float(
        form.get("professional_tax", 200) or 200
    )

    # The current form calls this field "deductions".
    # It represents Other Deductions.
    other_deductions = float(
        form.get("deductions", 0) or 0
    )

    overtime_hours = float(
        form.get("overtime_hours", 0) or 0
    )

    overtime_rate = float(
        form.get("overtime_rate", 0) or 0
    )

    # -----------------------------------------------------
    # Validation
    # -----------------------------------------------------

    if (
        not employee
        or len(pay_month) != 7
        or working_days <= 0
        or present_days < 0
        or leave_days < 0
        or present_days > working_days
        or leave_days > working_days
        or present_days + leave_days > working_days
        or pf_rate < 0
        or pf_rate > 100
        or min(
            allowances,
            professional_tax,
            other_deductions,
            overtime_hours,
            overtime_rate,
        ) < 0
    ):
        raise ValueError

    # -----------------------------------------------------
    # Attendance-based salary
    # -----------------------------------------------------

    daily_salary = (
        employee["basic_salary"] / working_days
    )

    attendance_salary = (
        daily_salary * present_days
    )

    # -----------------------------------------------------
    # Overtime
    # -----------------------------------------------------

    overtime_pay = (
        overtime_hours * overtime_rate
    )

    # -----------------------------------------------------
    # Automated deductions
    # -----------------------------------------------------

    pf_amount = (
        attendance_salary * pf_rate / 100
    )

    total_deductions = (
        pf_amount
        + professional_tax
        + other_deductions
    )

    # -----------------------------------------------------
    # Final salary
    # -----------------------------------------------------

    net_salary = (
        attendance_salary
        + allowances
        + overtime_pay
        - total_deductions
    )

    if net_salary < 0:
        raise ValueError

    return (
        pay_month,
        working_days,
        present_days,
        leave_days,
        allowances,
        pf_rate,
        pf_amount,
        professional_tax,
        other_deductions,
        total_deductions,
        overtime_hours,
        overtime_rate,
        overtime_pay,
        net_salary,
    )


# ---------------------------------------------------------
# HOME
# ---------------------------------------------------------

@app.route("/")
def index():
    return redirect(
        url_for("dashboard")
        if session.get("user")
        else url_for("login")
    )


# ---------------------------------------------------------
# LOGIN
# ---------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        if (
            request.form.get("username")
            == app.config["ADMIN_USERNAME"]
            and check_password_hash(
                app.config["ADMIN_PASSWORD_HASH"],
                request.form.get("password", ""),
            )
        ):

            session["user"] = "Payroll Administrator"

            return redirect(
                url_for("dashboard")
            )

        flash(
            "Invalid login. Try the demo credentials shown below.",
            "danger",
        )

    return render_template("login.html")


@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# ---------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():

    db = get_db()

    employee_count = db.execute(
        "SELECT COUNT(*) FROM employees"
    ).fetchone()[0]

    payroll_count = db.execute(
        "SELECT COUNT(*) FROM payrolls"
    ).fetchone()[0]

    total_paid = db.execute(
        "SELECT COALESCE(SUM(net_salary), 0) FROM payrolls"
    ).fetchone()[0]

    current_month = datetime.now().strftime("%Y-%m")

    current_month_paid = db.execute(
        """
        SELECT COALESCE(SUM(net_salary), 0)
        FROM payrolls
        WHERE pay_month = ?
        """,
        (current_month,),
    ).fetchone()[0]

    department_count = db.execute(
        "SELECT COUNT(DISTINCT department) FROM employees"
    ).fetchone()[0]

    recent = db.execute(
        """
        SELECT p.*, e.name, e.employee_code
        FROM payrolls p
        JOIN employees e
            ON e.id = p.employee_id
        ORDER BY p.generated_at DESC
        LIMIT 5
        """
    ).fetchall()

    return render_template(
        "dashboard.html",
        employee_count=employee_count,
        payroll_count=payroll_count,
        total_paid=total_paid,
        current_month_paid=current_month_paid,
        department_count=department_count,
        current_month=current_month,
        recent=recent,
    )


# ---------------------------------------------------------
# EMPLOYEES
# ---------------------------------------------------------

@app.route("/employees")
@login_required
def employees():

    query = request.args.get(
        "q",
        "",
    ).strip()

    rows = get_db().execute(
        """
        SELECT *
        FROM employees
        WHERE employee_code LIKE ?
           OR name LIKE ?
           OR department LIKE ?
           OR designation LIKE ?
        ORDER BY name
        """,
        tuple(
            f"%{query}%"
            for _ in range(4)
        ),
    ).fetchall()

    return render_template(
        "employees.html",
        employees=rows,
        query=query,
    )


@app.route("/employees/<int:employee_id>")
@login_required
def employee_detail(employee_id):

    db = get_db()

    employee = db.execute(
        "SELECT * FROM employees WHERE id = ?",
        (employee_id,),
    ).fetchone()

    if employee is None:

        flash(
            "Employee not found.",
            "danger",
        )

        return redirect(
            url_for("employees")
        )

    history = db.execute(
        """
        SELECT *
        FROM payrolls
        WHERE employee_id = ?
        ORDER BY pay_month DESC
        """,
        (employee_id,),
    ).fetchall()

    total_paid = sum(
        record["net_salary"]
        for record in history
    )

    return render_template(
        "employee_detail.html",
        employee=employee,
        history=history,
        total_paid=total_paid,
    )


@app.route("/employees/add", methods=["GET", "POST"])
@login_required
def add_employee():

    if request.method == "POST":

        try:

            db = get_db()

            db.execute(
                """
                INSERT INTO employees
                (
                    employee_code,
                    name,
                    department,
                    designation,
                    basic_salary
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                employee_values(request.form),
            )

            db.commit()

            flash(
                "Employee added successfully.",
                "success",
            )

            return redirect(
                url_for("employees")
            )

        except (
            ValueError,
            sqlite3.IntegrityError,
        ):

            flash(
                "Please use a unique employee ID and a valid salary.",
                "danger",
            )

    return render_template(
        "employee_form.html",
        employee=None,
    )


@app.route(
    "/employees/<int:employee_id>/edit",
    methods=["GET", "POST"],
)
@login_required
def edit_employee(employee_id):

    db = get_db()

    employee = db.execute(
        "SELECT * FROM employees WHERE id = ?",
        (employee_id,),
    ).fetchone()

    if employee is None:

        flash(
            "Employee not found.",
            "danger",
        )

        return redirect(
            url_for("employees")
        )

    if request.method == "POST":

        try:

            db.execute(
                """
                UPDATE employees
                SET employee_code=?,
                    name=?,
                    department=?,
                    designation=?,
                    basic_salary=?
                WHERE id=?
                """,
                (
                    *employee_values(request.form),
                    employee_id,
                ),
            )

            db.commit()

            flash(
                "Employee details updated.",
                "success",
            )

            return redirect(
                url_for("employees")
            )

        except (
            ValueError,
            sqlite3.IntegrityError,
        ):

            flash(
                "Please use a unique employee ID and a valid salary.",
                "danger",
            )

    return render_template(
        "employee_form.html",
        employee=employee,
    )


@app.route(
    "/employees/<int:employee_id>/delete",
    methods=["POST"],
)
@login_required
def delete_employee(employee_id):

    db = get_db()

    db.execute(
        "DELETE FROM payrolls WHERE employee_id = ?",
        (employee_id,),
    )

    db.execute(
        "DELETE FROM employees WHERE id = ?",
        (employee_id,),
    )

    db.commit()

    flash(
        "Employee and related payroll records removed.",
        "success",
    )

    return redirect(
        url_for("employees")
    )


# ---------------------------------------------------------
# DEMO DATA
# ---------------------------------------------------------

@app.route("/demo-data", methods=["POST"])
@login_required
def demo_data():

    db = get_db()

    if db.execute(
        "SELECT COUNT(*) FROM employees"
    ).fetchone()[0]:

        flash(
            "Demo data was not added because employee records already exist.",
            "info",
        )

        return redirect(
            url_for("dashboard")
        )

    staff = [
        (
            "MITS-101",
            "Aarav Sharma",
            "Information Technology",
            "Systems Analyst",
            48000,
        ),
        (
            "MITS-102",
            "Ananya Verma",
            "Finance",
            "Accounts Executive",
            42000,
        ),
        (
            "MITS-103",
            "Rohan Mehta",
            "Human Resources",
            "HR Coordinator",
            38000,
        ),
    ]

    db.executemany(
        """
        INSERT INTO employees
        (
            employee_code,
            name,
            department,
            designation,
            basic_salary
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        staff,
    )

    db.commit()

    flash(
        "Three MITS DU sample employees are ready. Generate payroll to complete the demo.",
        "success",
    )

    return redirect(
        url_for("dashboard")
    )


# ---------------------------------------------------------
# PAYROLL LIST
# ---------------------------------------------------------

@app.route("/payrolls")
@login_required
def payrolls():

    rows = get_db().execute(
        """
        SELECT
            p.*,
            e.name,
            e.employee_code,
            e.department
        FROM payrolls p
        JOIN employees e
            ON e.id = p.employee_id
        ORDER BY
            p.pay_month DESC,
            p.id DESC
        """
    ).fetchall()

    return render_template(
        "payrolls.html",
        payrolls=rows,
    )


# ---------------------------------------------------------
# GENERATE PAYROLL
# ---------------------------------------------------------

@app.route(
    "/payrolls/generate",
    methods=["GET", "POST"],
)
@login_required
def generate_payroll():

    db = get_db()

    employees = db.execute(
        "SELECT * FROM employees ORDER BY name"
    ).fetchall()

    if not employees:

        flash(
            "Add an employee before generating payroll.",
            "warning",
        )

        return redirect(
            url_for("add_employee")
        )

    if request.method == "POST":

        try:

            employee_id = int(
                request.form["employee_id"]
            )

            employee = db.execute(
                """
                SELECT *
                FROM employees
                WHERE id = ?
                """,
                (employee_id,),
            ).fetchone()

            (
                pay_month,
                working_days,
                present_days,
                leave_days,
                allowances,
                pf_rate,
                pf_amount,
                professional_tax,
                other_deductions,
                total_deductions,
                overtime_hours,
                overtime_rate,
                overtime_pay,
                net_salary,
            ) = payroll_values(
                request.form,
                employee,
            )

            db.execute(
                """
                INSERT INTO payrolls
                (
                    employee_id,
                    pay_month,
                    basic_salary,
                    working_days,
                    present_days,
                    leave_days,
                    allowances,
                    deductions,
                    pf_rate,
                    pf_amount,
                    professional_tax,
                    other_deductions,
                    overtime_hours,
                    overtime_rate,
                    overtime_pay,
                    net_salary
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    pay_month,
                    employee["basic_salary"],
                    working_days,
                    present_days,
                    leave_days,
                    allowances,
                    total_deductions,
                    pf_rate,
                    pf_amount,
                    professional_tax,
                    other_deductions,
                    overtime_hours,
                    overtime_rate,
                    overtime_pay,
                    net_salary,
                ),
            )

            db.commit()

            payroll_id = db.execute(
                "SELECT last_insert_rowid()"
            ).fetchone()[0]

            flash(
                "Payroll generated successfully.",
                "success",
            )

            return redirect(
                url_for(
                    "payslip",
                    payroll_id=payroll_id,
                )
            )

        except (
            ValueError,
            sqlite3.IntegrityError,
        ):

            flash(
                "Use valid attendance values and non-negative amounts. "
                "PF rate must be between 0 and 100. "
                "Present days and leave days cannot exceed working days. "
                "Each employee can have one payroll per month.",
                "danger",
            )

    return render_template(
        "payroll_form.html",
        employees=employees,
        current_month=datetime.now().strftime("%Y-%m"),
    )


# ---------------------------------------------------------
# EDIT PAYROLL
# ---------------------------------------------------------

@app.route(
    "/payrolls/<int:payroll_id>/edit",
    methods=["GET", "POST"],
)
@login_required
def edit_payroll(payroll_id):

    db = get_db()

    payroll = db.execute(
        """
        SELECT *
        FROM payrolls
        WHERE id = ?
        """,
        (payroll_id,),
    ).fetchone()

    if payroll is None:

        flash(
            "Payroll record not found.",
            "danger",
        )

        return redirect(
            url_for("payrolls")
        )

    employee = db.execute(
        """
        SELECT *
        FROM employees
        WHERE id = ?
        """,
        (payroll["employee_id"],),
    ).fetchone()

    if request.method == "POST":

        try:

            (
                pay_month,
                working_days,
                present_days,
                leave_days,
                allowances,
                pf_rate,
                pf_amount,
                professional_tax,
                other_deductions,
                total_deductions,
                overtime_hours,
                overtime_rate,
                overtime_pay,
                net_salary,
            ) = payroll_values(
                request.form,
                employee,
            )

            db.execute(
                """
                UPDATE payrolls
                SET
                    pay_month=?,
                    basic_salary=?,
                    working_days=?,
                    present_days=?,
                    leave_days=?,
                    allowances=?,
                    deductions=?,
                    pf_rate=?,
                    pf_amount=?,
                    professional_tax=?,
                    other_deductions=?,
                    overtime_hours=?,
                    overtime_rate=?,
                    overtime_pay=?,
                    net_salary=?
                WHERE id=?
                """,
                (
                    pay_month,
                    employee["basic_salary"],
                    working_days,
                    present_days,
                    leave_days,
                    allowances,
                    total_deductions,
                    pf_rate,
                    pf_amount,
                    professional_tax,
                    other_deductions,
                    overtime_hours,
                    overtime_rate,
                    overtime_pay,
                    net_salary,
                    payroll_id,
                ),
            )

            db.commit()

            flash(
                "Payroll record updated.",
                "success",
            )

            return redirect(
                url_for(
                    "payslip",
                    payroll_id=payroll_id,
                )
            )

        except (
            ValueError,
            sqlite3.IntegrityError,
        ):

            flash(
                "Use valid attendance values and non-negative amounts. "
                "PF rate must be between 0 and 100. "
                "This employee may already have a payroll for that month.",
                "danger",
            )

    return render_template(
        "payroll_form.html",
        employees=[employee],
        payroll=payroll,
        current_month=payroll["pay_month"],
        editing=True,
    )


# ---------------------------------------------------------
# DELETE PAYROLL
# ---------------------------------------------------------

@app.route(
    "/payrolls/<int:payroll_id>/delete",
    methods=["POST"],
)
@login_required
def delete_payroll(payroll_id):

    db = get_db()

    db.execute(
        "DELETE FROM payrolls WHERE id = ?",
        (payroll_id,),
    )

    db.commit()

    flash(
        "Payroll record removed.",
        "success",
    )

    return redirect(
        url_for("payrolls")
    )


# ---------------------------------------------------------
# REPORTS
# ---------------------------------------------------------

@app.route("/reports")
@login_required
def reports():

    db = get_db()

    departments = db.execute(
        """
        SELECT
            e.department,
            COUNT(DISTINCT e.id) AS employee_count,
            COUNT(p.id) AS payroll_count,
            COALESCE(SUM(p.net_salary), 0) AS total_paid
        FROM employees e
        LEFT JOIN payrolls p
            ON p.employee_id = e.id
        GROUP BY e.department
        ORDER BY total_paid DESC, e.department
        """
    ).fetchall()

    months = db.execute(
        """
        SELECT
            pay_month,
            COUNT(*) AS payroll_count,
            COALESCE(SUM(net_salary), 0) AS total_paid
        FROM payrolls
        GROUP BY pay_month
        ORDER BY pay_month DESC
        """
    ).fetchall()

    return render_template(
        "reports.html",
        departments=departments,
        months=months,
    )


# ---------------------------------------------------------
# PAYSLIP
# ---------------------------------------------------------

@app.route(
    "/payrolls/<int:payroll_id>/payslip"
)
@login_required
def payslip(payroll_id):

    row = get_db().execute(
        """
        SELECT
            p.*,
            e.name,
            e.employee_code,
            e.department,
            e.designation
        FROM payrolls p
        JOIN employees e
            ON e.id = p.employee_id
        WHERE p.id = ?
        """,
        (payroll_id,),
    ).fetchone()

    if row is None:

        flash(
            "Payslip not found.",
            "danger",
        )

        return redirect(
            url_for("payrolls")
        )

    return render_template(
        "payslip.html",
        payroll=row,
    )


# ---------------------------------------------------------
# DATABASE INITIALIZATION
# ---------------------------------------------------------

with app.app_context():
    init_db()


# ---------------------------------------------------------
# RUN APPLICATION
# ---------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)