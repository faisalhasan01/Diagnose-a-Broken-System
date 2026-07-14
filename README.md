# Django Performance Assessment - Section 1

This repository demonstrates the investigation, diagnosis, and fix of an $O(N)$ database query scaling issue (the N+1 Query problem) in a Django REST API.

## Requirements
- Python 3.12+
- SQLite (default)

---

## Quick Setup & Execution (Under 5 Minutes)

### 1. Initialize Virtual Environment
From this directory, run:
```bash
# Create the virtual environment
py -m venv .venv

# Activate the virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (CMD):
.venv\Scripts\activate.bat
# Linux/macOS:
source .venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run Database Migrations
Create the database tables and the schema required for Django Silk:
```bash
python manage.py migrate
```

### 4. Seed Sample Database
Generate a test customer and 250 orders (each containing random items and payments) to simulate realistic database volumes:
```bash
python seed_data.py
```

### 5. Run Automated Tests
Execute the test suite to verify the query count reduction and check endpoints correctness:
```bash
python manage.py test orders
```
*Expected test output:*
```text
[PERFORMANCE REPORT]
Number of orders in test: 5
Buggy Endpoint Query Count: 36 SQL queries
Optimized Endpoint Query Count: 2 SQL queries
Query reduction: 34 queries saved! (94.4% reduction)
```

---

## How to Profile Locally with Django Silk

### 1. Launch Development Server
You can launch the server using your terminal:
```bash
python manage.py runserver
```
Or, on Windows, simply double-click the **`run.bat`** file in the project folder to start it automatically.

### 2. View the Interactive Dashboard UI
Open your browser and visit:
```text
http://127.0.0.1:8000/
```
From here you can:
- Select a customer from the dropdown.
- Toggle between **Slow (Unoptimized)** and **Fast (Optimized)** querying modes.
- Visually inspect the database query counts, response latency metrics, and real-time performance gains side-by-side.

### 3. Trigger the JSON API Endpoints Directly
If you wish to query raw JSON payloads directly:
- **Buggy (Slow) Endpoint:**
  ```text
  GET http://127.0.0.1:8000/api/orders/summary/?customer_id=1
  ```
- **Optimized (Fast) Endpoint:**
  ```text
  GET http://127.0.0.1:8000/api/orders/summary-fixed/?customer_id=1
  ```

### 4. View the Silk Profiler Dashboard
To inspect SQL statements and execution traces, visit:
```text
http://127.0.0.1:8000/silk/
```
Here, you can review:
- The execution time comparison between both paths.
- The exact SQL statements executed.
- The SQL query counts (reducing from **1,491 queries** in the buggy view down to exactly **2 queries** in the fixed view).

