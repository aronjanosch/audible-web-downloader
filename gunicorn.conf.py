# Gunicorn configuration for Audible Web Downloader
#
# IMPORTANT: workers must stay at 1.
# The download queue is held entirely in-memory as a process-level singleton.
# Multiple worker processes would each have their own isolated queue and the
# SSE progress stream would only see updates from the process that happens to
# handle that request — leading to blank/stale progress UI.
#
# Use threads instead to handle concurrent requests within the single process.

workers = 1
worker_class = "gthread"
threads = 12          # SSE streams + API calls + download callbacks

bind = "0.0.0.0:5505"

# Never time out — SSE connections are long-lived and downloads can run for
# many minutes on slow connections.
timeout = 0

accesslog = "-"       # stdout
errorlog = "-"        # stderr
loglevel = "info"
