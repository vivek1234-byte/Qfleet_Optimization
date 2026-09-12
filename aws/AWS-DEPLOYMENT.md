# Deploying QFleet on AWS

Everything here is in `aws/`: a compose file, an nginx config, a frontend
image and a bootstrap script. The short version is one EC2 instance running
two containers behind nginx, on one URL.

## Which AWS service

| Option | Cost | HTTPS | Suits |
|---|---|---|---|
| **EC2 + Docker Compose** ← described here | free tier 12 months (t3.micro), else ~$15/mo (t3.small) | needs a domain | a demo you control, always warm, no cold starts |
| App Runner (API) + Amplify (frontend) | ~$25–46/mo if always on; Amplify free tier | free, automatic | managed, closest to the Vercel/Render split you already have |
| ECS Fargate + ALB | ~$16/mo for the load balancer alone, plus tasks | free via ACM | production, several services, autoscaling |
| Lambda container + Function URL | pennies when idle | free | bursty traffic — but a 600 MB image cold-starts in 5–10 s, which is the worst possible moment during judging |

EC2 is the recommendation for a demo: one box, always warm, and the whole
product on a single origin — which removes CORS from the picture entirely.

## What "single origin" buys you

On Vercel + Render the bundle is on one domain and the API on another, so
every request is cross-origin: `QGF_CORS_ORIGINS` has to list the frontend,
and `VITE_API_BASE_URL` has to be compiled into the bundle at build time.
Change either and things break in ways that only show up in the browser
console.

Here nginx serves the built frontend and forwards `/api` to the API container
beside it. The app asks for `/api/...` on whatever host it was loaded from —
exactly as it does under the Vite dev proxy. No CORS list, no API base URL, no
build-time coupling to a hostname.

## Launch

1. **EC2 → Launch instance**
   - AMI: **Ubuntu Server 24.04 LTS**
   - Type: **t3.small** (2 GB). `t3.micro` is free-tier eligible and does work
     — the bootstrap adds swap for it — but the first build takes 10–15
     minutes instead of 3–4.
   - Storage: **20 GB** gp3 (the image is ~1.5 GB; 8 GB is uncomfortable).
   - Key pair: create one, so you can SSH in when something needs looking at.
   - Network: allow **HTTP (80)** from anywhere, and **SSH (22)** from *your
     IP only* — not `0.0.0.0/0`.
   - **Advanced details → User data**: paste the whole of `aws/ec2-bootstrap.sh`.
2. Launch. Watch it build:
   ```bash
   ssh -i your-key.pem ubuntu@<public-ip>
   sudo tail -f /var/log/cloud-init-output.log
   ```
3. When it says `QFleet is up on port 80`, open `http://<public-ip>/` and sign
   in with `ADMIN001` / `Admin@12345`.

**Allocate an Elastic IP and associate it** before you send the link anywhere.
A default public IP changes every time the instance stops, and an instance you
stop overnight to save credits comes back on a different address.

## Updating it

```bash
ssh ubuntu@<ip>
cd /opt/qfleet
git pull
docker compose -f aws/docker-compose.yml --env-file aws/.env up -d --build
```

The accounts database lives in a named volume (`qfleet-data`), so rebuilding
does not wipe the employees an administrator created.

## HTTPS

The instance serves plain HTTP. For a demo over a projector that is usually
fine, but a link you send someone will draw a "Not secure" badge, and some
networks interfere with plain HTTP.

Certificates need a domain name — there is no certificate authority that will
issue for a bare IP address. If you have one (or a free DuckDNS subdomain),
point an A record at the Elastic IP and swap nginx for Caddy, which obtains
and renews certificates by itself:

```yaml
  web:
    image: caddy:2-alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy-data:/data
```

```
# Caddyfile
qfleet.example.com {
    root * /usr/share/nginx/html
    handle /api/* { reverse_proxy api:8000 }
    handle { try_files {path} /index.html
             file_server }
}
```

If you would rather not manage certificates at all, that is the argument for
App Runner + Amplify: both hand you an HTTPS URL with nothing to configure.

## Cost control

The free tier covers 750 hours a month of `t3.micro` for twelve months —
one instance running continuously. Past that, or on `t3.small`:

- **Stop the instance** when you are not demoing. You pay for the EBS volume
  (~$1.60/month for 20 GB) and nothing else. With an Elastic IP attached, note
  that AWS bills a small hourly charge for an Elastic IP that is *not*
  associated with a running instance.
- Set a **billing alarm** at $5 in CloudWatch before you start. An instance
  left running for a month is the usual way a hackathon budget disappears.

## What was verified

The nginx configuration in `aws/nginx.conf` was run for real — `nginx -t`
clean, then serving the production bundle with `/api` proxied to the live
backend:

- deep link to `/simulator` resolves rather than 404ing (SPA fallback works);
- login succeeds against the proxied API with **no** `VITE_API_BASE_URL` in
  the build and **no** CORS configuration on the backend;
- the header health badge reads *API healthy* — all four backend checks green;
- the Fuel Prediction page finds its trained model;
- no console errors anywhere in the run.

`aws/docker-compose.yml` parses, and the API image it builds is the same
`Dockerfile` already verified by running its entrypoint directly. The one
thing not exercised is `docker build` itself — this sandbox has no Docker
daemon — and the AWS console steps above are instructions, not something that
was executed.
