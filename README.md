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
2. Configure connection string and secret values (PowerShell example):
```powershell
$env:DATABASE_URL="mysql+pymysql://root:dyaperi@localhost:3306/fnb_insights"
$env:SECRET_KEY="replace-with-a-long-random-secret"
$env:BASE_URL="http://127.0.0.1:5000"
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

## Deploy online
The app exposes a module-level Flask object at the bottom of `app.py`:
```python
app = create_app()
```

Use this production start command:
```bash
gunicorn app:app
```

Do not use `gunicorn "app:create_app()"` for this project unless you remove the module-level `app` object and intentionally change the entry point.

### Required environment variables
- `DATABASE_URL` - MySQL connection URL. Use `mysql+pymysql://USER:PASSWORD@HOST:PORT/DATABASE`. If your provider gives `mysql://...`, the app converts it to `mysql+pymysql://...`.
- `SECRET_KEY` - long random value for Flask sessions. Required when `FLASK_ENV=production` or `APP_ENV=production`.
- `BASE_URL` - deployed public domain, for example `https://your-app.onrender.com` or `https://your-app.up.railway.app`. QR feedback links use this instead of `127.0.0.1`.
- `FLASK_ENV` or `APP_ENV` - set to `production`.

`PUBLIC_BASE_URL` is still supported as an older alias, but `BASE_URL` is preferred.

### Render
1. Push this repository to GitHub.
2. Create a Render **Web Service** from the repository.
3. Set runtime to Python.
4. Build command:
```bash
pip install -r requirements.txt
```
5. Start command:
```bash
gunicorn app:app
```
6. Add environment variables: `DATABASE_URL`, `SECRET_KEY`, `BASE_URL`, and `FLASK_ENV=production`.
7. Provision a MySQL database separately, then put its connection URL in `DATABASE_URL`.

### Railway
1. Create a Railway project from the GitHub repository.
2. Add a MySQL database service.
3. Add environment variables to the web service: `DATABASE_URL`, `SECRET_KEY`, `BASE_URL`, and `APP_ENV=production`.
4. Set the start command:
```bash
gunicorn app:app
```
5. Deploy, then set `BASE_URL` to the generated Railway public domain.

## Notes
- Primary data input is manual forms in the web app (CSV upload is not the main workflow).
- All business records are stored in the configured SQL database and analytics are calculated from DB data.
- Default local configuration points to MySQL: `mysql+pymysql://root:dyaperi@localhost:3306/fnb_insights`.

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
