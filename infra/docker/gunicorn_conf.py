# Gunicorn production configuration for Hospitality Agent Cloud API
import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
workers = int(os.getenv("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))
worker_class = "uvicorn.workers.UvicornWorker"

# Worker timeouts & graceful shutdown
timeout = 60
graceful_timeout = 30
keepalive = 5

# Security & limits
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190
max_requests = 1000
max_requests_jitter = 50

# Logging
loglevel = os.getenv("LOG_LEVEL", "info")
accesslog = "-"
errorlog = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)ss'
