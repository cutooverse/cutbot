# Python, Chromium and everything Chromium needs; plus ffmpeg (the MP4) and git (the game)
FROM mcr.microsoft.com/playwright/python:v1.64.0-noble
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt \
 || python3 -m pip install --no-cache-dir -r requirements.txt
COPY bot.py ./
COPY recorder ./recorder
CMD ["python3", "-u", "bot.py"]
