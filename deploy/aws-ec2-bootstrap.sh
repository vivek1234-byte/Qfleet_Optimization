#!/bin/bash
# AWS EC2 Bootstrap script for QFleet Backend (Ubuntu)
# This script sets up a t2.micro AWS instance, builds the Docker image and runs it.
set -e

echo "Starting QFleet EC2 Initialization..."

# 1. Add Swap Space (Crucial for t2.micro to not crash while building heavy ML packages like xgboost)
if [ ! -f /swapfile ]; then
    echo "Creating 2GB swap space..."
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

# 2. Update and Install Docker & Git
sudo apt-get update -y
sudo apt-get install -y docker.io git curl
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -a -G docker ubuntu

# 3. Clone Repository
cd /home/ubuntu
if [ ! -d "Qfleet_Optimization" ]; then
    git clone https://github.com/vivek1234-byte/Qfleet_Optimization.git
fi
cd Qfleet_Optimization
git fetch --all
git reset --hard origin/main

# 4. Configure Environment
echo "Setting up environment variables..."
cat << 'EOF' > .env
QGF_JWT_SECRET=AWS_PRODUCTION_SECRET_KEY_REPLACE_IF_NEEDED
QGF_SEED_DEMO=true
QGF_CORS_ORIGINS=https://qfleetoptimization.vercel.app,http://localhost:5173
PORT=80
EOF

# 5. Fix Dockerfile to map to port 80
cat << 'EOF' > Dockerfile.aws
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements-deploy.txt backend/requirements-deploy.txt
RUN pip install --no-cache-dir -r backend/requirements-deploy.txt
COPY . .
RUN rm -f backend/data/qfleet.db backend/data/qfleet.db-shm backend/data/qfleet.db-wal && chmod +x deploy/start.sh
RUN python train_model.py
ENV PORT=80
EXPOSE 80
CMD ["./deploy/start.sh"]
EOF

# 6. Build and Run Container
echo "Building Docker Image (this will take 5-10 minutes)..."
sudo docker build -t qfleet-api -f Dockerfile.aws .

echo "Stopping any existing containers..."
sudo docker stop qfleet-backend || true
sudo docker rm qfleet-backend || true

echo "Starting new container on port 80..."
sudo docker run -d \
  --name qfleet-backend \
  --restart unless-stopped \
  -p 80:80 \
  --env-file .env \
  qfleet-api

echo "QFleet Backend Deployment Completed!"
