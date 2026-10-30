#!/bin/bash
# install.sh — copy container-side scripts into the SatNOGS bind mount
set -e
DEST=/var/lib/docker-bindmounts/satnogs_satnogs-client/opt/satnogs-non-free/local/scripts
install -m 755 -g satnogs-client satnogs-post *.py "$DEST"/
echo "installed to $DEST"
