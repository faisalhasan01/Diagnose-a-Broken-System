# Django Performance, Async Queue & Multi-Tenancy Assessment

This repository demonstrates the complete solution for the technical assessment, covering database N+1 optimization, an async rate-limited email queue (Celery + Redis), and automatic multi-tenant data isolation.

## Requirements
- Python 3.12+
- SQLite (default)
- Redis Server (Required as broker for Celery and the Rate Limiter)

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

## How to Run & Profile Locally

### 1. Start the Redis Server
Ensure your Redis server is running on the default port `6379`.
- **On Windows:** (Using the winget installed port)
  Double-click `redis-server.exe` or execute `redis-server` in a command line window.
- **Using Docker (Alternative):**
  ```bash
  docker run --name redis-server -p 6379:6379 -d redis
  ```

### 2. Launch Celery Worker (Section 2)
In a separate terminal, activate the virtual environment and run the Celery worker.
- **On Windows:** (Requires a thread pool worker execution pool context because Windows lacks `fork()` support):
  ```bash
  celery -A django_perf_assessment worker --loglevel=info -P threads
  ```
- **On macOS/Linux:**
  ```bash
  celery -A django_perf_assessment worker --loglevel=info
  ```

### 3. Launch Django Development Server
You can launch the server using your terminal:
```bash
python manage.py runserver
```
Or, on Windows, simply double-click the **`run.bat`** file in the project folder to start it automatically.

### 4. View the Interactive Dashboard UI
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

