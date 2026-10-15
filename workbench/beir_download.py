"""Download a BEIR-format dataset from the Hugging Face Hub (standard library only).

Fetches ``corpus.jsonl``, ``queries.jsonl`` and ``qrels/<split>.tsv`` from a
``mteb/<name>`` dataset repo, which uses the BEIR layout that
workbench/real_scifact.py reads. This needs network access to huggingface.co.
Pass a commit SHA as ``revision`` to pin the data; the default, ``main``, is
whatever the repo holds today. Set OSIRIS_HF_DATASET_URL to use a mirror.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from typing import Dict, List

HF_DATASET_URL = os.environ.get(
    "OSIRIS_HF_DATASET_URL", "https://huggingface.co/datasets/{repo}/resolve/{revision}/{path}"
)
SOURCE_FILE = "SOURCE.json"


class BeirDownloadError(RuntimeError):
    """A dataset file could not be downloaded."""


def split_files(split: str) -> List[str]:
    return ["corpus.jsonl", "queries.jsonl", f"qrels/{split}.tsv"]


def file_digests(data_dir: str, split: str) -> Dict[str, Dict[str, object]]:
    """SHA-256 and size of each BEIR file of the split that exists in ``data_dir``."""
    digests: Dict[str, Dict[str, object]] = {}
    for rel in split_files(split):
        path = os.path.join(data_dir, rel)
        if not os.path.isfile(path):
            continue
        sha = hashlib.sha256()
        size = 0
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                sha.update(chunk)
                size += len(chunk)
        digests[rel] = {"sha256": sha.hexdigest(), "bytes": size}
    return digests


def download_beir(
    name: str,
    dest: str,
    split: str = "test",
    revision: str = "main",
    repo: str | None = None,
    url_template: str | None = None,
    timeout: float = 120.0,
) -> List[str]:
    """Download the split's BEIR files (default repo ``mteb/<name>``) into ``dest``.

    Files that already exist are kept. Returns the files that were downloaded.
    """
    repo = repo or f"mteb/{name}"
    url_template = url_template or HF_DATASET_URL
    downloaded = []
    for rel in split_files(split):
        target = os.path.join(dest, rel)
        if os.path.isfile(target):
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        url = url_template.format(repo=repo, revision=revision, path=rel)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".download-")
        try:
            with os.fdopen(fd, "wb") as out, urllib.request.urlopen(url, timeout=timeout) as resp:
                for chunk in iter(lambda: resp.read(1 << 20), b""):
                    out.write(chunk)
            os.replace(tmp, target)
        except (urllib.error.URLError, OSError) as e:
            if isinstance(e, urllib.error.HTTPError):
                e.close()
            if os.path.exists(tmp):
                os.remove(tmp)
            raise BeirDownloadError(
                f"Could not download {url}: {e}. Downloading needs network access to huggingface.co; "
                "you can also put corpus.jsonl, queries.jsonl and qrels/<split>.tsv in the directory yourself."
            ) from e
        downloaded.append(rel)

    source_path = os.path.join(dest, SOURCE_FILE)
    if downloaded or not os.path.exists(source_path):
        with open(source_path, "w", encoding="utf-8") as f:
            json.dump({"name": name, "repo": repo, "revision": revision, "url_template": url_template},
                      f, indent=2, sort_keys=True)
    return downloaded
