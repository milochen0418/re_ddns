[TOC]

# Initial Build
All files are created. Here's a summary of the complete Docker setup:

---

### Docker File Overview

| File | Purpose |
| --- | --- |
| Dockerfile | Python 3.11 + BIND9 + Node.js; installs Poetry dependencies and starts both services |
| docker-compose.yml | Port mapping (53, 3000, 8000); volume mount for source live-reload |
| named.conf | Main BIND9 settings: authoritative-only, logging |
| named.conf.local | TSIG key definition + zone declaration (dynamic updates allowed) |
| rndc.conf | `rndc` management tool configuration |
| db.example.com | Example zone file including the `home` A record |
| entrypoint.sh | Start BIND9 → start Reflex dev server → graceful shutdown |
| generate_tsig_key.sh | One-command TSIG secret generation and automatic config updates |
| .dockerignore | Excludes unnecessary files to speed up image builds |

### How It Works

1. A **single container** runs both BIND9 (DNS) and Reflex App (Web UI).
2. The `re_ddns` source code is mounted into the container. When you edit Python code on macOS, Reflex in the container detects changes and reloads automatically, **without rebuilding the image**.
3. **Port 53** is exposed from the container to macOS, so your Mac can act as a DDNS server.
4. **Port 3000** serves `http://localhost:3000` for operating the Reflex App to control BIND9.
5. Reflex App sends dynamic DNS updates via RFC 2136 (`dnspython`) to `127.0.0.1:53` inside the container.

## Quick Start

### Quick Start 1
```bash
# 1. Generate TSIG key (one-time only)
./docker/generate_tsig_key.sh

# 2. If macOS port 53 is occupied
sudo lsof -i :53  # check
sudo launchctl unload -w /System/Library/LaunchDaemons/com.apple.mDNSResponder.plist

# 3. Build & start
docker compose up --build

# 4. Open http://localhost:3000
# 5. In Configuration form, fill in:
#    Server IP=127.0.0.1, Key Name=ddns-key, Key Secret=<generated secret>

# Verify DNS
dig @127.0.0.1 home.example.com A
```

### Quick Start 2
If port 53 is already free (`lsof` returns nothing), there is no conflict.

On modern macOS (Ventura+), a `launchctl unload` error can be expected. `mDNSResponder` may already not be listening on port 53, which is consistent with an empty `lsof` result.

You can proceed directly:
```bash
# 1. Generate TSIG key (one-time)
./docker/generate_tsig_key.sh

# 2. Build & start
docker compose up --build
```

No need to worry about the `launchctl` error if port 53 is available.


# Initial Startup Test
## Test Method

After initial startup, go to the `re_ddns` project folder and run the following tests.


```bash=1
dig @127.0.0.1 home.example.com A
```
```
; <<>> DiG 9.10.6 <<>> @127.0.0.1 home.example.com A
; (1 server found)
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 24711
;; flags: qr aa rd; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 1
;; WARNING: recursion requested but not available

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 1232
;; QUESTION SECTION:
;home.example.com.              IN      A

;; ANSWER SECTION:
home.example.com.       300     IN      A       127.0.0.1

;; Query time: 5 msec
;; SERVER: 127.0.0.1#53(127.0.0.1)
;; WHEN: Thu Feb 19 06:49:54 CST 2026
;; MSG SIZE  rcvd: 61
```

```bash=2
dig @127.0.0.1 home.example.com A +short
```
```
127.0.0.1
```

```bash=3
dig @127.0.0.1 example.com SOA
```
```
; <<>> DiG 9.10.6 <<>> @127.0.0.1 example.com SOA
; (1 server found)
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 38322
;; flags: qr aa rd; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 1
;; WARNING: recursion requested but not available

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 1232
;; QUESTION SECTION:
;example.com.                   IN      SOA

;; ANSWER SECTION:
example.com.            300     IN      SOA     ns1.example.com. admin.example.com. 2025010101 3600 900 604800 300

;; Query time: 1 msec
;; SERVER: 127.0.0.1#53(127.0.0.1)
;; WHEN: Thu Feb 19 06:50:13 CST 2026
;; MSG SIZE  rcvd: 86
```



```bash=4
dig @127.0.0.1 example.com NS
```
```
; <<>> DiG 9.10.6 <<>> @127.0.0.1 example.com NS
; (1 server found)
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 34433
;; flags: qr aa rd; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 2
;; WARNING: recursion requested but not available

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 1232
;; QUESTION SECTION:
;example.com.                   IN      NS

;; ANSWER SECTION:
example.com.            300     IN      NS      ns1.example.com.

;; ADDITIONAL SECTION:
ns1.example.com.        300     IN      A       127.0.0.1

;; Query time: 1 msec
;; SERVER: 127.0.0.1#53(127.0.0.1)
;; WHEN: Thu Feb 19 06:50:20 CST 2026
;; MSG SIZE  rcvd: 74
```

```bash=5
dig @127.0.0.1 home.example.com A +noall +answer +authority
```
```
; <<>> DiG 9.10.6 <<>> @127.0.0.1 home.example.com A +noall +answer +authority
; (1 server found)
;; global options: +cmd
home.example.com.       300     IN      A       127.0.0.1
```

```bash=6
dig @127.0.0.1 example.com ANY
```
```
; <<>> DiG 9.10.6 <<>> @127.0.0.1 example.com ANY
; (1 server found)
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 7064
;; flags: qr aa rd; QUERY: 1, ANSWER: 2, AUTHORITY: 0, ADDITIONAL: 1
;; WARNING: recursion requested but not available

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 1232
;; QUESTION SECTION:
;example.com.                   IN      ANY

;; ANSWER SECTION:
example.com.            300     IN      SOA     ns1.example.com. admin.example.com. 2025010101 3600 900 604800 300
example.com.            300     IN      NS      ns1.example.com.

;; Query time: 1 msec
;; SERVER: 127.0.0.1#53(127.0.0.1)
;; WHEN: Thu Feb 19 06:51:12 CST 2026
;; MSG SIZE  rcvd: 100
```

```bash=7
dig @127.0.0.1 version.bind TXT CHAOS
```
```
; <<>> DiG 9.10.6 <<>> @127.0.0.1 version.bind TXT CHAOS
; (1 server found)
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 26953
;; flags: qr aa rd; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 1
;; WARNING: recursion requested but not available

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 1232
;; QUESTION SECTION:
;version.bind.                  CH      TXT

;; ANSWER SECTION:
version.bind.           0       CH      TXT     "not disclosed"

;; Query time: 1 msec
;; SERVER: 127.0.0.1#53(127.0.0.1)
;; WHEN: Thu Feb 19 06:51:19 CST 2026
;; MSG SIZE  rcvd: 67
```




## Test Result Analysis


Everything is normal; all tests pass:

| Item | Test | Result | Notes |
| --- | --- | --- | --- |
| 01 | `home.example.com A` | `127.0.0.1` | Dynamic record exists, TTL 300 is correct |
| 02 | `example.com SOA` | `ns1.example.com. admin.example.com.` | Zone authority information is correct |
| 03 | `example.com NS` | `ns1.example.com.` + glue record | NS and its A record are returned correctly |
| 04 | `example.com ANY` | SOA + NS (2 records) | Zone is complete |
| 05 | `version.bind TXT CHAOS` | `"not disclosed"` | Version hiding is active; security is OK |
| 06 | `flags: qr aa rd` | `aa` (authoritative answer) | BIND9 is correctly operating as an authoritative server |
| 07 | `recursion requested but not available` | Expected behavior | `recursion no` is configured correctly |



# Dynamic Operation Guide - Test Method

Dynamic DNS update — complete operation guide
------------------

### Step 1: Open Reflex UI

Open **http://localhost:3000** in your browser.

### Step 2: Fill the Configuration Form

On the Configuration page, fill in the following values:

| Field | Value | Description |
| --- | --- | --- |
| **Primary Nameserver** | `127.0.0.1` | BIND9 and Reflex are in the same container, so localhost is used |
| **DNS Zone** | `example.com` | Must match the zone name in BIND9 configuration |
| **Record Hostname** | `home` | Subdomain to update dynamically (`home.example.com`) |
| **Record Type** | `A (IPv4)` | Select A in the dropdown |
| **TTL (Seconds)** | `300` | Default is fine |
| **TSIG Key Name** | `ddns-key` | Must match key name in BIND9 config |
| **TSIG Key Secret** | `yfy0mnBZvA1pXv/hqJxNefx6R6RwZG7jXLYT6YcAM2g=` | Secret generated by `generate_tsig_key.sh` |

After filling all fields, click **Save**.

### Step 3: Detect IP and Trigger DNS Update

1. On Dashboard, click **Check Now** — this checks your external IP from `api64.ipify.org`.
2. After detection succeeds, click **Update DNS** — this sends a dynamic update to BIND9 via RFC 2136.

### Step 4: Verify Updated Result with dig
```bash
# Query updated record (should change from 127.0.0.1 to your external IP)
dig @127.0.0.1 home.example.com A +short

# Full output
dig @127.0.0.1 home.example.com A

# Check whether SOA serial increased (BIND9 auto-increments on each dynamic update)
dig @127.0.0.1 example.com SOA +short
```

### Expected Result

**Before update:**

```bash
$ dig @127.0.0.1 home.example.com A +short
127.0.0.1
```

**After update:**

```bash
$ dig @127.0.0.1 home.example.com A +short
<your external IP, e.g. 203.0.113.42>
```

### Debug Commands

If update fails, check:

```bash
# BIND9 dynamic update log
docker exec re-ddns cat /var/log/bind/update.log

# BIND9 main log
docker exec re-ddns cat /var/log/bind/named.log

# Overall container log
docker compose logs --tail=30

# Manual nsupdate test (inside container)
docker exec -it re-ddns bash -c '
nsupdate -y hmac-sha256:ddns-key:yfy0mnBZvA1pXv/hqJxNefx6R6RwZG7jXLYT6YcAM2g= <<EOF
server 127.0.0.1
zone example.com
update delete test.example.com A
update add test.example.com 300 A 1.2.3.4
send
EOF
'

# Verify manual update
dig @127.0.0.1 test.example.com A +short
# Expected output: 1.2.3.4

```