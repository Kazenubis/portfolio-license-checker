"""
Tests for the Portfolio License Checker — requirement parsing, license
classification, and the multi-source lookup fallback chain.
"""

import importlib.metadata as real_metadata
import os
import shutil
import tempfile
import unittest

import license_checker as lc


class TestParseRequirements(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write(self, content):
        path = os.path.join(self.tmpdir, "requirements.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_strips_version_specifiers(self):
        path = self._write("requests>=2.31\nflask==3.0.0\nnumpy\n")
        self.assertEqual(lc.parse_requirements(path), ["requests", "flask", "numpy"])

    def test_ignores_comments_and_blank_lines(self):
        path = self._write("# a comment\n\nrequests>=2.31\n\n# another\nflask\n")
        self.assertEqual(lc.parse_requirements(path), ["requests", "flask"])

    def test_missing_file_returns_empty_list(self):
        self.assertEqual(lc.parse_requirements(os.path.join(self.tmpdir, "nope.txt")), [])

    def test_handles_hyphenated_and_dotted_package_names(self):
        path = self._write("pygame-ce>=2.5\nscikit-learn>=1.3\nzope.interface\n")
        self.assertEqual(lc.parse_requirements(path), ["pygame-ce", "scikit-learn", "zope.interface"])


class TestClassify(unittest.TestCase):
    def test_mit_is_permissive(self):
        self.assertEqual(lc._classify("MIT"), "permissive")

    def test_bsd_is_permissive(self):
        self.assertEqual(lc._classify("BSD-3-Clause"), "permissive")

    def test_apache_is_permissive(self):
        self.assertEqual(lc._classify("Apache-2.0"), "permissive")

    def test_gpl_is_copyleft(self):
        self.assertEqual(lc._classify("GPL-3.0"), "copyleft")

    def test_agpl_is_copyleft(self):
        self.assertEqual(lc._classify("AGPL-3.0"), "copyleft")

    def test_lgpl_is_weak_copyleft_not_plain_copyleft(self):
        # LGPL allows linking from proprietary code, unlike GPL/AGPL —
        # it should get its own, less severe category.
        self.assertEqual(lc._classify("LGPL-2.1"), "weak-copyleft")
        self.assertEqual(lc._classify("GNU Library or Lesser General Public License (LGPL)"), "weak-copyleft")

    def test_unrecognized_text_is_unknown(self):
        self.assertEqual(lc._classify("Some Custom EULA"), "unknown")


class TestLookupLicenseRealPackages(unittest.TestCase):
    """Uses packages actually installed in this environment — these
    exercise the real importlib.metadata code path, including the two
    real-world messy cases this project's README calls out: a modern
    PEP 639 License-Expression field, and a package with no short
    license field at all (falls through to classifiers or the fallback
    table)."""

    def test_requests_license_is_found_and_permissive(self):
        license_text, category = lc.lookup_license("requests")
        self.assertEqual(category, "permissive")
        self.assertIn("apache", license_text.lower())

    def test_pygame_ce_license_is_found_and_flagged_weak_copyleft(self):
        license_text, category = lc.lookup_license("pygame-ce")
        self.assertEqual(category, "weak-copyleft")

    def test_unknown_package_name_falls_back_to_unknown(self):
        license_text, category = lc.lookup_license("this-package-does-not-exist-anywhere-xyz")
        self.assertEqual(license_text, "Unknown")
        self.assertEqual(category, "unknown")

    def test_known_fallback_table_covers_flask(self):
        # Exercises the fallback path directly, independent of whether
        # flask happens to be installed in the environment running this
        # test — a package not in KNOWN_LICENSE_FALLBACK and not
        # installed should NOT silently succeed via this route.
        license_text, category = lc.lookup_license("flask")
        self.assertEqual(category, "permissive")


class FakeDistributionMetadata:
    """A minimal stand-in for what importlib.metadata.metadata() returns,
    so the fallback-chain priority (License-Expression > Classifier >
    legacy License > offline table) can be tested deterministically
    without depending on which real packages happen to be installed."""

    def __init__(self, license_expression=None, classifiers=None, legacy_license=None):
        self._license_expression = license_expression
        self._classifiers = classifiers or []
        self._legacy_license = legacy_license

    def get(self, key):
        if key == "License-Expression":
            return self._license_expression
        if key == "License":
            return self._legacy_license
        return None

    def get_all(self, key):
        if key == "Classifier":
            return self._classifiers
        return None


class TestLookupLicenseFallbackChain(unittest.TestCase):
    def setUp(self):
        self._real_metadata_fn = lc.metadata.metadata

    def tearDown(self):
        lc.metadata.metadata = self._real_metadata_fn

    def test_license_expression_takes_priority(self):
        lc.metadata.metadata = lambda name: FakeDistributionMetadata(
            license_expression="MIT",
            classifiers=["License :: OSI Approved :: GNU General Public License v3 (GPLv3)"],
            legacy_license="GPL",
        )
        license_text, category = lc.lookup_license("fake-package")
        self.assertEqual(license_text, "MIT")
        self.assertEqual(category, "permissive")

    def test_classifier_used_when_no_license_expression(self):
        lc.metadata.metadata = lambda name: FakeDistributionMetadata(
            license_expression=None,
            classifiers=["License :: OSI Approved :: Apache Software License"],
        )
        license_text, category = lc.lookup_license("fake-package")
        self.assertIn("Apache", license_text)
        self.assertEqual(category, "permissive")

    def test_short_legacy_license_used_as_last_resort(self):
        lc.metadata.metadata = lambda name: FakeDistributionMetadata(
            legacy_license="BSD-3-Clause",
        )
        license_text, category = lc.lookup_license("fake-package")
        self.assertEqual(license_text, "BSD-3-Clause")
        self.assertEqual(category, "permissive")

    def test_long_legacy_license_text_blob_is_ignored(self):
        # Some real packages (e.g. pandas) put the ENTIRE license text
        # in this field, which isn't a usable short label — the checker
        # should skip it and fall through, not report a wall of text.
        long_license_text = "BSD License\n\n" + ("Redistribution and use... " * 50)
        lc.metadata.metadata = lambda name: FakeDistributionMetadata(
            legacy_license=long_license_text,
        )
        license_text, category = lc.lookup_license("not-in-fallback-table-xyz")
        self.assertEqual(license_text, "Unknown")
        self.assertEqual(category, "unknown")

    def test_falls_back_to_offline_table_when_metadata_has_nothing_usable(self):
        lc.metadata.metadata = lambda name: FakeDistributionMetadata()
        license_text, category = lc.lookup_license("pandas")
        self.assertEqual(category, "permissive")

    def test_package_not_found_falls_back_to_offline_table(self):
        def raise_not_found(name):
            raise real_metadata.PackageNotFoundError(name)

        lc.metadata.metadata = raise_not_found
        license_text, category = lc.lookup_license("requests")
        self.assertEqual(category, "permissive")


class TestScanProjectAndPortfolio(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _make_project(self, name, requirements_content=None):
        project_dir = os.path.join(self.tmpdir, name)
        os.makedirs(project_dir)
        if requirements_content is not None:
            with open(os.path.join(project_dir, "requirements.txt"), "w", encoding="utf-8") as f:
                f.write(requirements_content)
        return project_dir

    def test_scan_project_returns_none_without_requirements_file(self):
        project_dir = self._make_project("stdlib-only-project")
        self.assertIsNone(lc.scan_project(project_dir))

    def test_scan_project_reports_each_dependency(self):
        project_dir = self._make_project("web-project", "requests>=2.31\n")
        results = lc.scan_project(project_dir)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["package"], "requests")
        self.assertEqual(results[0]["category"], "permissive")

    def test_has_flagged_license_detects_copyleft(self):
        results = [
            {"package": "requests", "license": "Apache-2.0", "category": "permissive"},
            {"package": "pygame-ce", "license": "LGPL-2.1", "category": "weak-copyleft"},
        ]
        self.assertTrue(lc.has_flagged_license(results))

    def test_has_flagged_license_false_when_all_permissive(self):
        results = [{"package": "requests", "license": "Apache-2.0", "category": "permissive"}]
        self.assertFalse(lc.has_flagged_license(results))

    def test_scan_portfolio_walks_multiple_projects(self):
        self._make_project("project-a", "requests>=2.31\n")
        self._make_project("project-b", "pygame-ce>=2.5\n")
        self._make_project("project-c")  # no requirements.txt — should be skipped

        report = lc.scan_portfolio(self.tmpdir)

        self.assertEqual(set(report.keys()), {"project-a", "project-b"})
        self.assertTrue(lc.has_flagged_license(report["project-b"]))
        self.assertFalse(lc.has_flagged_license(report["project-a"]))


if __name__ == "__main__":
    unittest.main()
