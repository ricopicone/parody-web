# AWS deploy (SSM + GitHub Actions) — multi-book

The **same** `parody-book-host` repo deploys every book site. A site = one EC2
instance (or one service) running this code, configured for a book via
`/etc/parody-book-host/site.env`, pulling that book's content from its own
content-repo release. Update the host once → redeploy all sites. No per-book
code, no forks.

```
GitHub Actions (this repo)                      EC2 instance (per site)
  push to main / dispatch                         /opt/parody-book-host  (this repo)
  └─ assume AWS role (OIDC)                        /etc/parody-book-host/site.env  (book + secrets)
     └─ ssm send-command  ───────────────────────► deploy/deploy.sh
                                                      git reset --hard <sha>
                                                      pip install / migrate / collectstatic
                                                      gh release download (book content) + import_artifact
                                                      systemctl restart  → gunicorn ← nginx ← ACM/Route53
```

## One-time AWS setup

1. **OIDC role for GitHub Actions.** Create an IAM role trusted by GitHub's OIDC
   provider (`token.actions.githubusercontent.com`), scoped to this repo, with
   permission to `ssm:SendCommand` / `ssm:GetCommandInvocation` on the target
   instances. Put its ARN in repo **secret** `AWS_DEPLOY_ROLE_ARN`.
2. **Target map.** Set repo **variable** `DEPLOY_SITES` to a JSON array (shape in
   `deploy/sites.example.json`): `[{name, region, instance_id, app_dir}]`. Add an
   entry per book site — that's the only change to onboard a new site here.
3. **RDS Postgres** per site (or one cluster, a DB per site); put its URL in the
   instance's `site.env` as `DATABASE_URL`.
4. **Route53 + ACM** for each domain (e.g. `rtcbook.org`); TLS at nginx
   (certbot) or an ALB.

## Per-instance setup (once per site)

```bash
sudo useradd -r -m -d /opt/parody-book-host bookhost
sudo -u bookhost git clone https://github.com/ricopicone/parody-book-host /opt/parody-book-host
sudo -u bookhost python3 -m venv /opt/parody-book-host/.venv
sudo -u bookhost /opt/parody-book-host/.venv/bin/pip install -r /opt/parody-book-host/requirements.txt

sudo install -d -m 750 -o bookhost /etc/parody-book-host
sudo cp deploy/site.env.example /etc/parody-book-host/site.env   # then edit (chmod 600)
sudo install -d -o bookhost /var/lib/parody-book-host/media

sudo cp deploy/systemd/parody-book-host.service /etc/systemd/system/
sudo systemctl enable --now parody-book-host
sudo cp deploy/nginx/parody-book-host.conf /etc/nginx/sites-available/<domain>
sudo ln -s /etc/nginx/sites-available/<domain> /etc/nginx/sites-enabled/ && sudo nginx -s reload

# the SSM agent (root) runs deploy.sh; let it act as bookhost + restart the unit:
#   - clone owned by bookhost; deploy.sh uses `sudo systemctl restart`
#   - install gh CLI + unzip; GH_TOKEN (read-only to content repos) in site.env
sudo -u bookhost /opt/parody-book-host/.venv/bin/python manage.py migrate
sudo -u bookhost /opt/parody-book-host/.venv/bin/python manage.py createsuperuser   # the owner
```

> The SSM command in `.github/workflows/deploy.yml` runs `deploy.sh` as root with
> `sudo -E`; ensure the instance's SSM agent has an instance profile and that
> `git`/`systemctl` operate on the bookhost-owned clone (adjust the `sudo -u
> bookhost` wrapping in `deploy.sh`/the SSM command to taste for your hardening).

## Routine deploys

- **Host code change:** push to `main` → CI redeploys every site in `DEPLOY_SITES`.
- **New book content:** cut a release in the book's content repo, then run the
  **Deploy** workflow (dispatch) with that `site` and `release_tag` — or have the
  content repo fire a `repository_dispatch`/`workflow_dispatch` at this repo on
  release.

## Add a new book site

1. New EC2 instance (+ DB, domain, TLS); per-instance setup above with that
   book's `site.env` (`BOOK_SLUG`, `CONTENT_REPO`, `ARTIFACT_ASSET`, hosts).
2. Append it to the `DEPLOY_SITES` repo variable.
3. Run the Deploy workflow for it. Done — no code changes.
