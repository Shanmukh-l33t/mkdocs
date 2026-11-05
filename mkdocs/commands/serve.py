from __future__ import annotations

import io
import logging
import shutil
import sys
import tempfile
from os.path import isdir, isfile, join
from typing import TYPE_CHECKING, Callable
from urllib.parse import urlsplit

from mkdocs.commands.build import build
from mkdocs.config import load_config
from mkdocs.livereload import LiveReloadServer, _serve_url

if TYPE_CHECKING:
    from typing import IO

    from mkdocs.config.defaults import MkDocsConfig

log = logging.getLogger(__name__)


def _replayable_config_file(
    config_file: str | IO[bytes] | None,
) -> Callable[[], str | IO[bytes] | None]:
    """
    Return a callable producing the config source each (re)load should read.

    A config read from stdin (``mkdocs serve -f -``) can only be consumed once, and
    the first load closes the stream. Rebuilds must therefore replay the buffered
    bytes instead of re-opening ``'<stdin>'``, which raised
    ``ConfigurationError: Config file '<stdin>' does not exist`` (issue #4053).
    Any other source is returned unchanged so path-based configs keep their
    existing reopen-by-name behavior.
    """
    is_stdin = (
        config_file is sys.stdin
        or config_file is getattr(sys.stdin, 'buffer', None)
        or (not isinstance(config_file, str) and getattr(config_file, 'name', None) == '<stdin>')
    )
    if not is_stdin:
        return lambda: config_file

    data = config_file.read()  # type: ignore[union-attr]
    if isinstance(data, str):
        data = data.encode('utf-8')
    return lambda: io.BytesIO(data)


def serve(
    config_file: str | IO[bytes] | None = None,
    livereload: bool = True,
    build_type: str | None = None,
    watch_theme: bool = False,
    watch: list[str] = [],
    *,
    open_in_browser: bool = False,
    **kwargs,
) -> None:
    """
    Start the MkDocs development server.

    By default it will serve the documentation on http://localhost:8000/ and
    it will rebuild the documentation and refresh the page automatically
    whenever a file is edited.
    """
    # Create a temporary build directory, and set some options to serve it
    site_dir = tempfile.mkdtemp(prefix='mkdocs_')

    # Buffer a stdin-provided config once so every rebuild can replay it.
    next_config_file = _replayable_config_file(config_file)

    def get_config():
        config = load_config(
            config_file=next_config_file(),
            site_dir=site_dir,
            **kwargs,
        )
        config.watch.extend(watch)
        return config

    is_clean = build_type == 'clean'
    is_dirty = build_type == 'dirty'

    config = get_config()
    config.plugins.on_startup(command=('build' if is_clean else 'serve'), dirty=is_dirty)

    host, port = config.dev_addr
    mount_path = urlsplit(config.site_url or '/').path
    config.site_url = serve_url = _serve_url(host, port, mount_path)

    def builder(config: MkDocsConfig | None = None):
        log.info("Building documentation...")
        if config is None:
            config = get_config()
            config.site_url = serve_url

        build(config, serve_url=None if is_clean else serve_url, dirty=is_dirty)

    server = LiveReloadServer(
        builder=builder, host=host, port=port, root=site_dir, mount_path=mount_path
    )

    def error_handler(code) -> bytes | None:
        if code in (404, 500):
            error_page = join(site_dir, f'{code}.html')
            if isfile(error_page):
                with open(error_page, 'rb') as f:
                    return f.read()
        return None

    server.error_handler = error_handler

    try:
        # Perform the initial build
        builder(config)

        if livereload:
            # Watch the documentation files, the config file and the theme files.
            server.watch(config.docs_dir)
            if config.config_file_path:
                server.watch(config.config_file_path)

            if watch_theme:
                for d in config.theme.dirs:
                    server.watch(d)

            # Run `serve` plugin events.
            server = config.plugins.on_serve(server, config=config, builder=builder)

            for item in config.watch:
                server.watch(item)

        try:
            server.serve(open_in_browser=open_in_browser)
        except KeyboardInterrupt:
            log.info("Shutting down...")
        finally:
            server.shutdown()
    finally:
        config.plugins.on_shutdown()
        if isdir(site_dir):
            shutil.rmtree(site_dir)
