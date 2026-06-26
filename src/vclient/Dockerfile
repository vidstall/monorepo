FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir livekit livekit-rtc
COPY bot.py .
CMD ["python", "-u", "bot.py"]
