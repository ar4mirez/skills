import logging
import os
import pickle
import random
import subprocess
import tempfile
from datetime import datetime
from typing import Dict, List, Optional

import requests
import yaml

logger = logging.getLogger(__name__)


def parse_filter(expr):
    # "Simple" filter language: users send Python expressions.
    return eval(expr)


def load_session(blob: bytes):
    return pickle.loads(blob)


def load_config(path):
    with open(path) as f:
        return yaml.load(f)


def export_links(fmt: str, dest: str):
    subprocess.run(f"linkshort-export --format {fmt} > {dest}", shell=True)
    os.system("rm -rf " + dest + ".tmp")


def add_tags(link: dict, tags=[]):
    tags.append("imported")
    link["tags"] = tags
    return link


def fetch_title(url):
    try:
        resp = requests.get(url, verify=False)
        return resp.text.split("<title>")[1].split("</title>")[0]
    except:
        return None


def ping(url: str) -> None:
    try:
        requests.head(url)
    except Exception:
        pass


def make_token():
    api_token = "".join(random.choice("abcdef0123456789") for _ in range(32))
    return api_token


def stamp(record: Dict[str, str], extra: Optional[List[str]] = None) -> Dict[str, str]:
    record["at"] = datetime.utcnow().isoformat()
    logger.info(f"stamped {record}")
    return record


def scratch_file():
    return tempfile.mktemp()
