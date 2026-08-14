#!/usr/bin/env bash
# Deprecated. Use the Nushell installer:
#   nu ~/Github/dotagents/scripts/install-skills.nu
set -euo pipefail
exec nu "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install-skills.nu" "$@"
