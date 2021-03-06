# coding=utf-8
"""
Tests PulpExporter and PulpExport functionality

NOTE: assumes ALLOWED_EXPORT_PATHS setting contains "/tmp" - all tests will fail if this is not
the case.
"""
import unittest

from pulp_smash import api, cli, config
from pulp_smash.utils import uuid4
from pulp_smash.pulp3.utils import (
    delete_orphans,
    gen_repo,
)

from pulp_file.tests.functional.utils import (
    gen_file_client,
    gen_file_remote,
    monitor_task,
)

from pulpcore.client.pulpcore import (
    ApiClient as CoreApiClient,
    ExportersPulpApi,
    ExportersCoreExportsApi,
)

from pulpcore.client.pulpcore.exceptions import (
    ApiException,
)

from pulpcore.client.pulp_file import (
    RepositoriesFileApi,
    RepositorySyncURL,
    RemotesFileApi,
)

NUM_REPOS = 3
MAX_EXPORTS = 3
NUM_EXPORTERS = 4


class BaseExporterCase(unittest.TestCase):
    """
    Base functionality for Exporter and Export test classes

    The export process isn't possible without repositories having been sync'd - arranging for
    that to happen once per-class (instead of once-per-test) is the primary purpose of this parent
    class.
    """
    @classmethod
    def _setup_repositories(cls):
        """Create and sync a number of repositories to be exported."""
        # create and remember a set of repo
        repos = []
        remotes = []
        for r in range(NUM_REPOS):
            a_repo = cls.repo_api.create(gen_repo())
            # give it a remote and sync it
            body = gen_file_remote()
            remote = cls.remote_api.create(body)
            repository_sync_data = RepositorySyncURL(remote=remote.pulp_href)
            sync_response = cls.repo_api.sync(a_repo.pulp_href, repository_sync_data)
            monitor_task(sync_response.task)
            # remember it
            repos.append(a_repo)
            remotes.append(remote)
        return repos, remotes

    @classmethod
    def setUpClass(cls):
        """Create class-wide variables."""
        cls.cfg = config.get_config()
        cls.client = api.Client(cls.cfg, api.json_handler)
        cls.core_client = CoreApiClient(configuration=cls.cfg.get_bindings_config())
        cls.file_client = gen_file_client()

        cls.repo_api = RepositoriesFileApi(cls.file_client)
        cls.remote_api = RemotesFileApi(cls.file_client)
        cls.exporter_api = ExportersPulpApi(cls.core_client)
        cls.exports_api = ExportersCoreExportsApi(cls.core_client)

        (cls.repos, cls.remotes) = cls._setup_repositories()

    @classmethod
    def tearDownClass(cls):
        """Clean up after ourselves."""
        for remote in cls.remotes:
            cls.remote_api.delete(remote.pulp_href)
        for repo in cls.repos:
            cls.repo_api.delete(repo.pulp_href)
        delete_orphans(cls.cfg)

    def _delete_exporter(self, exporter):
        """
        Utility routine to delete an exporter.

        Sets last_exporter to null to make it possible. Also removes the export-directory
        and all its contents.
        """
        cli_client = cli.Client(self.cfg)
        cmd = ('rm', '-rf', exporter.path)
        cli_client.run(cmd, sudo=True)

        # NOTE: you have to manually undo 'last-export' if you really really REALLY want to
        #  delete an Exporter. This is...probably correct?
        body = {
            "last_export": None
        }
        self.exporter_api.partial_update(exporter.pulp_href, body)
        self.exporter_api.delete(exporter.pulp_href)

    def _create_exporter(self, cleanup=True):
        """Utility routine to create an exporter for the available repositories."""
        body = {
            "name": uuid4(),
            "repositories": [r.pulp_href for r in self.repos],
            "path": "/tmp/{}".format(uuid4())
        }
        exporter = self.exporter_api.create(body)
        if cleanup:
            self.addCleanup(self._delete_exporter, exporter)
        return exporter, body


class PulpExporterTestCase(BaseExporterCase):
    """Test PulpExporter CURDL methods."""
    def test_create(self):
        """Create a PulpExporter."""
        (exporter, body) = self._create_exporter()
        self.assertIsNone(exporter.last_export)
        self.assertEqual(body["name"], exporter.name)
        self.assertEqual(body["path"], exporter.path)
        self.assertEqual(len(self.repos), len(exporter.repositories))

    def test_read(self):
        """Read a created PulpExporter."""
        (exporter_created, body) = self._create_exporter()
        exporter_read = self.exporter_api.read(exporter_created.pulp_href)
        self.assertEqual(exporter_created.name, exporter_read.name)
        self.assertEqual(exporter_created.path, exporter_read.path)
        self.assertEqual(len(exporter_created.repositories), len(exporter_read.repositories))

    def test_partial_update(self):
        """Update a PulpExporter's path."""
        (exporter_created, body) = self._create_exporter()
        body = {
            "path": "/tmp/{}".format(uuid4())
        }
        self.exporter_api.partial_update(exporter_created.pulp_href, body)
        exporter_read = self.exporter_api.read(exporter_created.pulp_href)
        self.assertNotEqual(exporter_created.path, exporter_read.path)
        self.assertEqual(body["path"], exporter_read.path)

    def test_list(self):
        """Show a set of created PulpExporters."""
        for x in range(NUM_EXPORTERS):
            self._create_exporter()

        exporters = self.exporter_api.list().results
        self.assertEqual(NUM_EXPORTERS, len(exporters))

    def test_delete(self):
        """Delete a pulpExporter."""
        (exporter_created, body) = self._create_exporter(False)
        self._delete_exporter(exporter_created)
        try:
            self.exporter_api.read(exporter_created.pulp_href)
        except ApiException as ae:
            self.assertEqual(404, ae.status)
            return
        self.fail("Found a deleted exporter!")


class PulpExportTestCase(BaseExporterCase):
    """Test PulpExport CRDL methods (Update is not allowed)."""

    def _gen_export(self, exporter):
        """Create and read back an export for the specified PulpExporter."""
        # TODO: at this point we can't create an export unless we do string-surgery on the
        #  exporter-href because there's no way to get just-the-id
        export_response = self.exports_api.create(exporter.pulp_href.split("/")[-2], {})
        monitor_task(export_response.task)
        task = self.client.get(export_response.task)
        resources = task["created_resources"]
        self.assertEqual(1, len(resources))
        export_href = resources[0]
        export = self.exports_api.read(export_href)
        self.assertIsNotNone(export)
        return export

    def test_export(self):
        """Issue and evaluate a PulpExport (tests both Create and Read)."""
        (exporter, body) = self._create_exporter(cleanup=False)
        try:
            export = self._gen_export(exporter)
            self.assertIsNotNone(export)
            self.assertEqual(len(exporter.repositories), len(export.exported_resources))
            self.assertIsNotNone(export.filename)
            self.assertIsNotNone(export.sha256)
        finally:
            self._delete_exporter(exporter)

    def test_list(self):
        """Find all the PulpExports for a PulpExporter."""
        (exporter, body) = self._create_exporter(cleanup=False)
        try:
            export = None
            for i in range(MAX_EXPORTS):
                export = self._gen_export(exporter)
            exporter = self.exporter_api.read(exporter.pulp_href)
            self.assertEqual(exporter.last_export, export.pulp_href)
            exports = self.exports_api.list(exporter.pulp_href.split("/")[-2]).results
            self.assertEqual(MAX_EXPORTS, len(exports))
        finally:
            self._delete_exporter(exporter)

    def _delete_export(self, export):
        """
        Delete a PulpExport and test that it is gone.

        :param export: PulpExport to be deleted
        :return: true if specified export is gone, false if we can still find it
        """
        self.exports_api.delete(export.pulp_href)
        try:
            self.exports_api.read(export.pulp_href)
        except ApiException as ae:
            self.assertEqual(404, ae.status)
            return True
        return False

    def test_delete(self):
        """
        Test deleting exports for a PulpExporter.

        NOTE: Attempting to delete the current last_export is forbidden.
        """
        (exporter, body) = self._create_exporter(cleanup=False)
        try:
            # Do three exports
            first_export = self._gen_export(exporter)
            self._gen_export(exporter)
            last_export = self._gen_export(exporter)

            # delete one make sure it's gone
            if not self._delete_export(first_export):
                self.fail("Failed to delete an export")

            # make sure the exporter knows it's gone
            exporter = self.exporter_api.read(exporter.pulp_href)
            exports = self.exports_api.list(exporter.pulp_href.split("/")[-2]).results
            self.assertEqual(2, len(exports))

            # Now try to delete the last_export export and fail
            with self.assertRaises(ApiException) as ae:
                self._delete_export(last_export)
            self.assertEqual(ae.exception.status, 500)
        finally:
            self._delete_exporter(exporter)

    @unittest.skip("not yet implemented")
    def test_export_output(self):
        """Create an export and evaluate the resulting export-file."""
        self.fail("test_export_file")
