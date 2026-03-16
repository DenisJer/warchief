#!/bin/bash
set -e

# Usage: ./release.sh --major | --minor | --patch
# Bumps version, builds, publishes to PyPI, commits, and pushes.

cd "$(dirname "$0")"

# Read current version
CURRENT=$(grep -oP 'version = "\K[^"]+' pyproject.toml)
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"

case "${1}" in
  --major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  --minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  --patch) PATCH=$((PATCH + 1)) ;;
  *)
    echo "Usage: ./release.sh --major | --minor | --patch"
    echo "Current version: $CURRENT"
    exit 1
    ;;
esac

NEW="${MAJOR}.${MINOR}.${PATCH}"
echo "Releasing: $CURRENT → $NEW"

# Check for uncommitted changes
if [ -n "$(git status --porcelain)" ]; then
  echo "Error: uncommitted changes. Commit or stash first."
  exit 1
fi

# Check PyPI token
if [ -z "$PYPI_TOKEN" ]; then
  echo -n "PyPI token: "
  read -s PYPI_TOKEN
  echo ""
fi

# Bump version
sed -i '' "s/version = \"$CURRENT\"/version = \"$NEW\"/" pyproject.toml
echo "Version bumped in pyproject.toml"

# Run tests
echo "Running tests..."
source .venv/bin/activate
pip install -e . -q
python -m pytest tests/ -x -q || { echo "Tests failed — aborting"; git checkout pyproject.toml; exit 1; }

# Build
rm -rf dist/
python -m build -q
echo "Built dist/"

# Publish
twine upload dist/* --username __token__ --password "$PYPI_TOKEN"
echo "Published to PyPI"

# Commit + push
git add pyproject.toml
git commit -m "release: v${NEW}"
git tag "v${NEW}"
git push origin main --tags
echo ""
echo "Done! v${NEW} is live at https://pypi.org/project/warchief-orchestrator/${NEW}/"
