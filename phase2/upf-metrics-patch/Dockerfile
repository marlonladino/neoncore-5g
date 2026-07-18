# Custom open5gs-upfd build with the N3 GTP packet-count metrics
# (fivegs_ep_n3_gtp_{in,out}datapktn3upf) re-enabled.
#
# Upstream Open5GS disables these two counters at compile time in gtp-path.c
# (wrapped in `#if 0`) because incrementing a metric on every GTP-U packet
# measurably hurts UPF throughput on the hot data path (see Issue #2210,
# Discussion #2208/#2209). For this single-UE dev testbed that overhead is
# negligible and the Grafana visibility is worth it, so gtp-path-metrics.patch
# removes the `#if 0`/`#endif` guards around both blocks.
#
# Only open5gs-upfd's binary is rebuilt and swapped into the otherwise
# untouched, already-vetted gradiant/open5gs:2.8.0 image -- everything else
# (users, other NF binaries, runtime libs) comes from that image unchanged.

FROM debian:bullseye AS builder

RUN apt-get update && apt-get upgrade -y && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3-pip python3-setuptools python3-wheel \
        ninja-build build-essential flex bison git cmake meson \
        libsctp-dev libgnutls28-dev libgcrypt-dev libssl-dev \
        libmongoc-dev libbson-dev libyaml-dev libmicrohttpd-dev \
        libcurl4-gnutls-dev libnghttp2-dev libtins-dev libtalloc-dev \
        iproute2 ca-certificates netbase pkg-config libidn11-dev \
        curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN curl -sL -o open5gs.tar.gz \
        https://github.com/open5gs/open5gs/archive/refs/tags/v2.8.0.tar.gz && \
    tar xzf open5gs.tar.gz
COPY gtp-path-metrics.patch .
RUN cd open5gs-2.8.0 && patch -p1 < ../gtp-path-metrics.patch

RUN cd open5gs-2.8.0 && \
    meson build --prefix=/opt/open5gs && \
    ninja -C build install

FROM gradiant/open5gs:2.8.0
COPY --from=builder /opt/open5gs/bin/open5gs-upfd /opt/open5gs/bin/open5gs-upfd
