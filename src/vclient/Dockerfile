FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir livekit
COPY bot.py .
CMD ["python", "-u", "bot.py"]
