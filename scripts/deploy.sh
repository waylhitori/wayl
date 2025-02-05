
#!/bin/bash
set -e

# Build Docker image
docker build -t wayl-ai .

# Run containers
docker-compose up -d