"""Private browser-test server. Always uses a temporary database."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.main import create_app

if __name__ == '__main__':
    with TemporaryDirectory(prefix='svod-ui-') as folder:
        app=create_app('sqlite:///'+(Path(folder)/'test.sqlite3').as_posix(),production=False)
        try:
            uvicorn.run(app,host='127.0.0.1',port=8791,log_level='warning',access_log=False)
        finally:
            app.state.engine.dispose()
