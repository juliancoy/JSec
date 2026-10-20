#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run this script with sudo to install camera isolation.' >&2
    exit 1
fi
command -v nft >/dev/null
mkdir -p /etc/okam-local
cat > /etc/okam-local/firewall.nft <<'RULES'
# Only the dedicated camera interface is affected.
# Replacing this table in one transaction makes repeated starts safe.
add table inet okam_local
delete table inet okam_local
 table inet okam_local {
    chain forward {
        type filter hook forward priority -200; policy accept;
        iifname "wlp2s0" counter drop comment "No internet or LAN routing from camera"
        oifname "wlp2s0" counter drop comment "No routing into camera network"
    }
    chain output {
        type filter hook output priority -200; policy accept;
        oifname "wlp2s0" ip daddr 192.168.168.1 counter accept
        oifname "wlp2s0" udp sport 68 udp dport 67 counter accept
        oifname "wlp2s0" counter drop comment "Camera interface carries local camera traffic only"
    }
    chain input {
        type filter hook input priority -200; policy accept;
        iifname "wlp2s0" ip saddr 192.168.168.1 udp sport 67 udp dport 68 counter accept
        iifname "wlp2s0" ip saddr 192.168.168.1 ct state established,related counter accept
        iifname "wlp2s0" counter drop comment "No unsolicited access from camera network"
    }
 }
RULES
nft --check --file /etc/okam-local/firewall.nft
cat > /etc/systemd/system/okam-camera-isolation.service <<'SERVICE'
[Unit]
Description=Isolate O-KAM Wi-Fi from internet and LAN forwarding
Before=NetworkManager.service
After=nftables.service

[Service]
Type=oneshot
ExecStart=/usr/sbin/nft --file /etc/okam-local/firewall.nft
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SERVICE
systemctl daemon-reload
systemctl enable okam-camera-isolation.service
systemctl restart okam-camera-isolation.service
nft list table inet okam_local
echo 'Camera interface isolation is active and will load at boot.'
