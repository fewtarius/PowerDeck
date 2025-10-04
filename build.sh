#!/bin/bash
# PowerDeck Build Script

set -e

echo "Building PowerDeck..."

# Sync version from VERSION file
if [ -f "VERSION" ] && [ -f "update-version.sh" ]; then
    echo "Synchronizing version..."
    chmod +x update-version.sh
    ./update-version.sh
fi

# Build RyzenAdj binary for TDP control
echo "Building RyzenAdj for TDP control..."
if [ -d "RyzenAdj" ]; then
    # Check for cmake and required dependencies
    if ! command -v cmake &> /dev/null; then
        echo "Error: cmake is required to build RyzenAdj"
        echo "Install it with your package manager (e.g., apt install cmake, dnf install cmake, etc.)"
        exit 1
    fi

    # Create RyzenAdj build directory
    mkdir -p RyzenAdj/build
    cd RyzenAdj/build

    # Configure and build RyzenAdj
    echo "Configuring RyzenAdj build..."
    cmake -DCMAKE_BUILD_TYPE=Release ..

    echo "Compiling RyzenAdj..."
    make -j$(nproc 2>/dev/null || echo 1)

    # Verify binary was created
    if [ ! -f "ryzenadj" ]; then
        echo "Error: RyzenAdj compilation failed!"
        exit 1
    fi

    echo "RyzenAdj built successfully!"
    echo "Binary: RyzenAdj/build/ryzenadj"

    # Return to project root
    cd ../..
else
    echo "Warning: RyzenAdj submodule not found - TDP control will not be available"
fi

# Install dependencies
echo "Installing dependencies..."
pnpm install

# Build frontend
echo "Building frontend..."
pnpm build

# Apply IIFE fix for Decky compatibility
echo "Applying Decky compatibility fix..."
if [ -f "dist/index.js" ]; then
    # macOS compatible sed
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' 's/export { index as default };/(function() { return index; })();/' dist/index.js
    else
        sed -i 's/export { index as default };/(function() { return index; })();/' dist/index.js
    fi
    echo "IIFE fix applied"
else
    echo "Build failed - dist/index.js not found"
    exit 1
fi

echo "PowerDeck build complete!"
echo "Built files available in dist/"

# Show version info
if [ -f "VERSION" ]; then
    VERSION=$(cat VERSION | tr -d '\n\r')
    echo "Version: $VERSION"
fi

# Show RyzenAdj status
if [ -f "RyzenAdj/build/ryzenadj" ]; then
    echo "RyzenAdj: Available (TDP control enabled)"
else
    echo "RyzenAdj: Not available (TDP control disabled)"
fi
