#!/bin/bash
echo "Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
# Symlink uv to /usr/local/bin so it is globally available in the container PATH
ln -s $HOME/.local/bin/uv /usr/local/bin/uv
echo "uv installed successfully"
