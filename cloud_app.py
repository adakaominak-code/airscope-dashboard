"""Free-host entry point. Rebuild the read-only database from the bundled snapshot."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import tempfile
import streamlit as st

ROOT = Path(__file__).resolve().parent


@st.cache_resource
def prepare_snapshot():
    metadata = json.loads((ROOT / 'cloud_data' / 'manifest.json').read_text())
    folder = Path(tempfile.gettempdir()) / 'airscope'
    folder.mkdir(exist_ok=True)
    target = folder / (metadata['sha256'] + '.sqlite')
    if not target.exists():
        with tempfile.NamedTemporaryFile(dir=folder, delete=False) as output:
            temporary = Path(output.name)
            with gzip.open(ROOT / 'cloud_data' / 'airscope.sqlite.gz', 'rb') as source:
                shutil.copyfileobj(source, output)
        with temporary.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        if digest != metadata['sha256']:
            temporary.unlink()
            raise RuntimeError('The online data snapshot failed its integrity check.')
        temporary.replace(target)
    return str(target)


os.environ['AIRSCOPE_SQLITE_PATH'] = prepare_snapshot()
runpy.run_path(str(ROOT / 'src' / 'dashboard' / 'app.py'), run_name='__main__')
