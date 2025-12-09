echo "Starting deployment..."

git pull
docker compose up -d --build

echo "Deployment completed."
