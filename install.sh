#!/bin/bash
# install.sh — deploy the station scripts.   Usage: sudo ./install.sh
#   container side: satnogs-post + tools  -> bind mount local/scripts
#   host side:      satnogs-worker, its config/decoders, systemd timer
set -e
cd "$(dirname "$0")"
LOCAL=/var/lib/docker-bindmounts/satnogs_satnogs-client/opt/satnogs-non-free/local
DEST=$LOCAL/scripts
VENV=/opt/satnogs-worker/venv

install -m 755 -g satnogs-client satnogs-post *.py "$DEST"/
echo "installed container scripts to $DEST"

# --- host worker (runs as pi:satnogs-client; needs group write on these dirs)
install -m 755 worker/satnogs-worker /usr/local/bin/satnogs-worker
install -d -m 2775 -g satnogs-client "$LOCAL/iq" "$LOCAL/queue" "$LOCAL/work" "$LOCAL/cache"
chgrp satnogs-client "$LOCAL" "$LOCAL/iq" "$LOCAL/queue"
chmod g+rwxs "$LOCAL" "$LOCAL/iq" "$LOCAL/queue"
install -d -m 2775 -g satnogs-client "$LOCAL/satyaml" "$LOCAL/ksy"
install -m 664 -g satnogs-client worker/worker.yml "$LOCAL/worker.yml"
cp worker/satyaml/*.yml "$LOCAL/satyaml/" 2>/dev/null || true
cp worker/ksy/*.ksy worker/ksy/*.py "$LOCAL/ksy/" 2>/dev/null || true
chgrp -R satnogs-client "$LOCAL/satyaml" "$LOCAL/ksy"

if [[ ! -x $VENV/bin/python ]]; then
    python3 -m venv --system-site-packages "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade satnogs-decoders

install -m 644 worker/systemd/satnogs-worker.service worker/systemd/satnogs-worker.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now satnogs-worker.timer
echo "installed satnogs-worker; timer enabled (journalctl -u satnogs-worker)"
