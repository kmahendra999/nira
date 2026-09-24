# The Nira site.
#
# Static only, on nginx-alpine: roughly 50 MB, no runtime to patch, and
# nothing that can execute a request.
FROM nginx:1.27-alpine

# Run unprivileged. nginx-alpine ships an `nginx` user; the stock config
# wants to bind 80, which a non-root process may not, hence 8080 below.
RUN rm /etc/nginx/conf.d/default.conf

COPY website/nginx.conf           /etc/nginx/conf.d/nira.conf
COPY website/security-headers.conf /etc/nginx/security-headers.conf
COPY website/public/    /usr/share/nginx/html/

# The installer, from the one place it lives. The page tells people to pipe
# this into bash, and the README used to point that command at a GitHub
# Pages site that was never set up for this fork — so it 404'd. Serving it
# from the same host as the page means the command on the page works
# wherever the page is reachable, with no third party involved.
COPY scripts/install/install.sh /usr/share/nginx/html/install.sh

# Hash whatever was actually copied in, at build time, and write the
# digests where the page can read them. Doing it here rather than by hand
# means the digest on the page is a digest of the file being served — not
# of whichever build was current when someone last edited a constant.
RUN set -eu; \
    cd /usr/share/nginx/html/downloads 2>/dev/null || exit 0; \
    { echo '{'; \
      first=1; \
      for f in *; do \
        [ -f "$f" ] || continue; \
        case "$f" in checksums.json) continue ;; esac; \
        [ "$first" = 1 ] || echo ','; \
        first=0; \
        printf '  "%s": "%s"' "$f" "$(sha256sum "$f" | cut -d' ' -f1)"; \
      done; \
      echo; echo '}'; \
    } > checksums.json; \
    cat checksums.json

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
