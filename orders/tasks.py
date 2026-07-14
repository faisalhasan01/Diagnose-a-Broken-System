import json
import uuid
import time
from django.utils import timezone
from celery import shared_task
from django.conf import settings
import redis

# Initialize Redis client using Celery's broker configuration
redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)

# Sliding Window Rate Limiter Lua Script
# Ensures atomic removal of old requests, count check, and adding the new request.
LUA_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

-- Remove elements older than the sliding window threshold
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)

-- Count remaining requests in the window
local current_requests = redis.call('ZCARD', key)

if current_requests < limit then
    -- Add the request timestamp and member
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, window * 2)
    return 1 -- Allowed
else
    return 0 -- Denied
end
"""

# Register the Lua script with the Redis client
rate_limit_script = redis_client.register_script(LUA_SLIDING_WINDOW)


class ThrottledException(Exception):
    """Raised when the rate limit is exceeded."""
    pass


def check_rate_limit(rate_limit_key="email_rate_limit", limit=200, window=60):
    """
    Checks the rate limit using an atomic Redis sliding window.
    Default limit is 200 requests per 60 seconds (200 emails/minute).
    """
    now_ms = int(time.time() * 1000)
    window_ms = window * 1000
    member = f"{now_ms}:{uuid.uuid4()}"
    
    # Run the atomic Lua script
    result = rate_limit_script(keys=[rate_limit_key], args=[now_ms, window_ms, limit, member])
    return result == 1


@shared_task(bind=True, max_retries=3)
def send_transactional_email(self, email_data, is_test_fail=False):
    """
    Celery task to send transactional emails.
    Respects the rate limit, retries on failure with exponential backoff,
    and logs permanently failed tasks to a Dead-Letter Queue (DLQ).
    """
    # 1. Enforce rate limiting
    # If the rate limit is exceeded, raise ThrottledException to trigger retry
    if not check_rate_limit(limit=200, window=60):
        # Calculate backoff delay for rate limit retry: 2s, 4s, 8s
        backoff = 2 ** (self.request.retries + 1)
        raise self.retry(
            exc=ThrottledException("Rate limit of 200 emails/minute reached. Retrying task..."),
            countdown=backoff
        )

    # 2. Simulate email sending and handle failures
    try:
        if is_test_fail:
            raise Exception("Simulated connection error with email provider.")
        
        # Simulate successful email sending
        print(f"[EMAIL SENT] To: {email_data.get('to')}, Subject: {email_data.get('subject')}")
        return {"status": "success", "to": email_data.get("to")}
        
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            # DLQ (Dead Letter Queue) - Task permanently failed
            dlq_data = {
                "task_id": self.request.id,
                "email_data": email_data,
                "error": str(exc),
                "failed_at": timezone.now().isoformat()
            }
            redis_client.rpush("email_dlq", json.dumps(dlq_data))
            print(f"[DLQ ENTRY] Task {self.request.id} sent to DLQ: {str(exc)}")
            raise exc
        else:
            # Retry with exponential backoff: 2s, 4s, 8s
            backoff = 2 ** (self.request.retries + 1)
            raise self.retry(exc=exc, countdown=backoff)
