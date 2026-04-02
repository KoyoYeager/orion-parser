"""Download Python files from popular GitHub repos for testing."""
import urllib.request
import json
import os
import sys

# 50+ popular Python repos — pick key files from each
REPOS = [
    # Web frameworks
    ("django/django", "django/core/management/__init__.py"),
    ("django/django", "django/utils/functional.py"),
    ("django/django", "django/db/models/query.py"),
    ("pallets/click", "src/click/core.py"),
    ("pallets/click", "src/click/decorators.py"),
    ("pallets/jinja", "src/jinja2/environment.py"),
    ("pallets/jinja", "src/jinja2/compiler.py"),
    ("fastapi/fastapi", "fastapi/applications.py"),
    ("fastapi/fastapi", "fastapi/routing.py"),
    ("encode/starlette", "starlette/applications.py"),
    ("encode/starlette", "starlette/routing.py"),
    ("tornadoweb/tornado", "tornado/web.py"),
    ("tornadoweb/tornado", "tornado/ioloop.py"),
    # Data/ML
    ("pandas-dev/pandas", "pandas/core/frame.py"),
    ("pandas-dev/pandas", "pandas/core/series.py"),
    ("numpy/numpy", "numpy/core/numeric.py"),
    ("scikit-learn/scikit-learn", "sklearn/base.py"),
    ("scikit-learn/scikit-learn", "sklearn/utils/validation.py"),
    ("pytorch/pytorch", "torch/nn/modules/module.py"),
    ("pytorch/pytorch", "torch/optim/optimizer.py"),
    # Tools
    ("psf/requests", "src/requests/api.py"),
    ("psf/requests", "src/requests/sessions.py"),
    ("psf/requests", "src/requests/models.py"),
    ("urllib3/urllib3", "src/urllib3/connectionpool.py"),
    ("aio-libs/aiohttp", "aiohttp/web_app.py"),
    ("aio-libs/aiohttp", "aiohttp/client.py"),
    ("python-poetry/poetry", "src/poetry/console/application.py"),
    ("pypa/pip", "src/pip/_internal/commands/install.py"),
    ("pypa/pip", "src/pip/_internal/cli/main_parser.py"),
    # Testing
    ("pytest-dev/pytest", "src/_pytest/config/__init__.py"),
    ("pytest-dev/pytest", "src/_pytest/fixtures.py"),
    ("pytest-dev/pytest", "src/_pytest/python.py"),
    # DevOps/Infra
    ("ansible/ansible", "lib/ansible/executor/task_executor.py"),
    ("ansible/ansible", "lib/ansible/plugins/action/__init__.py"),
    ("saltstack/salt", "salt/client/__init__.py"),
    # CLI/Utility
    ("pallets/werkzeug", "src/werkzeug/serving.py"),
    ("pallets/werkzeug", "src/werkzeug/routing/map.py"),
    ("httpie/cli", "httpie/cli/definition.py"),
    ("tqdm/tqdm", "tqdm/std.py"),
    ("willmcgugan/rich", "rich/console.py"),
    ("willmcgugan/rich", "rich/table.py"),
    ("Textualize/textual", "src/textual/app.py"),
    ("Textualize/textual", "src/textual/widget.py"),
    # Async
    ("MagicStack/uvloop", "uvloop/loop.pyx"),  # skip .pyx
    ("python-trio/trio", "src/trio/_core/_run.py"),
    ("agronholm/anyio", "src/anyio/_backends/_asyncio.py"),
    # Type checking
    ("python/mypy", "mypy/checker.py"),
    ("python/mypy", "mypy/build.py"),
    ("microsoft/pyright", "packages/pyright-internal/typestubs/docutils/parsers/__init__.pyi"),
    # Data validation
    ("pydantic/pydantic", "pydantic/main.py"),
    ("pydantic/pydantic", "pydantic/fields.py"),
    ("marshmallow-code/marshmallow", "src/marshmallow/schema.py"),
    # Database
    ("sqlalchemy/sqlalchemy", "lib/sqlalchemy/orm/session.py"),
    ("sqlalchemy/sqlalchemy", "lib/sqlalchemy/engine/base.py"),
    # Misc popular
    ("ytdl-org/youtube-dl", "youtube_dl/extractor/common.py"),
    ("scrapy/scrapy", "scrapy/spiders/__init__.py"),
    ("celery/celery", "celery/app/base.py"),
    ("boto/boto3", "boto3/session.py"),
]

os.makedirs("files", exist_ok=True)
downloaded = 0
skipped = 0

for repo, path in REPOS:
    if path.endswith((".pyx", ".pyi")):
        skipped += 1
        continue
    fname = f"{repo.replace('/', '_')}_{path.replace('/', '_')}"
    outpath = os.path.join("files", fname)
    if os.path.exists(outpath):
        downloaded += 1
        continue
    url = f"https://raw.githubusercontent.com/{repo}/HEAD/{path}"
    try:
        urllib.request.urlretrieve(url, outpath)
        downloaded += 1
        print(f"OK  {repo}/{path}")
    except Exception as e:
        print(f"ERR {repo}/{path}: {e}")

print(f"\nDownloaded: {downloaded}, Skipped: {skipped}")
