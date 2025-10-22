#!/bin/bash

# uv installation
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$PATH"

# Install Python dependencies using uv
uv sync --dev

# Install pre-commit hooks
uv run pre-commit install

# Create basic project structure
mkdir -p src/crypto_spot_collector
mkdir -p tests
mkdir -p docs
mkdir -p config

# Create __init__.py files
touch src/__init__.py
touch src/crypto_spot_collector/__init__.py
touch tests/__init__.py

echo "✅ Development environment setup complete!"
echo "🐍 Python environment configured with uv"
echo "🔧 Pre-commit hooks installed"
echo "📁 Basic project structure created"