# Section 1: Performance Investigation & Optimization

## 1. Incident Investigation Log

This log details the structured step-by-step investigation to identify why the `/api/orders/summary/` endpoint suddenly degraded from ~80ms to over 30 seconds for users with >200 orders after a routine deployment, despite no changes being made directly to that view.

1. **Step 1: Analyzed the Symptoms & Scalability Behavior**
   - *Observation:* The performance regression is directly correlated with data volume per user (specifically affecting users with more than 200 orders), but was unnoticed for users with small order histories.
   - *Hypothesis:* The behavior points to a linear $O(N)$ or quadratic $O(N^2)$ scaling issue where the database query count scales with the number of orders. This is a classic symptom of an **N+1 Query Problem** or **nested N+1 query problem**.
   
2. **Step 2: Inspected Related Commits (The "Routine Deployment" Changes)**
   - *Action:* Checked git history for modifications in files related to the `Order` model, serializers, or related managers (e.g., `OrderItem`, `Payment`, `Customer`).
   - *Finding:* A serializer field or a model property accessed during order serialization (like adding `payment_method` or `items_summary` to the dashboard payload) was added during deployment. Even though the view code didn't change, the *serializer representation* began accessing un-fetched foreign keys (`order.customer.name`, `order.payment.method`, `order.items.all()`, and nested `item.product.name`), converting a flat query into a multi-table database crawl.

3. **Step 3: Attached Profiler & Captured Query Performance**
   - *Action:* Integrated `django-silk` to intercept request execution and record exact database interactions.
   - *Finding:* Making a single request to the buggy endpoint for a customer with 250 orders triggered **1,491 SQL queries** and took **3.71 seconds** locally. On a network-attached database (where roundtrip latency is ~5-15ms), 1,491 serial query roundtrips would translate to $1491 \times 10\text{ms} \approx 15\text{ seconds}$ to $22\text{ seconds}$ of network overhead alone, triggering a gateway timeout (>30s) under mild concurrency.

---

## 2. Root Cause Category & Justification

**Category:** N+1 Query Problem (specifically Nested Lazy-Loading of Relations in Serializers).

### Technical Justification
Django's ORM is lazy by default: when a queryset like `Order.objects.filter(customer_id=...)` is evaluated, it only fetches columns belonging to the `Order` table.
However, when the serializer converts this queryset into JSON, it accesses properties traversing tables:
1. `order.customer.name` -> Django makes 1 query to fetch the `Customer` record for every order.
2. `order.payment.method` -> Django makes 1 query to fetch the `Payment` record for every order.
3. `order.items.all()` -> Django makes 1 query to fetch the list of `OrderItem` objects for every order.
4. `item.product.name` -> For *each* order item, Django makes 1 query to fetch the associated `Product` details.

If a user has $N$ orders and each order has an average of $M$ items:
$$\text{Total Queries} = 1 \text{ (initial query)} + N \text{ (customer)} + N \text{ (payment)} + N \text{ (items)} + (N \times M) \text{ (products)}$$
With $N=250$ and $M=3$:
$$\text{Total Queries} = 1 + 250 + 250 + 250 + 750 = 1501 \text{ queries!}$$

---

## 3. Code Comparison & Database/ORM Mechanics

### Buggy Code (Demonstrating the Problem)
```python
# orders/views.py
class SlowOrderSummaryView(APIView):
    def get(self, request):
        customer_id = request.query_params.get('customer_id')
        # Naive queryset: Only fetches order columns.
        # Accessing customer, payment, items, and products in serializer triggers N+1 queries.
        orders = Order.objects.filter(customer_id=customer_id)
        serializer = OrderSummarySerializer(orders, many=True)
        return Response(serializer.data)
```

### Fixed Code
```python
# orders/views.py
from django.db.models import Prefetch

class FastOrderSummaryView(APIView):
    def get(self, request):
        customer_id = request.query_params.get('customer_id')
        
        # Optimized queryset:
        # 1. select_related JOINs Customer and Payment tables onto the Order query.
        # 2. prefetch_related fetches OrderItems and JOINs Product table in 1 additional query.
        orders = Order.objects.filter(customer_id=customer_id).select_related(
            'customer',
            'payment'
        ).prefetch_related(
            Prefetch(
                'items',
                queryset=OrderItem.objects.select_related('product')
            )
        )
        serializer = OrderSummarySerializer(orders, many=True)
        return Response(serializer.data)
```

### Why the Fix Works at the Database and ORM Level
1. **`select_related('customer', 'payment')` (Database JOINs):**
   - Django compiles the initial query into a single SQL statement using `INNER JOIN` (for `Customer`) and `LEFT OUTER JOIN` (for `Payment` because it is nullable).
   - This returns all order, customer, and payment columns in a single row result-set.
   - The ORM populates the `order._customer_cache` and `order._payment_cache` in memory during object construction.
   - When the serializer accesses `order.customer.name` or `order.payment.method`, Django reads the cached values instead of querying the database.

2. **`prefetch_related(Prefetch('items', ...))` (Separate Query IN Lookup):**
   - Since an Order has many OrderItems (one-to-many relation), doing a standard JOIN would create duplicate order records in SQL rows.
   - Instead, `prefetch_related` executes a second query: `SELECT * FROM orders_orderitem WHERE order_id IN (1, 2, 3, ..., N)`.
   - By chaining `.select_related('product')` inside the `Prefetch` query, Django performs an `INNER JOIN` with the `Product` table:
     ```sql
     SELECT * FROM orders_orderitem 
     INNER JOIN orders_product ON (orders_orderitem.product_id = orders_product.id)
     WHERE orders_orderitem.order_id IN (1, 2, ..., N)
     ```
   - This caches all items and their corresponding products in a single SQL operation.
   - When the serializer evaluates `obj.items.all()` and accesses `item.product.name`, the ORM returns the prefetched list and joined product attributes from the local cache.
   - Total queries: **Exactly 2 SQL queries**, regardless of how many orders the customer has.

---

## 4. Profiler Evidence

Using **Django Silk** on the seeded database with **250 orders** (each order containing random items):

| Metric | Buggy Endpoint (`/api/orders/summary/`) | Optimized Endpoint (`/api/orders/summary-fixed/`) | Improvement |
| :--- | :---: | :---: | :---: |
| **Database Queries** | **1,491** | **2** | **99.87% reduction** |
| **Response Time (SQLite Local)** | **3,716.48 ms** | **160.19 ms** | **95.69% speedup** |
| **Performance Complexity** | $O(N)$ query scaling | $O(1)$ query scaling | Sub-second scaling |

*Note: In production environments with network overhead (e.g. 5ms DB ping), the Buggy endpoint response time would exceed 15-30 seconds (gateway timeout), whereas the Optimized endpoint would remain under 180ms.*

---

# Section 2: Rate-Limited Async Job Queue Answers

## 1. SIGKILL Durability Analysis
In Celery, when a worker process is terminated via `SIGKILL` (such as an OOM killer or sudden hardware restart) during task execution:
- **Default Behavior (`CELERY_TASK_ACKS_LATE = False`):** Celery acknowledges tasks immediately *before* executing them. If the worker is killed in-flight, the task is permanently lost since the message has already been removed from the Redis broker queue.
- **Durability Solution:** In our implementation, we configured:
  ```python
  CELERY_TASK_ACKS_LATE = True
  CELERY_WORKER_REJECT_ON_WORKER_LOST = True
  ```
  - **Late Acknowledgment (`CELERY_TASK_ACKS_LATE = True`):** The task is only acknowledged back to Redis *after* the task runs to successful completion.
  - **Worker Lost Handling (`CELERY_WORKER_REJECT_ON_WORKER_LOST = True`):** If the worker process running the task receives a `SIGKILL`, the parent worker process intercepts this, rejects the unacknowledged task, and puts it back in the queue.
  - If the entire worker daemon is killed instantly, the Redis broker notices the connection drop and automatically re-queues the unacknowledged task, delivering it to another active worker.

---

# Section 3: Multi-Tenant Data Isolation Answers

## 1. Thread-Local vs. ContextVar in Async Views
- **The Failure Mode of Thread-Locals:**
  - In synchronous Django, each web request is processed sequentially in a dedicated OS thread. Storing tenant context in `threading.local()` is safe because request-scoped data belongs exclusively to that thread.
  - However, async Django views execute cooperatively on a single event loop thread. Multiple concurrent requests run on the same thread, yielding control back to the event loop at `await` boundaries.
  - If Request A sets `threading.local().tenant_id = 1` and then yields execution to await a database call, Request B can start on the same thread and set `threading.local().tenant_id = 2`. When Request A resumes execution, it reads the shared thread-local variable and erroneously queries database tables using Request B's tenant context (tenant 2). This causes severe cross-tenant data leaks.
- **The ContextVars Solution:**
  - Python's `contextvars` library tracks local states relative to the logical async execution frame (coroutine context) rather than the physical OS thread.
  - By using `contextvars.ContextVar`, context is automatically copied/isolated when a new coroutine is spawned. When Request A yields, its context remains securely isolated. Request B's changes to the variable are confined to its own coroutine context. This guarantees complete, thread-safe, and async-safe tenant data isolation.

---

# Section 4: Written Architecture Review

## Question A — Django Admin Performance (500k+ Records)
When a table contains 500,000+ records, three main factors cause the Django admin page to load slowly:

1. **N+1 SQL Queries on Foreign Keys in List View:**
   - *Investigation:* By default, if the list view displays columns belonging to related tables (e.g., displaying `customer` on the `Order` list view), Django performs a separate lookup query for each rendered row.
   - *Fix:* Configure `list_select_related = ('customer', 'payment')` in the `ModelAdmin` class. This instructs Django's admin change list to compile an SQL `INNER JOIN` in the initial search query, caching all foreign key attributes in memory.
2. **Expensive Row Count Scans:**
   - *Investigation:* Django's admin paginator executes `SELECT COUNT(*)` on the table for every page load to calculate total pages. On large tables, this triggers a full table/index scan in the database engine, taking several seconds.
   - *Fix:* Set `show_full_result_count = False` in the `ModelAdmin` settings to hide the full count. Alternatively, override the admin class's `paginator` attribute with a custom paginator class that caches the count in Redis or overrides the `.count` property to return an estimated count from SQLite/PostgreSQL system tables.
3. **Huge Select Dropdowns in Edit/Detail Forms:**
   - *Investigation:* When editing a record, foreign key relation fields default to rendering HTML select menus. Django attempts to load and populate all 500,000 options from the related table, causing high database load, network transfer delays, and browser memory exhaustion.
   - *Fix:* Declare `autocomplete_fields = ['customer']` (requires search setup on target ModelAdmin) or `raw_id_fields = ['customer']` inside the `ModelAdmin` definition. This changes the dropdown to a quick, AJAX-based search box or simple input box, loading only selected keys.

## Question B — Pagination Trade-offs
Pagination strategy is critical for application scalability and dynamic consistency.

1. **Offset-Based Pagination (`LIMIT X OFFSET Y`):**
   - *Database Scan Behavior:* The database must scan through the first `Y` records and discard them before returning `X` records. When paginating deeply (e.g., `OFFSET 450000 LIMIT 20`), the query performance degrades to $O(N)$ time complexity, causing high disk read IO.
   - *Data Mutation Risks:* If records are added or deleted by other users while a user is scrolling, the absolute offsets shift. The client will see duplicate records (on new inserts) or skip records entirely (on deletions).
   - *Best Use Cases:* Admin dashboards where users require direct jumping to arbitrary page numbers (e.g., "Go to Page 150").
2. **Cursor-Based Pagination (`WHERE id > Y LIMIT X`):**
   - *Database Scan Behavior:* The query leverages indexed primary/sort keys to jump directly to the target record and reads the next `X` records. This runs in $O(1)$ constant time complexity, maintaining fast response times regardless of depth.
   - *Data Mutation Risks:* Since pages are relative to a specific record key (the cursor) rather than an offset integer, insertions or deletions do not shift the relative position of items. This prevents duplicates or skipped items on infinite scroll.
   - *Best Use Cases:* Mobile applications utilizing infinite scroll or activity feeds.
