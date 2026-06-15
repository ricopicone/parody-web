release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
web: gunicorn booksite.wsgi:application -k uvicorn.workers.UvicornWorker --log-file -
