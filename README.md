# PayFlow

A minimal Flask + SQLite Payroll Management System for standard business operations.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

The first boot creates an empty database at `instance/payflow.db` and one administrator account:

- Username: `admin`
- Password: `admin123`

Before deployment, set environment variables for a secure secret and admin password:

```bash
export PAYFLOW_SECRET_KEY='replace-with-a-long-random-value'
export PAYFLOW_ADMIN_PASSWORD='replace-this-default-password'
```

Set these before the first boot. Existing administrator passwords are intentionally not overwritten.

## Clean-up commands for a legacy copy

Run these from the old project directory before replacing it with this distribution:

```bash
rm -f payroll.db payflow.db
rm -rf instance .venv __pycache__ .pytest_cache __MACOSX
find . -name '.DS_Store' -delete
```

Do not run these commands in a folder that contains data you need to keep.

## Payroll formula

`Net Salary = Base Salary + Allowances - Deductions - Tax`
