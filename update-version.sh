#!/bin/bash
# Update version in package.json and plugin.json from VERSION file
# If no VERSION file, reads from git tag and increments patch version

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" & pwd)"
VERSION_FILE="$SCRIPT_DIR/VERSION"

# Function to increment patch version
increment_version() {
    local version="$1"
    # Parse version components
    if [[ "$version" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
        local major="${BASH_REMATCH[1]}"
        local minor="${BASH_REMATCH[2]}"
        local patch="${BASH_REMATCH[3]}"
        # Increment patch
        patch=$((patch + 1))
        echo "${major}.${minor}.${patch}"
    else
        echo "ERROR: Invalid version format: $version" >&2
        exit 1
    fi
}

# Get current version from git tag or VERSION file
get_current_version() {
    # Try git tag first
    local tag
    tag=$(git describe --tags --abbrev=0 2>/dev/null | sed 's/^v//') || true
    
    if [ -n "$tag" ]; then
        echo "$tag"
    elif [ -f "$VERSION_FILE" ]; then
        cat "$VERSION_FILE" | tr -d '\n\r'
    else
        echo "ERROR: Cannot determine current version (no git tag or VERSION file)" >&2
        exit 1
    fi
}

# Determine version to use
if [ -f "$VERSION_FILE" ]; then
    CURRENT_VERSION=$(cat "$VERSION_FILE" | tr -d '\n\r')
else
    CURRENT_VERSION=$(get_current_version)
fi

if [ -z "$CURRENT_VERSION" ]; then
    echo "ERROR: VERSION file is empty"
    exit 1
fi

# Increment version for new release
VERSION=$(increment_version "$CURRENT_VERSION")

echo "Current version: $CURRENT_VERSION"
echo "New version: $VERSION"

# Update VERSION file
echo "$VERSION" > "$VERSION_FILE"
echo "Updated VERSION file: $VERSION"

# Update package.json
if [ -f "$SCRIPT_DIR/package.json" ]; then
    echo "  * Updating package.json..."
    # Use jq if available, otherwise use sed
    if command -v jq >/dev/null 2>&1; then
        jq --arg version "$VERSION" '.version = $version' "$SCRIPT_DIR/package.json" > "$SCRIPT_DIR/package.json.tmp"
        mv "$SCRIPT_DIR/package.json.tmp" "$SCRIPT_DIR/package.json"
    else
        # Fallback to sed
        sed -i "s/\"version\": \"[^\"]*\"/\"version\": \"$VERSION\"/" "$SCRIPT_DIR/package.json"
    fi
    echo "   * package.json updated"
fi

# Update plugin.json
if [ -f "$SCRIPT_DIR/plugin.json" ]; then
    echo "  * Updating plugin.json..."
    # Check if version field exists
    if grep -q '"version"' "$SCRIPT_DIR/plugin.json"; then
        # Update existing version field
        if command -v jq >/dev/null 2>&1; then
            jq --arg version "$VERSION" '.version = $version' "$SCRIPT_DIR/plugin.json" > "$SCRIPT_DIR/plugin.json.tmp"
            mv "$SCRIPT_DIR/plugin.json.tmp" "$SCRIPT_DIR/plugin.json"
        else
            sed -i "s/\"version\": \"[^\"]*\"/\"version\": \"$VERSION\"/" "$SCRIPT_DIR/plugin.json"
        fi
    else
        # Add version field after name field
        if command -v jq >/dev/null 2>&1; then
            jq --arg version "$VERSION" '.version = $version' "$SCRIPT_DIR/plugin.json" > "$SCRIPT_DIR/plugin.json.tmp"
            mv "$SCRIPT_DIR/plugin.json.tmp" "$SCRIPT_DIR/plugin.json"
        else
            sed -i "s/\"name\": \"PowerDeck\",/\"name\": \"PowerDeck\",\n  \"version\": \"$VERSION\",/" "$SCRIPT_DIR/plugin.json"
        fi
    fi
    echo "    * plugin.json updated"
fi

# Update Python files with hard-coded version references (if any remain)
if [ -f "$SCRIPT_DIR/main.py" ]; then
    echo "  * Updating Python files..."
    # Replace any remaining hard-coded version strings in Python files
    # This is a safety net for any missed version references
    
    # Update any remaining hard-coded "1.0.0" that might be missed
    sed -i "s/return \"1\.0\.0\"/return get_plugin_version()/g" "$SCRIPT_DIR/main.py" 2>/dev/null || true
    sed -i "s/\"database_version\": \"1\.0\.0\"/\"database_version\": get_plugin_version()/g" "$SCRIPT_DIR/main.py" 2>/dev/null || true
    
    # Remove any remaining hardcoded fallback versions
    sed -i "s/return \"[0-9]\+\.[0-9]\+\.[0-9]\+\"/return \"unknown\"/g" "$SCRIPT_DIR/main.py" 2>/dev/null || true
    sed -i "s/\"version\", \"[0-9]\+\.[0-9]\+\.[0-9]\+\"/\"version\", \"unknown\"/g" "$SCRIPT_DIR/main.py" 2>/dev/null || true
    
    echo "    * Python files checked"
fi

# Update decky.pyi version
if [ -f "$SCRIPT_DIR/decky.pyi" ]; then
    echo "  * Updating decky.pyi..."
    sed -i "s/__version__ = '[^']*'/__version__ = '$VERSION'/g" "$SCRIPT_DIR/decky.pyi" 2>/dev/null || true
    echo "    * decky.pyi updated"
fi

# Update frontend TypeScript files to remove hardcoded versions
if [ -f "$SCRIPT_DIR/src/index.tsx" ]; then
    echo "  * Updating frontend files..."
    # Remove hardcoded version constants and replace with backend calls
    sed -i "s/const POWERDECK_VERSION = \"[^\"]*\";/\/\/ Version managed by backend - no hardcoding/g" "$SCRIPT_DIR/src/index.tsx" 2>/dev/null || true
    sed -i "s/useState<string>(\"[0-9]\+\.[0-9]\+\.[0-9]\+\")/useState<string>(\"Loading...\")/g" "$SCRIPT_DIR/src/index.tsx" 2>/dev/null || true
    
    echo "    * Frontend files updated to use backend versioning"
fi

echo "Version update complete!"
