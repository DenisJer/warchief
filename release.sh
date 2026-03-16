#!/bin/bash
set -e

# Usage: ./release.sh --major | --minor | --patch
# Bumps version, builds, publishes to PyPI, commits, and pushes.

cd "$(dirname "$0")"

# Read current version
CURRENT=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
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

# Build Vue frontend
echo "Building Vue frontend..."
cd warchief/web/frontend
npm install --silent
npm run build || { echo "Frontend build failed — aborting"; cd ../../..; git checkout pyproject.toml; exit 1; }
cd ../../..
echo "Frontend built"

# Run tests
echo "Running tests..."
source .venv/bin/activate
pip install -e . -q
python -m pytest tests/ -x -q || { echo "Tests failed — aborting"; git checkout pyproject.toml; exit 1; }

# Build Python package
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
echo "Published to PyPI"

# Update Homebrew formula
TARBALL="warchief_orchestrator-${NEW}.tar.gz"
TARBALL_URL="https://files.pythonhosted.org/packages/source/w/warchief-orchestrator/${TARBALL}"
echo "Waiting for PyPI to propagate..."
sleep 5
SHA256=$(curl -sL "$TARBALL_URL" | shasum -a 256 | awk '{print $1}')
if [ -z "$SHA256" ] || [ "$SHA256" = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" ]; then
  echo "Warning: Could not fetch tarball from PyPI (may need more time). Update Homebrew formula manually."
else
  TAP_DIR=$(mktemp -d)
  git clone --depth 1 https://github.com/DenisJer/homebrew-tap.git "$TAP_DIR" 2>/dev/null
  FORMULA="$TAP_DIR/Formula/warchief.rb"
  if [ -f "$FORMULA" ]; then
    sed -i '' "s|url \".*\"|url \"${TARBALL_URL}\"|" "$FORMULA"
    sed -i '' "s|sha256 \".*\"|sha256 \"${SHA256}\"|" "$FORMULA"
    cd "$TAP_DIR"
    git add Formula/warchief.rb
    git commit -m "Update warchief to v${NEW}"
    git push origin main
    cd -
    echo "Homebrew formula updated"
  else
    echo "Warning: Homebrew formula not found at $FORMULA"
  fi
  rm -rf "$TAP_DIR"
fi

echo ""
echo "Done! v${NEW} is live:"
echo "  PyPI: https://pypi.org/project/warchief-orchestrator/${NEW}/"
echo "  Brew: brew upgrade warchief"
