#!/bin/bash
#
# Script to generate SRI (Subresource Integrity) hashes for CDN scripts
#
# Usage: ./generate_sri_hashes.sh
#
# This script downloads all CDN dependencies used in index.html and generates
# SHA-384 hashes for Subresource Integrity verification.
#

set -e

echo "=================================================="
echo "SRI Hash Generator for Session Viewer CDN Scripts"
echo "=================================================="
echo ""

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Temporary directory for downloads
TMP_DIR=$(mktemp -d)
trap "rm -rf $TMP_DIR" EXIT

# Function to generate SRI hash
generate_sri_hash() {
    local url=$1
    local filename=$(basename "$url")
    local temp_file="$TMP_DIR/$filename"

    echo -e "${YELLOW}Processing:${NC} $url"

    # Download the file
    if curl -sL "$url" -o "$temp_file"; then
        # Generate SHA-384 hash
        local hash=$(openssl dgst -sha384 -binary "$temp_file" | openssl base64 -A)
        echo -e "${GREEN}Integrity:${NC} sha384-$hash"
        echo ""
    else
        echo "ERROR: Failed to download $url"
        echo ""
    fi
}

echo "Generating SRI hashes for all CDN scripts..."
echo ""
echo "NOTE: Tailwind CSS (cdn.tailwindcss.com) is NOT included"
echo "    because it doesn't support CORS headers required for SRI."
echo "    This is documented in index.html with risk assessment."
echo ""

# CDN URLs from index.html (excluding Tailwind CSS)
generate_sri_hash "https://cdn.jsdelivr.net/npm/zero-md@3?register"
generate_sri_hash "https://cdn.jsdelivr.net/npm/dayjs@1.11.10/dayjs.min.js"
generate_sri_hash "https://cdn.jsdelivr.net/npm/dayjs@1.11.10/plugin/relativeTime.js"
generate_sri_hash "https://cdn.jsdelivr.net/npm/axios@1.6.2/dist/axios.min.js"
generate_sri_hash "https://cdn.jsdelivr.net/npm/renderjson@1.4.0/renderjson.min.js"
generate_sri_hash "https://cdnjs.cloudflare.com/ajax/libs/js-sha256/0.11.0/sha256.min.js"

echo "=================================================="
echo "Done! Copy the 'integrity' values above and replace"
echo "the placeholder hashes in index.html"
echo ""
echo "Scripts with SRI: 6/7 (86%)"
echo "  zero-md, dayjs, dayjs/plugin, axios, renderjson, js-sha256"
echo "  Tailwind CSS - Cannot use SRI (CDN limitation)"
echo "=================================================="
