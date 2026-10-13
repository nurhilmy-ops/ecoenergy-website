FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    DATA_DIR=/app/data

# rasterio's binary wheel bundles GDAL but links against the system libexpat, which the slim
# image does not ship; without it every Copernicus/GeoTIFF screening fails at import time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
# Fail the build, not every job, if a native library is missing.
RUN python -c "import rasterio, pyproj, shapely, matplotlib, scipy"

COPY app ./app
RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/data && chown appuser /app/data
USER appuser

EXPOSE 8000
CMD ["python", "-m", "app"]
