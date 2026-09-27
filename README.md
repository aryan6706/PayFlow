# PayFlow — Automated Employee Payroll System

A compact Flask + SQLite college-project demo for managing employees and generating monthly payroll payslips.

## Run it (beginner-friendly)

1. Open a terminal in this project folder.
2. Create an isolated Python environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install the only dependency and start the app:

   ```bash
   pip install -r requirements.txt
   python app.py
   ```

4. Open the address printed in the terminal, usually `http://127.0.0.1:5000`.

## Demo login

- Username: `admin`
- Password: `admin123`

## Best demo flow

1. Sign in.
2. Go to **Employees** → **Add Employee**.
3. Add `EMP001`, a name, department, job title, and basic monthly salary.
4. Go to **Generate Payroll**. Enter allowances, deductions, and overtime.
5. Generate the payslip, then show **Payroll History** and the **Dashboard**.

## Salary formula

`Net Salary = Basic Salary + Allowances + (Overtime Hours × Overtime Rate) − Deductions`

## Notes

- Data is saved locally in `payroll.db`, created automatically on first run.
- This is intentionally a college-demo MVP, not a production payroll system. Change the secret key and replace the demo login before publishing it.
