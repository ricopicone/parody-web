# Read-along audio on S3

**Task:** parody #647 — store generated read-along audio in S3 rather than on the box.

## Why

The reason is **HTTP Range**, not disk.

`parody_web_readaloud/views.py` hand-rolls Range handling — parses the header,
slices the file, sets `Content-Range`/`Accept-Ranges`, returns 206 — because
Django's `FileResponse` answers a Range request with **200 and the whole file**.
Project memory `media-endpoints-must-serve-byte-ranges` records what that cost:
the browser could not seek at all, and it took three rounds of debugging the
click path, which was never at fault. S3 does Range natively. Serving from S3
takes that whole category out of parody-web's hands.

Disk is the weaker reason. The audio is 62 MB today. It is real but small.

There is a third reason the brief names in passing and which matters more than
either: audio lives at `/srv/parody/readalong`, **outside the checkout**,
because `deploy_ec2.sh` runs `git clean -fdx`. That constraint disappears.

## What does not change

- Synthesis still happens only in `generate_readalong`. Nothing is ever
  synthesised on a request. That is the property that makes cost track content
  rather than listeners, and no part of this touches it.
- Gating is unchanged: `_track_or_404` asks the access policy exactly the
  question `parody_web.views.section_pdf` asks, and it asks it **before** a URL
  is minted.
- `ReadAlongTrack.audio_name` stays a name, not a path — which is precisely why
  the root can move from a directory to a bucket without a migration.
- Local dev keeps working with no AWS at all.

## The seam

`storage.py` is three functions over a directory. It becomes two backends over
the same three verbs, chosen by one setting.

```
                     PARODY_WEB_READALOUD_BUCKET
                       ""                 set
                        │                  │
                   DiskAudio           S3Audio
   write   name -> file in cache    put_object, ContentType audio/mpeg
   exists  Path.exists()            head_object
   url     None                     presigned GET, short-lived
   path    Path                     None
```

`views.audio` asks for a `url()`. If it gets one it redirects; if it gets `None`
it falls back to `_ranged`, which stays exactly as it is and is now the
**local-dev path only**. Keeping it is not reluctance to delete: `runserver`
must need no AWS, and a developer who cannot seek locally cannot test seeking.

### Names

Both backends run one shared `safe_name()`. Names are generated from `text_key`
+ voice and never come from a reader, but the check stands anyway — a malformed
row must not be able to address a file outside its root. `safe_name` rejects
empty names, path separators, and `..`; `DiskAudio` additionally keeps the
existing resolve-and-contain check behind it.

## Settings

| setting | default | meaning |
|---|---|---|
| `PARODY_WEB_READALOUD_BUCKET` | `""` (disk) | S3 bucket holding generated audio |
| `PARODY_WEB_READALOUD_PREFIX` | `"readalong/"` | key prefix inside that bucket |
| `PARODY_WEB_READALOUD_REGION` | `AWS_S3_REGION_NAME`, else `us-west-2` | |
| `PARODY_WEB_READALOUD_URL_EXPIRE` | `3600` | seconds a minted audio URL stays valid |
| `PARODY_WEB_READALOUD_SSE` | `AWS_S3_SSE` if set, else `""` | `ServerSideEncryption` on put |
| `PARODY_WEB_READALOUD_CACHE` | `""` | unchanged; required only when no bucket is set |

The bucket is **not** inherited from `AWS_STORAGE_BUCKET_NAME`. parody-web is
book-agnostic and installed into hosts it knows nothing about; writing into a
host's media bucket because it happened to configure one is a surprise. The
host opts in by name. Encryption, by contrast, *is* inherited — a bucket policy
that requires SSE would otherwise reject every put with no obvious cause.

## Expiry, and the one thing that can go wrong

A presigned URL dies twice over: at `ExpiresIn`, and — earlier — when the
credentials that signed it expire. On the box those are EC2 instance-role
credentials from IMDS, which rotate. `config/settings.py` already carries the
note: signed URLs "stop working when those credentials expire, which can be
well before `AWS_QUERYSTRING_EXPIRE`."

For a four-minute track played straight through this never bites; boto3
refreshes instance credentials ahead of expiry, so a freshly minted URL has
minutes to hours in hand. It bites for a reader who leaves the tab open over
lunch and then seeks. A media element keeps the redirect target for its
subsequent range requests, so that seek would 403 against a URL the page can no
longer refresh by itself.

Two guards, both small:

1. The redirect carries `Cache-Control: private, no-store`, so nothing reuses
   a dead URL out of a cache.
2. The client re-fetches once. On an audio `error` the player re-assigns
   `audio.src` to the same endpoint with a cache-busting parameter, restores
   `currentTime` through the existing `seekTo` path (which already waits for
   `loadedmetadata` — see `media-seeks-before-metadata-are-discarded`), and
   resumes if it was playing. Rate-limited to one retry per 10 s so a genuinely
   missing file cannot spin.

The alternative — proxying bytes from S3 through Django — was rejected. It puts
the box back in the path, pays for the bytes twice, and hand-rolls Range again,
which is the thing this change exists to stop doing.

## Migrating what exists

The 62 MB already on the box is **moved, not regenerated**. Regenerating costs
Polly money for audio that is byte-identical, and `text_key` exists precisely so
that unchanged words are never re-bought.

A new command does it:

    python manage.py sync_readalong_audio [--dry-run] [--from DIR]

It walks `ReadAlongTrack` rows with an `audio_name`, uploads any whose key is
missing from the bucket, and reports uploaded / already-there / **absent from
disk**. That last count is the one to read: a row whose file is not on disk is a
track that would 404 today, and the sync is where it becomes visible.

Local files are left alone. Deleting them is a separate decision, and this
change should be reversible by flipping one setting back.

## Boot-time refusal

`checks.py` gains one check, in the app's existing posture — misconfiguration
fails on boot, not at the first reader's request:

- bucket set, `boto3` not importable → `Error`. Serving from S3 needs boto3 to
  mint URLs, which is a genuine change: until now the `readalong` extra was a
  *generation-time* concern and a serving-only host needed neither boto3 nor
  PyMuPDF. `docs/host-integration.md` says so today and must stop saying it.

## AWS

No IAM change. The `homepagerico-ec2-role` inline policy `myAmazonS3FullAccess`
already grants `s3:GetObject`/`PutObject`/`DeleteObject`/`ListBucket` on
`arn:aws:s3:::homepagerico/*` — verified 2026-08-23.

Prefix is `readalong/`, deliberately not the `readaloud/` prefix already in the
bucket: that holds six unrelated mp3s from February and is nothing to do with
this app.

## Host side (homepage-django)

One settings line, inside the branch that already knows S3 is configured:

```python
PARODY_WEB_READALOUD_BUCKET = AWS_STORAGE_BUCKET_NAME
```

`PARODY_WEB_READALOUD_CACHE` stays set. It is what `sync_readalong_audio` reads
from, and it is the way back if the bucket has to be switched off.

## Tests

- `safe_name` rejects `../x`, `a/b`, `""`; `DiskAudio` still contains.
- Disk backend: unchanged behaviour, including every existing Range test.
- S3 backend, with a stubbed client: `write` puts under the prefix with
  `audio/mpeg`; `exists` maps `404`/`NoSuchKey` to `False` and re-raises the
  rest; `url` presigns the prefixed key with the configured expiry.
- View: bucket set + object present → 302 to the presigned URL, `no-store`;
  object absent → 404; a reader the policy refuses gets 404 **and no presign
  call is made** (the negative is the security-relevant assertion).
- `sync_readalong_audio`: uploads a missing key, skips a present one, counts a
  row whose file is gone, and `--dry-run` puts nothing.
- Client: `seek.test.js`-style extraction of the retry contract — one refetch
  per error, rate-limited, position preserved.
