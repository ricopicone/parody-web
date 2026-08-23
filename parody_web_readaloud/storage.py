"""Where generated audio lives.

Two backends behind the same three verbs, chosen by one setting:

    PARODY_WEB_READALOUD_BUCKET unset -> DiskAudio, under the cache directory
    PARODY_WEB_READALOUD_BUCKET set   -> S3Audio,   under a key prefix

The reason for the second is HTTP Range, not disk. Serving audio from Django
means hand-rolling Range — `FileResponse` answers a Range request with 200 and
the whole file, so the browser cannot seek at all — and that cost three rounds
of debugging a click path that was never at fault. S3 does Range natively; a
redirect hands the problem to something that has already solved it.

Disk stays because `runserver` must need no AWS, and a developer who cannot
seek locally cannot test seeking.

`ReadAlongTrack.audio_name` is a NAME, not a path. That is what lets the root
move from a directory to a bucket without touching a single row.
"""

from pathlib import Path

from django.conf import settings

AUDIO_CONTENT_TYPE = "audio/mpeg"

DEFAULT_PREFIX = "readalong/"
DEFAULT_REGION = "us-west-2"
DEFAULT_EXPIRE = 3600


def safe_name(name: str) -> str:
    """Reject a name that could address anything but a file in its own root.

    Names are generated from `text_key` and the voice and never come from a
    reader, but the check stands anyway: a malformed row must not be able to
    reach outside the cache directory or the key prefix.
    """
    if not name:
        raise ValueError("empty audio name")
    if "/" in name or "\\" in name:
        raise ValueError(f"audio name contains a path separator: {name!r}")
    if name in (".", ".."):
        # Both name the root itself, which then passes the containment check
        # and is opened as a file. `.` reached that far.
        raise ValueError(f"audio name is not a file: {name!r}")
    return name


def cache_root() -> Path:
    value = getattr(settings, "PARODY_WEB_READALOUD_CACHE", "")
    if not value:
        raise RuntimeError(
            "PARODY_WEB_READALOUD_CACHE is unset; read-along cannot store or "
            "serve audio. Set it to a writable directory, or set "
            "PARODY_WEB_READALOUD_BUCKET to keep audio in S3.")
    return Path(value)


def audio_path(name: str) -> Path:
    """Resolve a track's audio file inside the cache.

    Belt and braces behind `safe_name`: a symlink in the cache could still
    resolve outside it.
    """
    safe_name(name)
    root = cache_root().resolve()
    path = (root / name).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"audio name escapes the cache root: {name!r}")
    return path


class DiskAudio:
    """Audio as files under PARODY_WEB_READALOUD_CACHE."""

    def path(self, name: str) -> Path:
        return audio_path(name)

    def write(self, name: str, data: bytes) -> None:
        path = audio_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def exists(self, name: str) -> bool:
        return audio_path(name).exists()

    def url(self, name: str):
        """No URL of its own: the caller serves the bytes itself."""
        return None


_CLIENTS = {}


def _s3_client(region: str, key_id: str = ""):
    """A cached boto3 S3 client.

    Signature v4 explicitly, because a presigned v2 URL is refused by buckets
    in regions created after 2014. Credentials come from settings when a host
    sets them and from boto3's default chain when it does not — which is how
    production works: the EC2 instance role, not a key pair in the environment.
    """
    cached = _CLIENTS.get((region, key_id))
    if cached is not None:
        return cached
    import boto3
    from botocore.client import Config

    client = boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=getattr(settings, "AWS_ACCESS_KEY_ID", None) or None,
        aws_secret_access_key=(
            getattr(settings, "AWS_SECRET_ACCESS_KEY", None) or None),
        config=Config(signature_version="s3v4"),
    )
    _CLIENTS[(region, key_id)] = client
    return client


class S3Audio:
    """Audio as objects under a key prefix in one bucket.

    Reading is a redirect to a presigned URL, minted only after the access
    check the view already made. The bucket path is not public and not
    guessable: keys are sha256 text keys.
    """

    def __init__(self, bucket, prefix=DEFAULT_PREFIX, region=DEFAULT_REGION,
                 expire=DEFAULT_EXPIRE, sse=""):
        self.bucket = bucket
        self.prefix = prefix
        self.region = region
        self.expire = expire
        self.sse = sse

    @property
    def client(self):
        return _s3_client(
            self.region, getattr(settings, "AWS_ACCESS_KEY_ID", "") or "")

    def key(self, name: str) -> str:
        return f"{self.prefix}{safe_name(name)}"

    def path(self, name: str):
        """No local path: there is no file to stream."""
        return None

    def write(self, name: str, data: bytes) -> None:
        # ContentType at PUT time rather than as a presign override: the object
        # then serves correctly however it is reached, including by anything
        # that is not this view.
        params = {"Bucket": self.bucket, "Key": self.key(name), "Body": data,
                  "ContentType": AUDIO_CONTENT_TYPE}
        if self.sse:
            params["ServerSideEncryption"] = self.sse
        self.client.put_object(**params)

    def exists(self, name: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=self.key(name))
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            # AccessDenied, NoSuchBucket, a throttle: not an absence, and
            # reporting it as one would hide a misconfiguration behind a 404
            # that looks exactly like an ungenerated track.
            raise
        return True

    def url(self, name: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self.key(name)},
            ExpiresIn=self.expire,
        )


def backend():
    """The configured audio store.

    Raises RuntimeError when neither a bucket nor a cache directory is set —
    the caller turns that into a 404, because a reader can do nothing with the
    difference between "not configured" and "not generated".
    """
    bucket = getattr(settings, "PARODY_WEB_READALOUD_BUCKET", "") or ""
    if not bucket:
        cache_root()  # raises when unset, which is the whole check
        return DiskAudio()
    return S3Audio(
        bucket=bucket,
        prefix=getattr(settings, "PARODY_WEB_READALOUD_PREFIX",
                       DEFAULT_PREFIX) or "",
        region=(getattr(settings, "PARODY_WEB_READALOUD_REGION", "")
                or getattr(settings, "AWS_S3_REGION_NAME", "")
                or DEFAULT_REGION),
        expire=getattr(settings, "PARODY_WEB_READALOUD_URL_EXPIRE",
                       DEFAULT_EXPIRE),
        # Inherited, unlike the bucket: a bucket policy that requires
        # server-side encryption would otherwise reject every put with no
        # obvious cause.
        sse=(getattr(settings, "PARODY_WEB_READALOUD_SSE", None)
             if getattr(settings, "PARODY_WEB_READALOUD_SSE", None) is not None
             else getattr(settings, "AWS_S3_SSE", "")) or "",
    )


def write_audio(name: str, data: bytes) -> None:
    backend().write(name, data)
