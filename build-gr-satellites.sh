#!/bin/bash
# build-gr-satellites.sh — build gr-satellites from source into /usr/local,
# replacing the distribution package.   Usage: ./build-gr-satellites.sh [tag]
#   e.g. ./build-gr-satellites.sh v5.9.0     (default: latest v5.* tag)
# Re-run with a newer tag to upgrade. Needs GNU Radio 3.10 (5.x branch).
set -e
SRC=${SRC:-$HOME/src/gr-satellites}
JOBS=${JOBS:-2}          # Pi 4: higher -j can run out of RAM during the C++/LTO build

sudo apt-get install -y --no-install-recommends build-essential cmake git gnuradio-dev \
    liborc-0.4-dev libsndfile1-dev python3-construct python3-requests python3-websocket

# gr-satellites installs for (and its scripts run with) the default python3,
# so that must be the Python GNU Radio was packaged for
if ! python3 -c "from gnuradio import gr" 2>/dev/null; then
    echo "error: '$(command -v python3)' ($(python3 --version 2>&1)) can't import GNU Radio;" >&2
    echo "       the default python3 must be the distribution's Python." >&2
    exit 1
fi

# remove the distro build so only one copy is on the paths
if dpkg -s gr-satellites >/dev/null 2>&1; then
    sudo apt-get remove -y gr-satellites 'libgnuradio-satellites*'
fi

[[ -d $SRC/.git ]] || git clone https://github.com/daniestevez/gr-satellites.git "$SRC"
cd "$SRC"
git fetch -q --tags
TAG=${1:-$(git tag -l 'v5.*' --sort=-v:refname | head -n 1)}
git checkout -q "$TAG"
echo "building gr-satellites $TAG with -j$JOBS"

rm -rf build && mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j"$JOBS"
sudo make install
sudo ldconfig
hash -r
echo "installed: $(gr_satellites --version 2>&1 | head -n 1) at $(command -v gr_satellites)"
