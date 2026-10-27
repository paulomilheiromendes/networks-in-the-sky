# ns-3 simulation image (Docker track). Build from the repository root:
#   docker build -t sky-ns3:3.42 -f docker/ns3.Dockerfile .     (or: make images)
#
# The notebook runs one container per simulation job:
#   docker run --rm -v <results>:/out sky-ns3:3.42 aanet --numNodes=50 ... --outFile=/out/x.csv
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      g++ cmake ninja-build python3 wget bzip2 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ARG NS3_VERSION=3.42
# ns-3 modules to build. Add the ones your scenario needs,
# e.g. "point-to-point;internet;applications;flow-monitor;wifi;mobility;spectrum"
ARG NS3_MODULES="point-to-point;internet;applications;flow-monitor"

WORKDIR /opt
RUN wget -q https://www.nsnam.org/releases/ns-allinone-${NS3_VERSION}.tar.bz2 \
 && tar xjf ns-allinone-${NS3_VERSION}.tar.bz2 \
 && mv ns-allinone-${NS3_VERSION}/ns-${NS3_VERSION} /opt/ns-3 \
 && rm -rf ns-allinone-${NS3_VERSION} ns-allinone-${NS3_VERSION}.tar.bz2

# 1) ns-3 libraries: slow (20-40 min), but cached by Docker until NS3_* changes.
#    "release" = optimised and portable (no -march=native, so the image runs on any x86-64/arm64 CPU).
WORKDIR /opt/ns-3
RUN ./ns3 configure --build-profile=release --enable-modules="${NS3_MODULES}" -G Ninja \
 && ./ns3 build

# 2) Your scenarios: every folder in ns3/ becomes a program; rebuilding is fast.
#    Each program is linked into the PATH under its own name (e.g. "aanet").
COPY ns3/ scratch/
RUN ./ns3 build \
 && for f in build/scratch/*/ns3.* build/scratch/ns3.*; do \
      [ -x "$f" ] || continue; \
      n=$(basename "$f" | sed -E 's/^ns3\.[0-9.]+-//; s/-(default|debug|optimized)$//'); \
      ln -sf "/opt/ns-3/$f" "/usr/local/bin/$n"; \
    done

WORKDIR /out
