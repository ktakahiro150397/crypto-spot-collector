FROM mcr.microsoft.com/devcontainers/python:1-3.11-bullseye

# Install MySQL client
RUN apt-get update && apt-get install -y default-mysql-client && rm -rf /var/lib/apt/lists/*

# Install uv as root
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:$PATH"

# Make uv available to all users
RUN ln -s /root/.cargo/bin/uv /usr/local/bin/uv

# Set up the workspace directory
WORKDIR /workspaces/crypto-spot-collector