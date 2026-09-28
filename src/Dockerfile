FROM python:3.11-slim
# libgl1/libglib2.0-0 are needed by opencv-python on slim images
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# Listens on all interfaces inside the container; docker-compose publishes it on 127.0.0.1 only.
ENV EMAFIG_ALLOWED_HOSTS=127.0.0.1,localhost
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
