# azautov2ray

Automatic Xray **VLESS + Reality** relay for a Linux VPS.

Fetches your subscription configs, tests them (TCP → real delay → download speed), picks the best upstream, exposes a stable Reality inbound for your phone/PC, and auto-fails over when the selected node dies.

## One-line install (VPS)

```bash
curl -fsSL https://raw.githubusercontent.com/AliZolfaghar/azautov2ray/main/install.sh | sudo bash
```

Interactive prompts work with the pipe above (reads from `/dev/tty`). Alternatives:

```bash
sudo bash <(curl -fsSL https://raw.githubusercontent.com/AliZolfaghar/azautov2ray/main/install.sh)
```

Or after cloning:

```bash
sudo bash install.sh
```

### First run

The script detects that nothing is installed and asks:

- Domain (optional — if empty, public IP is used in the client link)
- Public IP (auto-detected, confirm)
- Reality port (default `443`)
- Reality dest / SNI (default `www.microsoft.com:443`)
- Subscription URL(s)
- Observer interval & fail threshold
- Whether to open the firewall port

Then it automatically:

1. Installs Python deps + downloads **Xray-core**
2. Generates Reality keys / UUID / shortId
3. Tests subscription nodes and selects the best
4. Writes `/etc/azautov2ray/config.yaml` + `xray.json`
5. Installs systemd units and starts them
6. Prints a **VLESS Reality link** and **QR code**

### Later runs

```bash
sudo bash install.sh
```

Management menu:

1. Status  
2. Show Reality QR / link  
3. Retest subscriptions & apply best  
4. Edit settings  
5. Restart services  
6. Reinstall (keep downloads)  
7. Uninstall  

**Reinstall** re-runs the setup wizard without deleting `/opt` downloads: existing Xray binary and Python venv packages are reused. You can keep Reality keys (same QR) or regenerate them.

After install you can also run:

```bash
sudo azautov2ray            # management menu
sudo azautov2ray status
sudo azautov2ray qr
sudo azautov2ray retest
sudo azautov2ray reinstall
```

## Config

`/etc/azautov2ray/config.yaml`

```yaml
server:
  domain: vpn.example.com
  public_ip: "1.2.3.4"
  reality_port: 443
  reality_dest: "www.microsoft.com:443"
  reality_server_names: ["www.microsoft.com"]

subscriptions:
  # Predefined during setup (can add more):
  - https://raw.githubusercontent.com/barry-far/V2ray-config/main/All_Configs_base64_Sub.txt
  # - https://example.com/sub1

testing:
  ping_timeout_ms: 1500
  real_delay_url: "https://www.google.com/generate_204"
  real_delay_max_ms: 2000
  speed_url: "https://speed.cloudflare.com/__down?bytes=10000000"
  speed_timeout_s: 15
  max_candidates_for_speed: 10
  concurrency: 20
  real_delay_concurrency: 50   # test real-delay in parallel batches
  only_ports: [443]            # non-443 nodes discarded before testing
  only_reality: true           # only Reality (security=reality + pbk) kept

observer:
  interval_s: 60
  fail_threshold: 3
  rescan_on_fail: true

generated:
  uuid: "..."
  reality_private_key: "..."
  reality_public_key: "..."
  short_id: "..."
```

Your phone/PC always connect to **this VPS** via Reality. Only the upstream node behind the VPS changes — no need to re-scan the QR when failover happens.

## Layout

| Path | Purpose |
|------|---------|
| `/opt/azautov2ray` | App code, venv, Xray binary |
| `/etc/azautov2ray` | `config.yaml`, `xray.json`, `state.json`, logs |
| `azautov2ray-xray.service` | Xray process |
| `azautov2ray-observer.service` | Health check + failover |

## Requirements

- Linux VPS with public IP (domain optional)
- Root (`sudo`)
- Outbound internet (to fetch subscriptions and download Xray)

## License

AGPL-3.0 — see [LICENSE](LICENSE).
