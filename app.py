import os
import shutil
import sqlite3
import csv
import io
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, Response, abort
)
from jinja2 import ChoiceLoader, DictLoader
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'payflow-enterprise-secret-key-9941')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IS_SERVERLESS = bool(
    os.environ.get('VERCEL')
    or os.environ.get('AWS_LAMBDA_FUNCTION_NAME')
    or not os.access(BASE_DIR, os.W_OK)
)

if IS_SERVERLESS:
    app.config['DATABASE'] = '/tmp/payflow_india_v3.db'
else:
    app.config['DATABASE'] = os.path.join(BASE_DIR, 'payflow_india_v3.db')

# ==============================================================================
# EMBEDDED SYNCHRONIZED TEMPLATES & STATIC ASSETS (100% immune to file mismatch)
# ==============================================================================

STYLE_CSS = """\
:root {
  --bg: #f8fafc;
  --surface: #ffffff;
  --border: #e2e8f0;
  --text: #0f172a;
  --muted: #64748b;
  --accent: #0f172a;
  --accent-hover: #1e293b;
  --danger: #dc2626;
  --success-bg: #dcfce7;
  --success-text: #166534;
  --inactive-bg: #f1f5f9;
  --inactive-text: #475569;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
.app-shell { display: flex; min-height: 100vh; }
.sidebar {
  width: 240px;
  background: #0f172a;
  color: #f8fafc;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 24px 16px;
  flex-shrink: 0;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #ffffff;
  text-decoration: none;
  font-weight: 700;
  font-size: 16px;
  padding: 0 12px 24px;
  border-bottom: 1px solid #1e293b;
}
.brand span {
  background: #ffffff;
  color: #0f172a;
  font-size: 12px;
  font-weight: 800;
  padding: 4px 7px;
  border-radius: 6px;
}
.nav-links { display: flex; flex-direction: column; gap: 4px; margin-top: 20px; }
.nav-links a {
  color: #94a3b8;
  text-decoration: none;
  padding: 10px 12px;
  border-radius: 6px;
  font-weight: 500;
  transition: all 0.15s;
}
.nav-links a:hover, .nav-links a.active { background: #1e293b; color: #ffffff; }
.sidebar-footer {
  border-top: 1px solid #1e293b;
  padding: 16px 12px 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  color: #94a3b8;
}
.sidebar-footer a { color: #f8fafc; text-decoration: underline; }
.workspace { flex: 1; padding: 36px 48px; max-width: 1200px; }
.page-title {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 28px;
  gap: 16px;
  flex-wrap: wrap;
}
.eyebrow {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 4px;
}
h1 { font-size: 24px; font-weight: 700; letter-spacing: -0.02em; }
h2 { font-size: 16px; font-weight: 600; }
.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 16px;
  margin-bottom: 28px;
}
.metrics article {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.metrics span { color: var(--muted); font-size: 13px; font-weight: 500; }
.metrics strong { font-size: 24px; font-weight: 700; letter-spacing: -0.02em; }
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 28px;
}
.panel-heading {
  padding: 18px 24px;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.form-panel { padding: 28px; }
.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 20px;
}
label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-weight: 600;
  font-size: 13px;
  color: var(--text);
}
input, select {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 14px;
  background: #ffffff;
  color: var(--text);
}
input:focus, select:focus { outline: 2px solid var(--accent); border-color: transparent; }
input[readonly] { background: #f1f5f9; color: var(--muted); }
.filters {
  display: flex;
  gap: 10px;
  padding: 16px 24px;
  border-bottom: 1px solid var(--border);
  background: #fcfcfd;
  flex-wrap: wrap;
}
.filters input { flex: 1; min-width: 200px; }
.table-responsive { width: 100%; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td {
  padding: 14px 24px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
th {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  background: #f8fafc;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
tr:last-child td { border-bottom: none; }
td small { display: block; color: var(--muted); font-size: 12px; font-weight: 400; }
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 9px 16px;
  border-radius: 6px;
  font-weight: 600;
  font-size: 13px;
  text-decoration: none;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.15s;
}
.btn-dark { background: var(--accent); color: #ffffff; }
.btn-dark:hover { background: var(--accent-hover); }
.btn-light { background: #ffffff; border-color: var(--border); color: var(--text); }
.btn-light:hover { background: #f1f5f9; }
.status {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  text-transform: capitalize;
}
.status.Active, .status.active, .status.Paid { background: var(--success-bg); color: var(--success-text); }
.status.Inactive, .status.inactive, .status.Pending, .status.Processed { background: var(--inactive-bg); color: var(--inactive-text); }
.actions { display: flex; gap: 12px; align-items: center; justify-content: flex-end; }
.text-link { color: var(--text); font-weight: 600; text-decoration: underline; font-size: 13px; }
.link-danger {
  background: none;
  border: none;
  color: var(--danger);
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
  text-decoration: underline;
}
.empty { text-align: center; color: var(--muted); padding: 36px !important; }
.net-preview {
  margin-top: 24px;
  padding: 16px 20px;
  background: #f8fafc;
  border: 1px solid var(--border);
  border-radius: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 15px;
}
.net-preview strong { font-size: 20px; font-weight: 700; }
.form-actions { margin-top: 24px; display: flex; justify-content: flex-end; gap: 10px; }
.alert {
  padding: 12px 16px;
  border-radius: 8px;
  margin-bottom: 20px;
  font-weight: 500;
  font-size: 13px;
  border: 1px solid transparent;
}
.alert-success { background: #dcfce7; color: #166534; border-color: #bbf7d0; }
.alert-danger { background: #fee2e2; color: #991b1b; border-color: #fecaca; }
.alert-warning { background: #fef9c3; color: #854d0e; border-color: #fef08a; }
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.login-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 36px;
  width: 100%;
  max-width: 400px;
}
@media print {
  .no-print, .sidebar { display: none !important; }
  .workspace { padding: 0; max-width: 100%; }
  .panel { border: 1px solid #000; }
}
"""

TEMPLATES = {
    "base.html": """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}PayFlow{% endblock %}</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
  {% if session.user_id %}
  <div class="app-shell">
    <aside class="sidebar no-print">
      <div>
        <a class="brand" href="{{ url_for('dashboard') }}"><span>PF</span>PayFlow</a>
        <nav class="nav-links">
          <a href="{{ url_for('dashboard') }}" class="{% if request.endpoint == 'dashboard' %}active{% endif %}">Overview</a>
          <a href="{{ url_for('employees') }}" class="{% if 'employee' in (request.endpoint or '') %}active{% endif %}">Employees</a>
          <a href="{{ url_for('payrolls') }}" class="{% if 'payroll' in (request.endpoint or '') or request.endpoint == 'payslip' %}active{% endif %}">Payroll ledger</a>
          <a href="{{ url_for('reports') }}" class="{% if request.endpoint == 'reports' %}active{% endif %}">Reports</a>
        </nav>
      </div>
      <div class="sidebar-footer">
        <span>{{ session.username }}</span>
        <a href="{{ url_for('logout') }}">Sign out</a>
      </div>
    </aside>
    <main class="workspace">
      {% with messages = get_flashed_messages(with_categories=true) %}
        {% for category, message in messages %}
          <div class="alert alert-{{ category }} no-print">{{ message }}</div>
        {% endfor %}
      {% endwith %}
      {% block content %}{% endblock %}
    </main>
  </div>
  {% else %}
  <main class="login-page">
    {% block auth_content %}{% endblock %}
  </main>
  {% endif %}
</body>
</html>
""",
    "login.html": """\
{% extends 'base.html' %}
{% block title %}Sign in · PayFlow{% endblock %}
{% block auth_content %}
<div class="login-card">
  <p class="eyebrow">INDIAN PAYROLL MANAGEMENT</p>
  <h1 style="margin-bottom: 6px;">PayFlow</h1>
  <p style="color: var(--muted); margin-bottom: 24px;">Sign in to access your payroll workspace (Default: admin / admin123).</p>
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for category, message in messages %}
      <div class="alert alert-{{ category }}">{{ message }}</div>
    {% endfor %}
  {% endwith %}
  <form method="post" style="display: flex; flex-direction: column; gap: 16px;">
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    <label>Username
      <input type="text" name="username" value="admin" required autofocus>
    </label>
    <label>Password
      <input type="password" name="password" value="admin123" required>
    </label>
    <button type="submit" class="btn btn-dark" style="margin-top: 8px; width: 100%;">Sign in</button>
  </form>
</div>
{% endblock %}
""",
    "dashboard.html": """\
{% extends 'base.html' %}
{% block title %}Overview · PayFlow{% endblock %}
{% block content %}
<div class="page-title">
  <div>
    <p class="eyebrow">PAYROLL OPERATIONS (INR)</p>
    <h1>Overview</h1>
    <p style="color: var(--muted);">Manage employee salaries, PF, TDS, and disbursements in Indian Rupees (₹).</p>
  </div>
  <div style="display: flex; gap: 10px;">
    <a class="btn btn-light" href="{{ url_for('new_employee') }}">Add employee</a>
    <a class="btn btn-dark" href="{{ url_for('new_payroll') }}">New payroll record</a>
  </div>
</div>

<div class="metrics">
  <article>
    <span>Active employees</span>
    <strong>{{ stats.employees }}</strong>
  </article>
  <article>
    <span>Payroll records</span>
    <strong>{{ stats.runs }}</strong>
  </article>
  <article>
    <span>{{ current_period|period }} net pay</span>
    <strong>{{ stats.current_total|money }}</strong>
  </article>
  <article>
    <span>Total disbursed</span>
    <strong>{{ stats.total_paid|money }}</strong>
  </article>
</div>

<section class="panel">
  <div class="panel-heading">
    <div>
      <p class="eyebrow">RECENT ACTIVITY</p>
      <h2>Latest payroll records</h2>
    </div>
    <a class="text-link" href="{{ url_for('payrolls') }}">View full ledger</a>
  </div>
  <div class="table-responsive">
    <table>
      <thead>
        <tr>
          <th>Employee</th>
          <th>Department</th>
          <th>Pay period</th>
          <th>Net salary (₹)</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% for p in recent %}
        <tr>
          <td>
            <strong>{{ p.full_name }}</strong>
            <small>{{ p.employee_code }}</small>
          </td>
          <td>{{ p.department }}</td>
          <td>{{ p.pay_period|period }}</td>
          <td><strong>{{ p.net_salary|money }}</strong></td>
          <td class="actions">
            <a class="text-link" href="{{ url_for('payslip', payroll_id=p.id) }}">Payslip</a>
          </td>
        </tr>
        {% else %}
        <tr>
          <td colspan="5" class="empty">No payroll records yet.</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</section>
{% endblock %}
""",
    "employees.html": """\
{% extends 'base.html' %}
{% block title %}Employees · PayFlow{% endblock %}
{% block content %}
<div class="page-title">
  <div>
    <p class="eyebrow">DIRECTORY</p>
    <h1>Employees</h1>
    <p style="color: var(--muted);">Active and inactive organization personnel.</p>
  </div>
  <a class="btn btn-dark" href="{{ url_for('new_employee') }}">Add employee</a>
</div>

<section class="panel">
  <form class="filters" method="get">
    <input name="q" value="{{ query }}" placeholder="Search by name, employee code, or department...">
    <select name="status">
      <option value="">All statuses</option>
      <option value="Active" {% if status|lower == 'active' %}selected{% endif %}>Active</option>
      <option value="Inactive" {% if status|lower == 'inactive' %}selected{% endif %}>Inactive</option>
    </select>
    <button type="submit" class="btn btn-light">Filter</button>
  </form>
  <div class="table-responsive">
    <table>
      <thead>
        <tr>
          <th>Employee</th>
          <th>Department</th>
          <th>Designation</th>
          <th>Basic salary (₹)</th>
          <th>Status</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% for e in employees %}
        <tr>
          <td>
            <strong>{{ e.full_name }}</strong>
            <small>{{ e.employee_code }}</small>
          </td>
          <td>{{ e.department }}</td>
          <td>{{ e.designation }}</td>
          <td><strong>{{ e.base_salary|money }}</strong></td>
          <td><span class="status {{ e.status }}">{{ e.status }}</span></td>
          <td class="actions">
            <a class="text-link" href="{{ url_for('edit_employee', employee_id=e.id) }}">Edit</a>
            <form method="post" action="{{ url_for('delete_employee', employee_id=e.id) }}" style="display:inline;">
              <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
              <button type="submit" class="link-danger" onclick="return confirm('Remove this employee?')">Remove</button>
            </form>
          </td>
        </tr>
        {% else %}
        <tr>
          <td colspan="6" class="empty">No employees found. Click "Add employee" to create a record.</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</section>
{% endblock %}
""",
    "employee_form.html": """\
{% extends 'base.html' %}
{% block title %}{{ 'Edit' if employee else 'Add' }} employee · PayFlow{% endblock %}
{% block content %}
<div class="page-title">
  <div>
    <p class="eyebrow">DIRECTORY</p>
    <h1>{{ 'Edit employee' if employee else 'Add employee' }}</h1>
  </div>
  <a class="btn btn-light" href="{{ url_for('employees') }}">Cancel</a>
</div>

<section class="panel form-panel">
  <form method="post">
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    <div class="form-grid">
      <label>Employee code
        <input type="text" name="employee_code" value="{{ employee.employee_code if employee else next_code }}" placeholder="e.g. EMP005" required>
      </label>
      <label>Full name
        <input type="text" name="full_name" value="{{ employee.full_name if employee else '' }}" placeholder="e.g. Vikramaditya Rao" required>
      </label>
      <label>Department
        <input type="text" name="department" value="{{ employee.department if employee else 'Engineering' }}" placeholder="e.g. Engineering" required>
      </label>
      <label>Designation
        <input type="text" name="designation" value="{{ employee.designation if employee else 'Software Engineer' }}" placeholder="e.g. Senior Developer" required>
      </label>
      <label>Monthly basic salary (₹)
        <input type="number" min="0" step="0.01" name="base_salary" value="{{ employee.base_salary if employee else '65000' }}" placeholder="e.g. 65000" required>
      </label>
      <label>Payment details (Bank / IFSC / A/C)
        <input type="text" name="payment_details" value="{{ employee.payment_details if employee else 'HDFC Bank · NEFT' }}" placeholder="e.g. SBI / HDFC · IFSC" required>
      </label>
      <label>Status
        <select name="status">
          <option value="Active" {% if not employee or employee.status|lower == 'active' %}selected{% endif %}>Active</option>
          <option value="Inactive" {% if employee and employee.status|lower == 'inactive' %}selected{% endif %}>Inactive</option>
        </select>
      </label>
    </div>
    <div class="form-actions">
      <button type="submit" class="btn btn-dark">Save employee</button>
    </div>
  </form>
</section>
{% endblock %}
""",
    "payrolls.html": """\
{% extends 'base.html' %}
{% block title %}Payroll ledger · PayFlow{% endblock %}
{% block content %}
<div class="page-title">
  <div>
    <p class="eyebrow">DISBURSEMENTS</p>
    <h1>Payroll ledger</h1>
    <p style="color: var(--muted);">Complete salary register and printable payslip records in ₹.</p>
  </div>
  <div style="display: flex; gap: 10px;">
    <a class="btn btn-light" href="{{ url_for('export_payrolls', period=period) }}">Export CSV</a>
    <a class="btn btn-dark" href="{{ url_for('new_payroll') }}">New payroll record</a>
  </div>
</div>

<section class="panel">
  <form class="filters" method="get">
    <input type="month" name="period" value="{{ period }}" style="max-width: 220px;">
    <button type="submit" class="btn btn-light">Filter month</button>
    {% if period %}
      <a class="btn btn-light" href="{{ url_for('payrolls') }}">Show all</a>
    {% endif %}
  </form>
  <div class="table-responsive">
    <table>
      <thead>
        <tr>
          <th>Employee</th>
          <th>Pay period</th>
          <th>Basic (₹)</th>
          <th>HRA / Allowances (₹)</th>
          <th>PF / Deductions (₹)</th>
          <th>TDS / Tax (₹)</th>
          <th>Net salary (₹)</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% for r in records %}
        <tr>
          <td>
            <strong>{{ r.full_name }}</strong>
            <small>{{ r.employee_code }} · {{ r.department }}</small>
          </td>
          <td>{{ r.pay_period|period }}</td>
          <td>{{ r.base_salary|money }}</td>
          <td>{{ r.allowances|money }}</td>
          <td>{{ r.deductions|money }}</td>
          <td>{{ r.tax|money }}</td>
          <td><strong>{{ r.net_salary|money }}</strong></td>
          <td class="actions">
            <a class="text-link" href="{{ url_for('payslip', payroll_id=r.id) }}">Payslip</a>
            <form method="post" action="{{ url_for('delete_payroll', payroll_id=r.id) }}" style="display:inline;">
              <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
              <button type="submit" class="link-danger" onclick="return confirm('Delete this payroll entry?')">Delete</button>
            </form>
          </td>
        </tr>
        {% else %}
        <tr>
          <td colspan="8" class="empty">No payroll records found for this period.</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</section>
{% endblock %}
""",
    "payroll_form.html": """\
{% extends 'base.html' %}
{% block title %}New payroll · PayFlow{% endblock %}
{% block content %}
<div class="page-title">
  <div>
    <p class="eyebrow">PAYROLL</p>
    <h1>New payroll record</h1>
    <p style="color: var(--muted);">Net salary in ₹ is calculated automatically on submission.</p>
  </div>
  <a class="btn btn-light" href="{{ url_for('payrolls') }}">Cancel</a>
</div>

<section class="panel form-panel">
  <form method="post">
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    <div class="form-grid">
      <label>Employee
        <select name="employee_id" required>
          {% for e in employees %}
            <option value="{{ e.id }}" data-base="{{ e.base_salary }}">{{ e.full_name }} · {{ e.employee_code }}</option>
          {% endfor %}
        </select>
      </label>
      <label>Pay period
        <input type="month" name="pay_period" value="{{ current_period }}" required>
      </label>
      <label>Basic salary (₹)
        <input id="base" readonly value="{{ (employees[0].base_salary if employees else 0)|money }}">
      </label>
      <label>HRA & Special Allowances (₹)
        <input class="calc" type="number" min="0" step="0.01" name="allowances" value="15000">
      </label>
      <label>PF & Other Deductions (₹)
        <input class="calc" type="number" min="0" step="0.01" name="deductions" value="3600">
      </label>
      <label>TDS / Income Tax (₹)
        <input class="calc" type="number" min="0" step="0.01" name="tax" value="4500">
      </label>
    </div>
    <div class="net-preview">
      <span>Estimated net payable salary</span>
      <strong id="net-preview">₹0.00</strong>
    </div>
    <div class="form-actions">
      <button type="submit" class="btn btn-dark">Create payroll record</button>
    </div>
  </form>
</section>

<script>
const select = document.querySelector('[name="employee_id"]');
const base = document.querySelector('#base');
const net = document.querySelector('#net-preview');
const val = name => Number(document.querySelector(`[name="${name}"]`).value) || 0;

function update() {
  if (!select || !select.selectedOptions.length) return;
  const b = Number(select.selectedOptions[0].dataset.base) || 0;
  base.value = '₹' + b.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const total = b + val('allowances') - val('deductions') - val('tax');
  net.textContent = '₹' + total.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2});
}
if (select) {
  select.onchange = update;
  document.querySelectorAll('.calc').forEach(el => el.oninput = update);
  update();
}
</script>
{% endblock %}
""",
    "payslip.html": """\
{% extends 'base.html' %}
{% block title %}Payslip · {{ item.full_name }}{% endblock %}
{% block content %}
<div class="page-title no-print">
  <div>
    <p class="eyebrow">DOCUMENT</p>
    <h1>Salary Slip</h1>
  </div>
  <div style="display: flex; gap: 10px;">
    <a class="btn btn-light" href="{{ url_for('payrolls') }}">Back to ledger</a>
    <button type="button" class="btn btn-dark" onclick="window.print()">Print / Save PDF</button>
  </div>
</div>

<section class="panel" style="padding: 36px; max-width: 820px;">
  <div style="display: flex; justify-content: space-between; border-bottom: 2px solid var(--text); padding-bottom: 20px; margin-bottom: 24px;">
    <div>
      <p class="eyebrow">OFFICIAL PAYSLIP (INDIA)</p>
      <h2 style="font-size: 22px; font-weight: 700;">PayFlow Payroll Statement</h2>
      <p style="color: var(--muted); font-size: 13px;">Reference: #PF-{{ "%04d"|format(item.id) }}</p>
    </div>
    <div style="text-align: right;">
      <p class="eyebrow">PAY PERIOD</p>
      <strong style="font-size: 16px;">{{ item.pay_period|period }}</strong>
      <p style="color: var(--muted); font-size: 12px;">Processed: {{ item.payment_date }}</p>
    </div>
  </div>

  <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 28px;">
    <div>
      <p class="eyebrow">EMPLOYEE DETAILS</p>
      <p><strong>{{ item.full_name }}</strong> ({{ item.employee_code }})</p>
      <p style="color: var(--muted);">{{ item.designation }} · {{ item.department }}</p>
    </div>
    <div style="text-align: right;">
      <p class="eyebrow">DISBURSEMENT ACCOUNT</p>
      <p><strong>{{ item.payment_details or 'NEFT / RTGS Bank Transfer' }}</strong></p>
      <p><span class="status {{ item.payment_status }}">{{ item.payment_status }}</span></p>
    </div>
  </div>

  <table style="border: 1px solid var(--border); margin-bottom: 24px;">
    <thead>
      <tr>
        <th>Earnings</th>
        <th style="text-align: right;">Amount (₹)</th>
        <th>Deductions</th>
        <th style="text-align: right;">Amount (₹)</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Basic Salary</td>
        <td style="text-align: right;">{{ item.base_salary|money }}</td>
        <td>Provident Fund (PF) & Deductions</td>
        <td style="text-align: right;">{{ item.deductions|money }}</td>
      </tr>
      <tr>
        <td>HRA & Special Allowances</td>
        <td style="text-align: right;">{{ item.allowances|money }}</td>
        <td>TDS / Income Tax</td>
        <td style="text-align: right;">{{ item.tax|money }}</td>
      </tr>
      <tr style="background: #f8fafc; font-weight: 700;">
        <td>Gross Earnings</td>
        <td style="text-align: right;">{{ (item.base_salary + item.allowances)|money }}</td>
        <td>Total Deductions</td>
        <td style="text-align: right;">{{ (item.deductions + item.tax)|money }}</td>
      </tr>
    </tbody>
  </table>

  <div class="net-preview" style="margin-top: 0;">
    <span style="font-weight: 600;">Net Salary Payable (INR)</span>
    <strong style="font-size: 24px;">{{ item.net_salary|money }}</strong>
  </div>
</section>
{% endblock %}
""",
    "reports.html": """\
{% extends 'base.html' %}
{% block title %}Reports · PayFlow{% endblock %}
{% block content %}
<div class="page-title">
  <div>
    <p class="eyebrow">ANALYTICS</p>
    <h1>Financial Reports</h1>
    <p style="color: var(--muted);">Consolidated monthly and departmental salary expenditure in ₹.</p>
  </div>
  <a class="btn btn-light" href="{{ url_for('export_payrolls') }}">Download full CSV</a>
</div>

<section class="panel">
  <div class="panel-heading">
    <div>
      <p class="eyebrow">MONTHLY REGISTER</p>
      <h2>Period-wise summary</h2>
    </div>
  </div>
  <div class="table-responsive">
    <table>
      <thead>
        <tr>
          <th>Pay period</th>
          <th>Employees paid</th>
          <th>Basic total</th>
          <th>Allowances</th>
          <th>PF / Deductions</th>
          <th>TDS / Tax</th>
          <th>Net disbursed</th>
        </tr>
      </thead>
      <tbody>
        {% for p in periods %}
        <tr>
          <td><strong>{{ p.pay_period|period }}</strong></td>
          <td>{{ p.headcount }}</td>
          <td>{{ p.total_base|money }}</td>
          <td>{{ p.total_allowances|money }}</td>
          <td>{{ p.total_deductions|money }}</td>
          <td>{{ p.total_tax|money }}</td>
          <td><strong>{{ p.net_disbursed|money }}</strong></td>
        </tr>
        {% else %}
        <tr>
          <td colspan="7" class="empty">No monthly payroll data recorded yet.</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</section>

<section class="panel">
  <div class="panel-heading">
    <div>
      <p class="eyebrow">COST CENTERS</p>
      <h2>Departmental breakdown</h2>
    </div>
  </div>
  <div class="table-responsive">
    <table>
      <thead>
        <tr>
          <th>Department</th>
          <th>Headcount</th>
          <th>Total net expenditure</th>
        </tr>
      </thead>
      <tbody>
        {% for d in departments %}
        <tr>
          <td><strong>{{ d.department }}</strong></td>
          <td>{{ d.emp_count }}</td>
          <td><strong>{{ d.total_payroll_expenditure|money }}</strong></td>
        </tr>
        {% else %}
        <tr>
          <td colspan="3" class="empty">No departments added yet.</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</section>
{% endblock %}
"""
}

# Prioritize embedded templates so mismatched disk files can never crash the app
app.jinja_loader = ChoiceLoader([DictLoader(TEMPLATES), app.jinja_loader])


def sync_local_project_files():
    """Automatically repairs local repo files and removes the instance folder on macOS."""
    if IS_SERVERLESS:
        return
    try:
        instance_dir = os.path.join(BASE_DIR, 'instance')
        if os.path.exists(instance_dir):
            shutil.rmtree(instance_dir, ignore_errors=True)

        os.makedirs(os.path.join(BASE_DIR, 'templates'), exist_ok=True)
        os.makedirs(os.path.join(BASE_DIR, 'static'), exist_ok=True)

        for name, content in TEMPLATES.items():
            with open(os.path.join(BASE_DIR, 'templates', name), 'w', encoding='utf-8') as f:
                f.write(content)

        with open(os.path.join(BASE_DIR, 'static', 'style.css'), 'w', encoding='utf-8') as f:
            f.write(STYLE_CSS)

        vercel_json = """{\n  "version": 2,\n  "builds": [\n    {\n      "src": "app.py",\n      "use": "@vercel/python"\n    }\n  ],\n  "routes": [\n    {\n      "src": "/(.*)",\n      "dest": "app.py"\n    }\n  ]\n}\n"""
        with open(os.path.join(BASE_DIR, 'vercel.json'), 'w', encoding='utf-8') as f:
            f.write(vercel_json)

        with open(os.path.join(BASE_DIR, '.gitignore'), 'w', encoding='utf-8') as f:
            f.write("__pycache__/\n*.py[cod]\n*.db\n*.sqlite3\ninstance/\n.env\n.venv/\nvenv/\n.DS_Store\n")
    except Exception:
        pass


sync_local_project_files()


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
                employee_code TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                department TEXT NOT NULL,
                designation TEXT NOT NULL,
                base_salary REAL NOT NULL DEFAULT 0.0,
                payment_details TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS payroll_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                pay_period TEXT NOT NULL,
                base_salary REAL NOT NULL DEFAULT 0.0,
                allowances REAL NOT NULL DEFAULT 0.0,
                deductions REAL NOT NULL DEFAULT 0.0,
                tax REAL NOT NULL DEFAULT 0.0,
                net_salary REAL NOT NULL DEFAULT 0.0,
                payment_status TEXT NOT NULL DEFAULT 'Paid',
                payment_date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (employee_id) REFERENCES employees (id) ON DELETE CASCADE,
                UNIQUE(employee_id, pay_period)
            );
        """)
        admin_hash = generate_password_hash("admin123", method="pbkdf2:sha256")
        row = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
        if not row:
            conn.execute("INSERT INTO users (username, password_hash) VALUES ('admin', ?)", (admin_hash,))
        else:
            conn.execute("UPDATE users SET password_hash = ? WHERE username = 'admin'", (admin_hash,))

        # Seed realistic Indian employees & payroll records if database is brand new
        emp_count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        if emp_count == 0:
            current_period = datetime.now().strftime('%Y-%m')
            today_str = datetime.now().strftime('%Y-%m-%d')
            sample_employees = [
                ('EMP001', 'Aarav Sharma', 'Engineering', 'Senior Software Engineer', 95000.0, 'HDFC Bank · A/C 5010048291 · HDFC0001204', 'Active'),
                ('EMP002', 'Priya Nair', 'Product & Design', 'Product Manager', 85000.0, 'ICICI Bank · A/C 0004015829 · ICIC0000004', 'Active'),
                ('EMP003', 'Rohan Deshmukh', 'Finance & Ops', 'Financial Analyst', 68000.0, 'State Bank of India · A/C 3829104857 · SBIN0004210', 'Active'),
                ('EMP004', 'Ananya Iyer', 'Human Resources', 'HR Operations Lead', 62000.0, 'Axis Bank · A/C 9190100482 · UTIB0000124', 'Active'),
            ]
            conn.executemany("""
                INSERT INTO employees (employee_code, full_name, department, designation, base_salary, payment_details, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, sample_employees)

            seeded_emps = conn.execute("SELECT id, base_salary FROM employees ORDER BY id ASC").fetchall()
            for emp in seeded_emps:
                base = float(emp['base_salary'])
                allowances = round(base * 0.25, 2)   # 25% HRA & Allowances
                deductions = round(base * 0.06, 2)   # 6% PF
                tax = round(base * 0.08, 2)          # 8% TDS
                net = round((base + allowances) - (deductions + tax), 2)
                conn.execute("""
                    INSERT INTO payroll_records (
                        employee_id, pay_period, base_salary, allowances,
                        deductions, tax, net_salary, payment_status, payment_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Paid', ?)
                """, (emp['id'], current_period, base, allowances, deductions, tax, net, today_str))

        conn.commit()


@app.before_request
def ensure_initialized():
    if not os.path.exists(app.config['DATABASE']):
        init_db()


init_db()


def format_inr(value):
    try:
        val = float(value or 0)
        negative = val < 0
        val = abs(val)
        s = f"{val:.2f}"
        int_part, dec_part = s.split('.')
        if len(int_part) > 3:
            last3 = int_part[-3:]
            rest = int_part[:-3]
            groups = []
            while len(rest) > 2:
                groups.insert(0, rest[-2:])
                rest = rest[:-2]
            if rest:
                groups.insert(0, rest)
            formatted_int = ",".join(groups) + "," + last3
        else:
            formatted_int = int_part
        prefix = "-₹" if negative else "₹"
        return f"{prefix}{formatted_int}.{dec_part}"
    except (TypeError, ValueError):
        return "₹0.00"


@app.template_filter('money')
def money_filter(value):
    return format_inr(value)


@app.template_filter('period')
def period_filter(value):
    if not value:
        return ""
    try:
        parts = str(value).split('-')
        if len(parts) == 2:
            dt = datetime(int(parts[0]), int(parts[1]), 1)
            return dt.strftime('%B %Y')
    except Exception:
        pass
    return str(value)


@app.context_processor
def inject_globals():
    return {'csrf_token': 'payflow-csrf-token'}


@app.route('/static/style.css')
def serve_css():
    return Response(STYLE_CSS, mimetype='text/css')


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def generate_next_emp_code(conn):
    rows = conn.execute("SELECT employee_code FROM employees").fetchall()
    max_num = 0
    for r in rows:
        code = str(r['employee_code']).upper().replace('EMP', '').strip()
        if code.isdigit():
            max_num = max(max_num, int(code))
    return f"EMP{max_num + 1:03d}"


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '').strip()

        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if user and check_password_hash(user['password_hash'], password):
                session.clear()
                session['user_id'] = user['id']
                session['username'] = user['username']
                return redirect(url_for('dashboard'))

        flash("Invalid username or password. Default is admin / admin123.", "danger")
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def dashboard():
    current_period = datetime.now().strftime('%Y-%m')
    with get_db() as conn:
        emp_count = conn.execute("SELECT COUNT(*) FROM employees WHERE status COLLATE NOCASE = 'Active'").fetchone()[0]
        runs_count = conn.execute("SELECT COUNT(*) FROM payroll_records").fetchone()[0]
        curr_tot = conn.execute(
            "SELECT COALESCE(SUM(net_salary), 0) FROM payroll_records WHERE pay_period = ?",
            (current_period,)
        ).fetchone()[0]
        tot_paid = conn.execute("SELECT COALESCE(SUM(net_salary), 0) FROM payroll_records").fetchone()[0]

        stats = {
            'employees': emp_count,
            'runs': runs_count,
            'current_total': curr_tot,
            'total_paid': tot_paid
        }

        recent = conn.execute("""
            SELECT p.id, p.pay_period, p.net_salary, p.payment_status,
                   e.full_name, e.employee_code, e.employee_code AS emp_code, e.department
            FROM payroll_records p
            JOIN employees e ON p.employee_id = e.id
            ORDER BY p.id DESC LIMIT 6
        """).fetchall()

    return render_template('dashboard.html', stats=stats, current_period=current_period, recent=recent)


@app.route('/employees')
@login_required
def employees():
    query = (request.args.get('q') or '').strip()
    status = (request.args.get('status') or '').strip()

    sql = "SELECT *, employee_code AS emp_code, payment_details AS bank_account FROM employees WHERE 1=1"
    params = []

    if query:
        sql += " AND (full_name LIKE ? OR employee_code LIKE ? OR department LIKE ? OR designation LIKE ?)"
        q_wild = f"%{query}%"
        params.extend([q_wild, q_wild, q_wild, q_wild])

    if status:
        sql += " AND status COLLATE NOCASE = ?"
        params.append(status)

    sql += " ORDER BY employee_code ASC"

    with get_db() as conn:
        all_employees = conn.execute(sql, params).fetchall()

    return render_template('employees.html', employees=all_employees, query=query, status=status)


@app.route('/employees/new', methods=['GET', 'POST'])
@app.route('/employees/create', methods=['GET', 'POST'], endpoint='employee_create')
@login_required
def new_employee():
    with get_db() as conn:
        next_code = generate_next_emp_code(conn)

        if request.method == 'POST':
            code = (
                request.form.get('employee_code')
                or request.form.get('emp_code')
                or request.form.get('code')
                or next_code
            ).strip().upper()
            name = (
                request.form.get('full_name')
                or request.form.get('name')
                or request.form.get('employee_name')
                or 'New Employee'
            ).strip()
            dept = (request.form.get('department') or request.form.get('dept') or 'Engineering').strip()
            desig = (request.form.get('designation') or request.form.get('title') or 'Software Engineer').strip()
            try:
                salary = float((request.form.get('base_salary') or request.form.get('salary') or '50000').strip() or 50000)
            except ValueError:
                salary = 50000.0
            payment = (
                request.form.get('payment_details')
                or request.form.get('bank_account')
                or 'HDFC Bank · NEFT'
            ).strip()
            status = (request.form.get('status') or 'Active').strip().capitalize()

            try:
                conn.execute("""
                    INSERT INTO employees (employee_code, full_name, department, designation, base_salary, payment_details, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (code, name, dept, desig, salary, payment, status))
                conn.commit()
                flash(f"Employee {name} ({code}) added.", "success")
                return redirect(url_for('employees'))
            except sqlite3.IntegrityError:
                flash(f"Employee Code '{code}' already exists. Please use another code.", "danger")

    return render_template('employee_form.html', employee=None, next_code=next_code)


@app.route('/employees/<int:employee_id>/edit', methods=['GET', 'POST'])
@app.route('/employees/<int:employee_id>/update', methods=['GET', 'POST'], endpoint='employee_edit')
@login_required
def edit_employee(employee_id):
    with get_db() as conn:
        emp = conn.execute(
            "SELECT *, employee_code AS emp_code, payment_details AS bank_account FROM employees WHERE id = ?",
            (employee_id,)
        ).fetchone()
        if not emp:
            abort(404)

        if request.method == 'POST':
            code = (
                request.form.get('employee_code')
                or request.form.get('emp_code')
                or emp['employee_code']
            ).strip().upper()
            name = (request.form.get('full_name') or emp['full_name']).strip()
            dept = (request.form.get('department') or emp['department']).strip()
            desig = (request.form.get('designation') or emp['designation']).strip()
            try:
                salary = float((request.form.get('base_salary') or emp['base_salary'] or 0))
            except ValueError:
                salary = float(emp['base_salary'])
            payment = (
                request.form.get('payment_details')
                or request.form.get('bank_account')
                or emp['payment_details']
            ).strip()
            status = (request.form.get('status') or 'Active').strip().capitalize()

            try:
                conn.execute("""
                    UPDATE employees
                    SET employee_code = ?, full_name = ?, department = ?, designation = ?,
                        base_salary = ?, payment_details = ?, status = ?
                    WHERE id = ?
                """, (code, name, dept, desig, salary, payment, status, employee_id))
                conn.commit()
                flash("Employee details updated.", "success")
                return redirect(url_for('employees'))
            except sqlite3.IntegrityError:
                flash(f"Employee Code '{code}' is already assigned to another employee.", "danger")

    return render_template('employee_form.html', employee=emp, next_code=emp['employee_code'])


@app.route('/employees/<int:employee_id>/delete', methods=['POST'])
@login_required
def delete_employee(employee_id):
    with get_db() as conn:
        conn.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
        conn.commit()
    flash("Employee removed.", "success")
    return redirect(url_for('employees'))


@app.route('/payrolls')
@login_required
def payrolls():
    period = (request.args.get('period') or '').strip()
    sql = """
        SELECT p.*, e.employee_code, e.employee_code AS emp_code, e.full_name, e.department, e.designation
        FROM payroll_records p
        JOIN employees e ON p.employee_id = e.id
        WHERE 1=1
    """
    params = []
    if period:
        sql += " AND p.pay_period = ?"
        params.append(period)
    sql += " ORDER BY p.pay_period DESC, e.employee_code ASC"

    with get_db() as conn:
        records = conn.execute(sql, params).fetchall()

    return render_template('payrolls.html', records=records, period=period)


@app.route('/payrolls/new', methods=['GET', 'POST'])
@app.route('/payrolls/process', methods=['GET', 'POST'], endpoint='payroll_process')
@login_required
def new_payroll():
    with get_db() as conn:
        active_employees = conn.execute(
            "SELECT *, employee_code AS emp_code FROM employees WHERE status COLLATE NOCASE = 'Active' ORDER BY employee_code ASC"
        ).fetchall()

    if not active_employees:
        flash("Add at least one active employee before processing payroll.", "warning")
        return redirect(url_for('new_employee'))

    if request.method == 'POST':
        employee_id = int(request.form.get('employee_id') or active_employees[0]['id'])
        pay_period = (request.form.get('pay_period') or datetime.now().strftime('%Y-%m')).strip()
        try:
            allowances = float(request.form.get('allowances') or 0)
        except ValueError:
            allowances = 0.0
        try:
            deductions = float(request.form.get('deductions') or 0)
        except ValueError:
            deductions = 0.0
        try:
            tax = float(request.form.get('tax') or 0)
        except ValueError:
            tax = 0.0
        payment_status = (request.form.get('payment_status') or 'Paid').strip()
        payment_date = datetime.now().strftime('%Y-%m-%d')

        with get_db() as conn:
            emp = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
            if not emp:
                flash("Selected employee not found.", "danger")
                return redirect(url_for('new_payroll'))

            base_salary = float(emp['base_salary'])
            net_salary = round((base_salary + allowances) - (deductions + tax), 2)

            conn.execute("""
                INSERT INTO payroll_records (
                    employee_id, pay_period, base_salary, allowances,
                    deductions, tax, net_salary, payment_status, payment_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(employee_id, pay_period) DO UPDATE SET
                    base_salary = excluded.base_salary,
                    allowances = excluded.allowances,
                    deductions = excluded.deductions,
                    tax = excluded.tax,
                    net_salary = excluded.net_salary,
                    payment_status = excluded.payment_status,
                    payment_date = excluded.payment_date
            """, (employee_id, pay_period, base_salary, allowances, deductions, tax, net_salary, payment_status, payment_date))
            conn.commit()
            flash(f"Payroll processed for {emp['full_name']} ({pay_period}).", "success")
            return redirect(url_for('payrolls', period=pay_period))

    current_period = datetime.now().strftime('%Y-%m')
    return render_template('payroll_form.html', employees=active_employees, current_period=current_period)


@app.route('/payrolls/<int:payroll_id>/payslip')
@login_required
def payslip(payroll_id):
    with get_db() as conn:
        record = conn.execute("""
            SELECT p.*, e.employee_code, e.employee_code AS emp_code,
                   e.full_name, e.department, e.designation,
                   e.payment_details, e.payment_details AS bank_account
            FROM payroll_records p
            JOIN employees e ON p.employee_id = e.id
            WHERE p.id = ?
        """, (payroll_id,)).fetchone()
        if not record:
            abort(404)
    return render_template('payslip.html', item=record)


@app.route('/payrolls/<int:payroll_id>/delete', methods=['POST'])
@login_required
def delete_payroll(payroll_id):
    with get_db() as conn:
        conn.execute("DELETE FROM payroll_records WHERE id = ?", (payroll_id,))
        conn.commit()
    flash("Payroll entry deleted.", "success")
    return redirect(url_for('payrolls'))


@app.route('/reports')
@login_required
def reports():
    with get_db() as conn:
        period_summary = conn.execute("""
            SELECT 
                pay_period,
                COUNT(id) as headcount,
                COALESCE(SUM(base_salary), 0) as total_base,
                COALESCE(SUM(allowances), 0) as total_allowances,
                COALESCE(SUM(deductions), 0) as total_deductions,
                COALESCE(SUM(tax), 0) as total_tax,
                COALESCE(SUM(net_salary), 0) as net_disbursed
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
            ORDER BY total_payroll_expenditure DESC
        """).fetchall()

    return render_template('reports.html', periods=period_summary, departments=dept_summary)


@app.route('/export/payrolls')
@login_required
def export_payrolls():
    period = (request.args.get('period') or '').strip()
    sql = """
        SELECT 
            p.id, e.employee_code, e.full_name, e.department, e.designation, p.pay_period,
            p.base_salary, p.allowances, p.deductions, p.tax, p.net_salary,
            p.payment_status, p.payment_date
        FROM payroll_records p
        JOIN employees e ON p.employee_id = e.id
        WHERE 1=1
    """
    params = []
    if period:
        sql += " AND p.pay_period = ?"
        params.append(period)
    sql += " ORDER BY p.pay_period DESC, e.employee_code ASC"

    with get_db() as conn:
        records = conn.execute(sql, params).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Record ID', 'Employee Code', 'Full Name', 'Department', 'Designation', 'Pay Period',
        'Basic Salary (INR)', 'Allowances (INR)', 'Deductions (INR)', 'TDS / Tax (INR)',
        'Net Salary (INR)', 'Status', 'Date'
    ])
    for row in records:
        writer.writerow(list(row))

    output.seek(0)
    suffix = period if period else "all"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=payflow_register_{suffix}.csv"}
    )


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5001)