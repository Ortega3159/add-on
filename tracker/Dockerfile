ARG WEALTHFOLIO_VERSION=3.10.0
ARG WEALTHFOLIO_DIGEST=sha256:6dcf9019aee7ba0747344087365ea57846107943ff0e2718a9bee72a98e20f85

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