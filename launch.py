"""Start once, detached from the terminal; never relies on an internet connection."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser
import app_paths

URL='http://127.0.0.1:8766'

def health():
    try:
        # Ignore environment/system proxy configuration for loopback probes.
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL+'/api/health',timeout=1) as response:
            return json.load(response)
    except (OSError,ValueError): return None

def main():
    state=health()
    if state:
        if state.get('app')!='Forge Player' or state.get('version')!='0.50':
            raise SystemExit('A different server is on port 8766. Close that Forge server before opening 0.50.')
        webbrowser.open(URL);return
    root=Path(__file__).resolve().parent
    logs=app_paths.data_root()/'logs';logs.mkdir(parents=True,exist_ok=True)
    with (logs/'launcher.log').open('ab') as output:
        flags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0
        process=subprocess.Popen([sys.executable,str(root/'forge.py'),'serve'],cwd=root,stdin=subprocess.DEVNULL,stdout=output,stderr=output,creationflags=flags,close_fds=True)
    for _ in range(40):
        if health(): webbrowser.open(URL);return
        if process.poll() is not None: break
        time.sleep(.25)
    raise SystemExit('Local server did not start. Check Documents/Forge_Player/logs/launcher.log. Another app or older Forge may occupy port 8766.')

if __name__=='__main__': main()
