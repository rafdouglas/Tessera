#!/bin/bash
# Prepare release files for manual GitHub upload
#
# Usage:
#   ./scripts/prepare_release.sh [version]
#
# If version not provided, reads from plugins/tessera/metadata.txt

set -e

# Determine version
if [ -n "$1" ]; then
    VERSION="$1"
else
    # Extract version from metadata.txt
    VERSION=$(grep "^version=" plugins/tessera/metadata.txt | cut -d'=' -f2)
fi

echo "Preparing release for version: $VERSION"

# Run packaging script to create ZIPs in dist/
echo "Running packaging script..."
python scripts/package.py

# Rename with version numbers in dist/
echo "Creating versioned ZIPs in dist/..."
cd dist
cp tessera.zip tessera-${VERSION}.zip
cp percentage_split.zip percentage_split-${VERSION}.zip
cp stripe_hatching.zip stripe_hatching-${VERSION}.zip
cd ..

echo ""
echo "✓ Release files ready in dist/:"
ls -lh dist/*-${VERSION}.zip

echo ""
echo "Next steps:"
echo "1. Create a git tag: git tag -a v${VERSION} -m 'Release ${VERSION}'"
echo "2. Push the tag: git push origin v${VERSION}"
echo "3. GitHub Actions will automatically create the release"
echo ""
echo "Or manually upload files from dist/ to GitHub Releases page."
