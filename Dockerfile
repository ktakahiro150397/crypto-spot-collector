FROM python:3.11.14-slim

# Install MySQL client
RUN apt-get update && apt-get install -y default-mysql-client && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
# RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/uv:$PATH"
ENV PATH="/uvx:$PATH"
ENV PATH="/bin/:$PATH"

# Make uv available to all users
RUN ln -s /root/.cargo/bin/uv /usr/local/bin/uv

# Install git
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Set up app directory
WORKDIR /app

# Copy git directory for version information
COPY .git /app/.git

# Copy application files
COPY /src /app
COPY pyproject.toml /app/
COPY uv.lock /app/
COPY README.md /app/

RUN uv sync --locked

CMD [ "uv", "run", "crypto_spot_collector/scripts/buy_spot.py" ]