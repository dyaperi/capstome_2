# Intelligent Financial and Branding Insights System for F&B SMEs

A Flask capstone prototype for traditional food and beverage SMEs (for example, Mee Rebus Amy Warisan Sary).

## Required stack
- Backend: **Flask (Python)**
- Frontend: **HTML, CSS, Bootstrap 5, JavaScript**
- Database: **MySQL** (default via `DATABASE_URL`)

## Features delivered
- Login page (default: `admin / admin123`)
- Direct data entry pages (primary workflow):
  - Menu Engineering module (add, edit, update, delete)
  - Sales entry
  - Expense entry
  - Marketing campaign entry
  - Customer review entry
- Main dashboard with KPI cards (revenue, cost, profit, ROI, positive sentiment)
- Analytics page
- Forecast page (revenue + cash flow forecasts)
- ROI page (campaign ROI table)
- Sentiment insights page (distribution + trend vs sales)
- Reports page (P&L summary + menu performance)
- Full row-level action buttons (edit/delete) for table records
- Profitability vs Popularity matrix, quadrant classification, and strategic action recommendations

## Project structure
- `app.py` - Flask app and routes
- `config.py` - app configuration + MySQL URI
- `db.py` - SQLAlchemy instance
- `models.py` - relational models
- `analytics.py` - forecasting, ROI, and sentiment logic
- `schema.sql` - MySQL schema (optional if you use MySQL)
- `templates/` - Jinja + Bootstrap pages
- `static/css/style.css` - custom UI styles
- `static/js/dashboard.js` - Chart.js rendering

## Database setup (MySQL)
1. Create DB and tables:
```sql
SOURCE schema.sql;
```
2. Configure connection string (PowerShell example):
```powershell
$env:DATABASE_URL="mysql+pymysql://root:deaperi@localhost:3306/fnb_insights"
```

## Run locally
> This is a **Flask app**, not a Streamlit app.  
> Use `python app.py` (do **not** run `streamlit run app.py`).

### Windows PowerShell
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Or run helper script:
```powershell
.\run_flask.ps1
```

### macOS/Linux
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Or run helper script:
```bash
./run_flask.sh
```

Open: `http://127.0.0.1:5000`

## Notes
- Primary data input is manual forms in the web app (CSV upload is not the main workflow).
- All business records are stored in the configured SQL database and analytics are calculated from DB data.
- Default configuration points to MySQL: `mysql+pymysql://root:deaperi@localhost:3306/fnb_insights`.

## Troubleshooting
- If you see `SyntaxError` with `<<<<<<< ours` in `app.py`, your local file still has unresolved Git merge conflict markers.
- Fix by discarding local conflicted content and restoring the committed version:
  - `git checkout -- app.py`
  - then run `python -m py_compile app.py` to confirm syntax is valid.
- If you see `ModuleNotFoundError: No module named 'flask_sqlalchemy'`, your current Python environment does not have dependencies installed.
  1. Activate your virtual environment first.
  2. Run:
     - `python -m pip install --upgrade pip`
     - `python -m pip install -r requirements.txt`
  3. Verify install:
     - `python -m pip show Flask-SQLAlchemy`
  4. Re-run:
     - `python app.py`
- If you ran `streamlit run app.py`, stop and run `python app.py` instead (this project uses Flask routes/templates, not Streamlit).

### Fix merge-conflicted files quickly
If Git shows:
- `Conflicted: README.md`
- `Conflicted: app.py`
- `Conflicted: requirements.txt`

run:
```bash
./fix_conflicts.sh
```

This script checks those files for conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) and restores clean versions from your current branch `HEAD`.
