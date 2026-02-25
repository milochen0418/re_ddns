; /etc/bind/zones/db.example.com
; ──────────────────────────────
; Authoritative zone file for example.com
; Replace "example.com" with your actual domain.
; The "home" A record is the one managed by re_ddns.

$TTL    300
@       IN      SOA     ns1.example.com. admin.example.com. (
                        2025010101  ; Serial (YYYYMMDDNN)
                        3600        ; Refresh
                        900         ; Retry
                        604800      ; Expire
                        300 )       ; Negative Cache TTL

; ── Name servers ──
@       IN      NS      ns1.example.com.

; ── NS glue record (point to this server's public IP) ──
ns1     IN      A       127.0.0.1

; ── Dynamic record managed by re_ddns ──
; This will be updated via RFC 2136 by the Reflex app.
home    IN      A       127.0.0.1
