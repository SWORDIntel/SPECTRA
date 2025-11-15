#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Define the repository URL and directory name
REPO_URL="https://github.com/proseltd/Telepathy-Community.git"
REPO_DIR="Telepathy-Community"

# 1. Clean Slate: Forcefully remove any existing Telepathy-Community directory
if [ -d "$REPO_DIR" ]; then
  echo "Removing existing directory: $REPO_DIR"
  rm -rf "$REPO_DIR"
fi

# 2. Fresh Clone: Clone the repository again
echo "Cloning repository: $REPO_URL"
git clone "$REPO_URL"

# 3. Set Permissions: Explicitly set ownership and permissions
echo "Setting permissions for: $REPO_DIR"
chmod -R 755 "$REPO_DIR"

# 4. Install Dependencies: Create a Python virtual environment and install dependencies
echo "Creating Python virtual environment"
python3 -m venv "$REPO_DIR/venv"

echo "Activating virtual environment and installing dependencies"
source "$REPO_DIR/venv/bin/activate"
pip install -r "$REPO_DIR/requirements.txt"
deactivate

echo "Setup complete. The development environment is ready in the '$REPO_DIR' directory."
