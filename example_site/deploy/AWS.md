# AWS deploy (SSM + GitHub Actions)

A **book site** is its own small repo (generate it from `example_site/`): a thin
Django project that pins the `parody-web` package + this deploy glue. It deploys
to one EC2 instance, configured for a book via `/etc/parody-book-host/site.env`,
pulling that book's content from its own content-repo release. The shared deploy
logic lives in `parody-web` as a **reusable workflow**, so improving it once
updates every book site.

```
book-site repo (this template)              EC2 instance
  push to main / dispatch
  └─ uses: ricopicone/parody-web/.github/workflows/deploy-reusable.yml
       └─ assume AWS role (OIDC) ─ ssm send-command ─► deploy/deploy.sh
                                                         git reset --hard <sha>
                                                         pip install (pulls parody-web)
                                                         migrate / collectstatic
                                                         gh release download (content) + import_artifact
                                                         systemctl restart → gunicorn ← nginx ← ACM/Route53
```

## One-time AWS
- **OIDC role** trusted by GitHub for this book-site repo, allowed `ssm:SendCommand`
  / `ssm:GetCommandInvocation` on the instance → repo **secret** `AWS_DEPLOY_ROLE_ARN`.
- Repo **variables**: `AWS_REGION`, `INSTANCE_ID`, `APP_DIR` (the clone path).
- **RDS Postgres** (→ `DATABASE_URL` in site.env); **Route53 + ACM** for the domain.

## Per-instance setup (once)
```bash
sudo useradd -r -m -d /opt/<site> bookhost
sudo -u bookhost git clone https://github.com/<you>/<book-site-repo> /opt/<site>
sudo -u bookhost python3 -m venv /opt/<site>/.venv
sudo -u bookhost /opt/<site>/.venv/bin/pip install -r /opt/<site>/requirements.txt
sudo install -d -m 750 -o bookhost /etc/parody-book-host
sudo cp deploy/site.env.example /etc/parody-book-host/site.env   # edit (chmod 600)
sudo install -d -o bookhost /var/lib/parody-book-host/media
sudo cp deploy/systemd/parody-book-host.service /etc/systemd/system/
sudo systemctl enable --now parody-book-host
sudo cp deploy/nginx/parody-book-host.conf /etc/nginx/sites-available/<domain>
sudo ln -s /etc/nginx/sites-available/<domain> /etc/nginx/sites-enabled/ && sudo nginx -s reload
# install gh + unzip; put a read-only GH_TOKEN for the content repo in site.env
sudo -u bookhost /opt/<site>/.venv/bin/python manage.py migrate
sudo -u bookhost /opt/<site>/.venv/bin/python manage.py createsuperuser   # the owner
```

## Routine deploys
- **Renderer update:** bump `parody-web` in `requirements.txt` (Dependabot can
  auto-PR) → push → CI deploys.
- **Site/template change:** push to the book-site repo's `main` → CI deploys.
- **New book content:** cut a release in the book's content repo, then run the
  **Deploy** workflow (dispatch) with that `release_tag`.

## A new book site
1. Generate a repo from `example_site/`; set its `site.env` (`BOOK_SLUG`,
   `CONTENT_REPO`, hosts, `DATABASE_URL`) and `requirements.txt` pin.
2. Provision instance + DB + domain (above); set repo vars/secret.
3. Push. No renderer code is copied — it comes from the `parody-web` pin.
