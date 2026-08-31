FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# لو محتاجين Playwright، لازم نثبت متصفحاته كمان
# RUN playwright install chromium

COPY . .

EXPOSE 8000