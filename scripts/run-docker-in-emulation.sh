set -eu
TAG="${1:-latest}"

docker compose -f docker-compose.yml up -d