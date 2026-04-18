# Intelligent Financial and Branding Insights System for F&B SMEs

This is a Flask capstone project for small food and beverage businesses (SMEs).

## Tech Stack
- Backend: Flask (Python)
- Frontend: HTML, CSS, Bootstrap 5, JavaScript
- Database: MySQL (set with `DATABASE_URL`)

## Main Features
- Login page (default account: `admin / admin123`)
- Data input pages:
  - Menu Engineering (add, edit, delete)
  - Sales
  - Expenses
  - Marketing campaigns
  - Customer reviews
- Dashboard with key numbers:
  - Revenue
  - Cost
  - Profit
  - ROI
  - Positive sentiment
- Analytics page
- Forecast page (revenue and cash flow)
- ROI page (campaign ROI table)
- Sentiment page (distribution and trend)
- Reports page (P&L summary and menu performance)
- Profitability vs popularity matrix with action suggestions

## Project Files
- `app.py` - Main Flask app and routes
- `config.py` - App settings and database URL
- `db.py` - SQLAlchemy setup
- `models.py` - Database models
- `analytics.py` - Forecast, ROI, and sentiment logic
- `schema.sql` - MySQL table schema
- `templates/` - HTML templates (Jinja + Bootstrap)
- `static/css/style.css` - Custom styles
- `static/js/dashboard.js` - Chart.js code

## Database Setup (MySQL)
1. Create database tables:
```sql
SOURCE schema.sql;
```

2. Set database URL in PowerShell:
```powershell
$env:DATABASE_URL="mysql+pymysql://root:deaperi@localhost:3306/fnb_insights"
```

## Run the App
This is a Flask app, not a Streamlit app.
Run with `python app.py`.

### Windows (PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Or use:
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

Or use:
```bash
./run_flask.sh
```

Open in browser: `http://127.0.0.1:5000`

## Notes
- Main data input is manual form entry in the app.
- All records are saved in the SQL database.
- Analytics are calculated from database data.

## Troubleshooting
- If you see merge markers like `<<<<<<<` in `app.py`, fix the conflict first.
- If you see `ModuleNotFoundError: No module named 'flask_sqlalchemy'`:
  1. Activate your virtual environment.
  2. Run:
     - `python -m pip install --upgrade pip`
     - `python -m pip install -r requirements.txt`
  3. Run the app again: `python app.py`
- If you ran `streamlit run app.py`, stop it and run `python app.py` instead.

## Quick Conflict Fix
If Git reports conflicts in files like `README.md`, `app.py`, or `requirements.txt`, run:

```bash
./fix_conflicts.sh
```
