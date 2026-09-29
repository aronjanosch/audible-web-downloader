# Gunicorn configuration for Audible Web Downloader
#
# IMPORTANT: workers must stay at 1.
# The download queue is held entirely in-memory as a process-level singleton.
# Multiple worker processes would each have their own isolated queue and the
# SSE progress stream would only see updates from the process that happens to
# handle that request — leading to blank/stale progress UI.
#
# Use threads instead to handle concurrent requests within the single process.

import os

workers = 1
worker_class = "gthread"
# One thread per in-flight request. Every open admin tab holds one thread for its SSE progress
# stream, so the pool must comfortably exceed (open tabs + concurrent API calls). Threads are cheap
# (I/O bound); the single worker process is what keeps the in-memory queue coherent.
threads = int(os.environ.get("GUNICORN_THREADS", "32"))
# gthread parks idle keep-alive sockets in a poller (no thread held), so a long keep-alive saves the
# TCP/TLS setup for the ~15 asset requests of a cold page load behind a reverse proxy.
keepalive = 30
# Heartbeat file on tmpfs: avoids spurious worker stalls when the container fs is slow (Docker).
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None

bind = "0.0.0.0:5505"

# Never time out — SSE connections are long-lived and downloads can run for
# many minutes on slow connections.
timeout = 0

accesslog = "-"       # stdout
errorlog = "-"        # stderr
loglevel = "info"
