ARG WEALTHFOLIO_VERSION=3.9.1
ARG WEALTHFOLIO_DIGEST=sha256:0ebd0147463f3637afce8cf33e0601a7c5c060e70f15c19d5762435f5819234a

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