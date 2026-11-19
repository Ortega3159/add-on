ARG WEALTHFOLIO_VERSION=3.13.1
ARG WEALTHFOLIO_DIGEST=sha256:a51bf08440ec3c517b728e4d5a7d9134cc564e1749eec45bd4f0b7f39573336e

FROM ghcr.io/wealthfolio/wealthfolio:${WEALTHFOLIO_VERSION}@${WEALTHFOLIO_DIGEST}

ARG BUILD_VERSION
ARG BUILD_ARCH

USER root

# Fail during the build if a future Wealthfolio image changes assumptions
# required by this Home Assistant wrapper.
RUN \
    test -x /usr/local/bin/wealthfolio-server \
    && test -d /app/dist \
    && id wealthfolio >/dev/null 2>&1

# Runtime dependencies used only by the Home Assistant bootstrap script.
RUN apk add --no-cache \
    jq \
    openssl \
    su-exec \
    && test "$(command -v su-exec)" = "/sbin/su-exec"

COPY --chmod=0755 run.sh /run.sh

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

CMD ["/run.sh"]