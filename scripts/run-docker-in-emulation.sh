 docker run -d --name careervaulthq --platform linux/arm/v7 \
      -p 8000:8000 \
      -v careervault-data:/data \
      --restart unless-stopped \
      careervaulthq:latest