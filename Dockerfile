FROM python:3.12-slim

# Install system dependencies including gosu for user switching
RUN apt-get update && \
    apt-get install -y ffmpeg gosu && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    FLASK_APP=app.py \
    PUID=1000 \
    PGID=1000

# Copy requirements file
COPY requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy entrypoint script
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Create directories for volumes
RUN mkdir -p /app/config /app/downloads /app/library

# Expose port
EXPOSE 5505

# Set entrypoint
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Run the application
CMD ["python", "run.py"]

