"""Download multiple .py files from 60+ popular GitHub repos."""
import urllib.request
import os

REPOS = {
    "django/django": ["django/core/management/__init__.py","django/utils/functional.py","django/db/models/query.py","django/db/models/fields/__init__.py","django/http/request.py","django/template/base.py","django/forms/fields.py","django/views/generic/base.py"],
    "pallets/flask": ["src/flask/app.py","src/flask/blueprints.py","src/flask/config.py","src/flask/ctx.py","src/flask/helpers.py","src/flask/sessions.py"],
    "fastapi/fastapi": ["fastapi/applications.py","fastapi/routing.py","fastapi/params.py","fastapi/dependencies/utils.py","fastapi/security/oauth2.py"],
    "encode/starlette": ["starlette/applications.py","starlette/routing.py","starlette/requests.py","starlette/responses.py","starlette/websockets.py"],
    "tornadoweb/tornado": ["tornado/web.py","tornado/ioloop.py","tornado/httputil.py","tornado/gen.py","tornado/template.py"],
    "aio-libs/aiohttp": ["aiohttp/web_app.py","aiohttp/client.py","aiohttp/web_request.py","aiohttp/web_response.py","aiohttp/connector.py"],
    "sanic-org/sanic": ["sanic/app.py","sanic/request.py","sanic/response.py","sanic/router.py"],
    "pandas-dev/pandas": ["pandas/core/frame.py","pandas/core/series.py","pandas/core/groupby/groupby.py","pandas/io/parsers/readers.py","pandas/core/indexes/base.py"],
    "numpy/numpy": ["numpy/core/numeric.py","numpy/core/fromnumeric.py","numpy/lib/function_base.py","numpy/ma/core.py"],
    "scikit-learn/scikit-learn": ["sklearn/base.py","sklearn/utils/validation.py","sklearn/model_selection/_split.py","sklearn/pipeline.py","sklearn/tree/_classes.py"],
    "pytorch/pytorch": ["torch/nn/modules/module.py","torch/optim/optimizer.py","torch/autograd/__init__.py","torch/utils/data/dataloader.py"],
    "huggingface/transformers": ["src/transformers/modeling_utils.py","src/transformers/configuration_utils.py","src/transformers/tokenization_utils_base.py","src/transformers/trainer.py"],
    "keras-team/keras": ["keras/src/layers/layer.py","keras/src/models/model.py","keras/src/optimizers/optimizer.py"],
    "psf/requests": ["src/requests/api.py","src/requests/sessions.py","src/requests/models.py","src/requests/adapters.py","src/requests/auth.py"],
    "urllib3/urllib3": ["src/urllib3/connectionpool.py","src/urllib3/response.py","src/urllib3/_collections.py"],
    "httpie/cli": ["httpie/cli/definition.py","httpie/output/formatters/colors.py"],
    "encode/httpx": ["httpx/_client.py","httpx/_models.py","httpx/_transports/default.py"],
    "pallets/click": ["src/click/core.py","src/click/decorators.py","src/click/types.py"],
    "tqdm/tqdm": ["tqdm/std.py","tqdm/auto.py"],
    "willmcgugan/rich": ["rich/console.py","rich/table.py","rich/text.py","rich/panel.py","rich/progress.py"],
    "Textualize/textual": ["src/textual/app.py","src/textual/widget.py","src/textual/screen.py"],
    "python-poetry/poetry": ["src/poetry/console/application.py","src/poetry/packages/locker.py","src/poetry/installation/installer.py"],
    "pytest-dev/pytest": ["src/_pytest/config/__init__.py","src/_pytest/fixtures.py","src/_pytest/python.py","src/_pytest/runner.py","src/_pytest/assertion/rewrite.py"],
    "HypothesisWorks/hypothesis": ["hypothesis-python/src/hypothesis/core.py"],
    "ansible/ansible": ["lib/ansible/executor/task_executor.py","lib/ansible/plugins/action/__init__.py","lib/ansible/parsing/yaml/dumper.py"],
    "saltstack/salt": ["salt/client/__init__.py","salt/modules/cmdmod.py"],
    "docker/docker-py": ["docker/api/client.py","docker/models/containers.py"],
    "sqlalchemy/sqlalchemy": ["lib/sqlalchemy/orm/session.py","lib/sqlalchemy/engine/base.py","lib/sqlalchemy/sql/elements.py","lib/sqlalchemy/orm/query.py"],
    "tortoise/tortoise-orm": ["tortoise/models.py","tortoise/queryset.py"],
    "python-trio/trio": ["src/trio/_core/_run.py","src/trio/_highlevel_generic.py"],
    "agronholm/anyio": ["src/anyio/_backends/_asyncio.py"],
    "python/mypy": ["mypy/checker.py","mypy/build.py","mypy/semanal.py","mypy/types.py"],
    "astral-sh/ruff": ["scripts/check_docs_formatted.py"],
    "pydantic/pydantic": ["pydantic/main.py","pydantic/fields.py"],
    "marshmallow-code/marshmallow": ["src/marshmallow/schema.py","src/marshmallow/fields.py"],
    "pallets/jinja": ["src/jinja2/environment.py","src/jinja2/compiler.py","src/jinja2/lexer.py"],
    "pallets/werkzeug": ["src/werkzeug/serving.py","src/werkzeug/routing/map.py"],
    "celery/celery": ["celery/app/base.py"],
    "rq/rq": ["rq/worker.py","rq/job.py"],
    "scrapy/scrapy": ["scrapy/spiders/__init__.py","scrapy/http/request/__init__.py","scrapy/core/engine.py"],
    "psf/black": ["src/black/__init__.py","src/black/linegen.py","src/black/parsing.py"],
    "boto/boto3": ["boto3/session.py","boto3/resources/base.py"],
    "ytdl-org/youtube-dl": ["youtube_dl/extractor/common.py","youtube_dl/utils.py"],
    "Rapptz/discord.py": ["discord/client.py","discord/message.py","discord/guild.py"],
    "pyca/cryptography": ["src/cryptography/x509/base.py"],
    "python-attrs/attrs": ["src/attr/_make.py","src/attr/validators.py"],
    "omry/omegaconf": ["omegaconf/OmegaConf.py","omegaconf/basecontainer.py"],
    "home-assistant/core": ["homeassistant/core.py","homeassistant/config.py"],
    "apache/airflow": ["airflow/models/dag.py","airflow/operators/python.py"],
    "tiangolo/typer": ["typer/main.py","typer/core.py"],
    "python-pillow/Pillow": ["src/PIL/Image.py","src/PIL/ImageDraw.py"],
    "sympy/sympy": ["sympy/core/basic.py","sympy/core/expr.py"],
    "networkx/networkx": ["networkx/classes/graph.py","networkx/algorithms/shortest_paths/generic.py"],
    "matplotlib/matplotlib": ["lib/matplotlib/pyplot.py"],
    "sphinx-doc/sphinx": ["sphinx/application.py","sphinx/builders/__init__.py"],
    "paramiko/paramiko": ["paramiko/transport.py","paramiko/channel.py"],
    "fabric/fabric": ["fabric/connection.py","fabric/runners.py"],
    "ray-project/ray": ["python/ray/actor.py","python/ray/remote_function.py"],
    "dask/dask": ["dask/dataframe/core.py","dask/base.py"],
    "python/cpython": ["Lib/pathlib/__init__.py","Lib/typing.py","Lib/collections/__init__.py"],
}

os.makedirs("files", exist_ok=True)
downloaded = 0
failed = 0

for repo, paths in REPOS.items():
    for path in paths:
        fname = f"{repo.replace('/', '__')}_{os.path.basename(path)}"
        outpath = os.path.join("files", fname)
        if os.path.exists(outpath):
            downloaded += 1
            continue
        for branch in ["HEAD", "main", "master"]:
            url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
            try:
                urllib.request.urlretrieve(url, outpath)
                downloaded += 1
                break
            except Exception:
                continue
        else:
            failed += 1
            print(f"ERR {repo}/{path}")

print(f"\nRepos: {len(REPOS)}")
print(f"Downloaded: {downloaded}, Failed: {failed}")
