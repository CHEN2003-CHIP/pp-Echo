FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        git \
        ca-certificates \
        coreutils \
        findutils \
        grep \
        sed \
        gawk \
        diffutils \
        patch \
        tar \
        gzip \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

