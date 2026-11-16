# Running Desk Dashboard on Unraid

This guide runs the backend as one Docker Compose stack on Unraid 7.2 or later, with server metrics from Unraid's built-in GraphQL API. Every address below is a placeholder: swap in your own.

## 1. Install Docker Compose support

Install the **Docker Compose Manager** plugin from Community Applications (Apps → search "Compose Manager"). It adds a "Compose" section at the bottom of the **Docker** tab.

## 2. Make a folder for the stack

Keep the config and data on the array or cache pool, not on the flash drive, since `.env` holds secrets:

```bash
mkdir -p /mnt/user/appdata/desk-dashboard/data
cd /mnt/user/appdata/desk-dashboard
```

Copy `docker-compose.example.yml` and `.env.example` from this repository into that folder, named `docker-compose.yml` and `.env`. Then lock down the env file:

```bash
chmod 600 .env
```

## 3. Edit `docker-compose.yml` for Unraid

Unraid's appdata folders belong to `nobody:users` (99:100). The simplest setup runs the container as that user with a host folder for `/data`:

```yaml
services:
  dashboard:
    image: ghcr.io/snoopysneeze335/desk-dashboard:latest
    container_name: desk-dashboard
    user: "99:100"
    restart: unless-stopped
    env_file: .env
    ports:
      - "8080:8080"
    volumes:
      - /mnt/user/appdata/desk-dashboard/data:/data
    read_only: true
    tmpfs:
      - /tmp
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
```

Then make sure the data folder belongs to that user:

```bash
chown -R 99:100 /mnt/user/appdata/desk-dashboard/data
```

The image still runs as a non-root user (10001) if you leave out `user:`. In that case, run `chown 10001:10001` on the data folder instead.

If port 8080 is taken, change only the left side, for example `"8090:8080"`.

## 4. Create the stack in Compose Manager

1. Go to **Docker → Compose → Add New Stack** and name it `desk-dashboard`.
2. Under the advanced options, set the stack directory to `/mnt/user/appdata/desk-dashboard`. Compose Manager then uses the `docker-compose.yml` and `.env` in that folder. Otherwise it keeps stacks on the flash drive under `/boot/config/plugins/compose.manager/projects/`, which you don't want for secrets.
3. Click **Compose Up**.

**Where `.env` lives:** next to `docker-compose.yml`, in `/mnt/user/appdata/desk-dashboard/.env`. You can also edit it from the stack's **Edit Stack → ENV File** menu.

## 5. Unraid API key and GraphQL URL

1. In the Unraid web UI, open **Settings → Management Access → API Keys** and create a key with the **Viewer** role. Put it in `.env` as `UNRAID_API_KEY`.
2. Set `UNRAID_GRAPHQL_URL` to the web UI address plus `/graphql`:

   ```dotenv
   UNRAID_GRAPHQL_URL=http://192.168.1.10/graphql
   ```

   - **Use the server's LAN IP, not its Tailscale address.** The container reaches the host over the LAN bridge. A `100.x.y.z` Tailscale address may not be routable from inside a container, and with the Tailscale sidecar it would loop through the tailnet for no reason.
   - **Custom web UI port:** include it, for example `http://192.168.1.10:8088/graphql`.
   - **"Use SSL/TLS" set to Strict:** plain-HTTP requests get redirected, and a redirected POST loses its body. Use the `https://…myunraid.net/graphql` address that Unraid shows for the LAN IP. It has a valid certificate; the dashboard always verifies certificates and won't accept a self-signed one.

3. Check it from the Unraid terminal (replace the key):

   ```bash
   curl -s -X POST http://192.168.1.10/graphql \
     -H 'Content-Type: application/json' -H 'x-api-key: YOUR_VIEWER_KEY' \
     -d '{"query":"{ metrics { cpu { percentTotal } memory { percentTotal } } }"}'
   ```

   You should see `{"data":{"metrics":{"cpu":{"percentTotal":…},"memory":{"percentTotal":…}}}}`.

**Without the API:** set `SERVER_METRICS_SOURCE=host`. The container then reads host-wide CPU and RAM from `/proc`. The numbers can differ slightly from Unraid's dashboard, because Unraid counts cached memory differently.

## 6. Tailscale (optional)

To reach the dashboard over HTTPS from anywhere on your tailnet, add the sidecar from [`deploy/tailscale/`](tailscale/compose.tailscale.yml):

1. Copy the `deploy/tailscale/` folder into `/mnt/user/appdata/desk-dashboard/deploy/tailscale/`.
2. Add `TS_AUTHKEY=tskey-auth-…` to `.env`.
3. Merge the override into your `docker-compose.yml`, or run it from the Unraid terminal:

   ```bash
   cd /mnt/user/appdata/desk-dashboard
   docker compose -f docker-compose.yml -f deploy/tailscale/compose.tailscale.yml up -d
   ```

The dashboard is then at `https://desk-dashboard.example.ts.net/`, with your own tailnet name in place of `example`. The first HTTPS request can take a few seconds while Tailscale gets the certificate. HTTPS certificates must be turned on for your tailnet in the Tailscale admin console.

If you use the sidecar, put a host folder owned by the container user, or a named volume, at `/var/lib/tailscale`, so the node keeps its identity across restarts.

## 7. Updating

In Compose Manager, click **Update Stack**. From the terminal, run `docker compose pull && docker compose up -d`. The quota counter and holdings cache in `data/` survive updates, so an update never causes an extra SimpleFIN fetch.
