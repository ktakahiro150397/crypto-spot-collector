echo "Starting deployment..."

git pull
docker compose down
docker compose build
docker compose up -d

echo "Deployment completed."
