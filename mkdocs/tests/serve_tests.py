#!/usr/bin/env python

import io
import unittest
from unittest import mock

from mkdocs.commands import serve as serve_command
from mkdocs.tests.base import change_dir, tempdir


class _StdinStream(io.BytesIO):
    """
    A binary file object shaped like the one click passes for ``--config-file -``.

    ``sys.stdin.buffer`` reports its name as ``<stdin>`` and that is exactly what
    ``mkdocs serve -f -`` hands to :func:`mkdocs.commands.serve.serve`.
    """

    name = '<stdin>'


class ServeTests(unittest.TestCase):
    """Tests for reloading the config on rebuild in ``mkdocs serve`` (issue #4053)."""

    @tempdir(
        files={
            'mkdocs.yml': 'site_name: Test\n',
            'docs/index.md': '# Hello\n',
        }
    )
    def test_stdin_config_reloads_on_rebuild(self, tdir):
        # `mkdocs serve -f -` reads the config from stdin. The first load consumes
        # and closes that stream, so the rebuild triggered by a file change must
        # replay the buffered configuration instead of re-opening '<stdin>'.
        config_source = _StdinStream(b'site_name: Test\n')
        rebuild_errors = []

        with change_dir(tdir), mock.patch('mkdocs.commands.serve.LiveReloadServer') as mock_server:
            server = mock_server.return_value

            def rebuild(**kwargs):
                # Simulate the rebuild the livereload server performs when a
                # watched file changes, while the server is still running.
                try:
                    mock_server.call_args.kwargs['builder'](None)
                except Exception as error:  # - recorded for the assertion
                    rebuild_errors.append(error)
                    raise

            server.serve.side_effect = rebuild
            serve_command.serve(config_file=config_source, livereload=False)

        self.assertEqual(
            rebuild_errors,
            [],
            'rebuild with a config read from stdin failed: '
            + (repr(rebuild_errors[0]) if rebuild_errors else ''),
        )

    @tempdir(
        files={
            'mkdocs.yml': 'site_name: Test\n',
            'docs/index.md': '# Hello\n',
        }
    )
    def test_path_config_reloads_on_rebuild(self, tdir):
        # A config given as a path must keep reloading on rebuild as before.
        rebuild_errors = []

        with change_dir(tdir), mock.patch('mkdocs.commands.serve.LiveReloadServer') as mock_server:
            server = mock_server.return_value

            def rebuild(**kwargs):
                try:
                    mock_server.call_args.kwargs['builder'](None)
                except Exception as error:  # - recorded for the assertion
                    rebuild_errors.append(error)
                    raise

            server.serve.side_effect = rebuild
            serve_command.serve(config_file='mkdocs.yml', livereload=False)

        self.assertEqual(
            rebuild_errors,
            [],
            'rebuild with a config path failed: '
            + (repr(rebuild_errors[0]) if rebuild_errors else ''),
        )
