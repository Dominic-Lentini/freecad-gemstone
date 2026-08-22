# SPDX-License-Identifier: LGPL-2.1-or-later
"""Release-metadata checks: the things that must agree before tagging.

Pure file and XML checks — no FreeCAD, no Qt. ``version.py`` says "keep in
sync with <version> in package.xml", which is exactly the kind of instruction
that rots silently; these tests make the drift a test failure instead of a bad
release.
"""

import os
import re
import xml.etree.ElementTree as ElementTree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NS = {"p": "https://wiki.freecad.org/Package_Metadata"}


def _package_xml():
    return ElementTree.parse(os.path.join(ROOT, "package.xml")).getroot()


def _version_py():
    from freecad.lapidary.version import __version__
    return __version__


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as stream:
        return stream.read()


class TestVersion:
    def test_version_py_matches_package_xml(self):
        assert _package_xml().find("p:version", NS).text == _version_py()

    def test_version_is_semver(self):
        assert re.fullmatch(r"\d+\.\d+\.\d+", _version_py()), _version_py()

    def test_changelog_documents_this_version(self):
        changelog = _read("CHANGELOG.md")
        assert "## [%s]" % _version_py() in changelog
        # The Unreleased section stays, so there is somewhere to write next.
        assert "## [Unreleased]" in changelog


class TestPackageMetadata:
    def test_required_fields(self):
        root = _package_xml()
        for field in ("name", "description", "version", "date", "license"):
            element = root.find("p:" + field, NS)
            assert element is not None and element.text.strip(), field
        assert root.find("p:name", NS).text == "Lapidary"

    def test_declares_a_maintainer_with_an_email(self):
        maintainer = _package_xml().find("p:maintainer", NS)
        assert maintainer is not None
        assert "@" in (maintainer.get("email") or "")

    def test_repository_and_bugtracker_urls(self):
        types = {url.get("type")
                 for url in _package_xml().findall("p:url", NS)}
        assert {"repository", "bugtracker", "readme"} <= types

    def test_repository_url_declares_the_branch_it_lives_on(self):
        """branch= is required for type="repository", and the addon-index
        review checks it names the branch actually shipping this file."""
        repository, = [url for url in _package_xml().findall("p:url", NS)
                       if url.get("type") == "repository"]
        assert repository.get("branch") == "main"

    def test_readme_url_is_a_raw_markdown_link(self):
        """The Addon Manager renders this URL's body as Markdown; a
        /blob/ link serves GitHub's HTML page instead."""
        readme, = [url for url in _package_xml().findall("p:url", NS)
                   if url.get("type") == "readme"]
        assert "/raw/" in readme.text, readme.text
        assert readme.text.endswith(".md"), readme.text

    def test_icon_path_resolves(self):
        icon = _package_xml().find("p:icon", NS).text
        assert os.path.isfile(os.path.join(ROOT, icon)), icon

    def test_workbench_content_block(self):
        workbench = _package_xml().find(
            "p:content/p:workbench", NS)
        assert workbench is not None
        assert workbench.find("p:classname", NS).text == "LapidaryWorkbench"
        # The GUI is written against PySide6, first shipped in FreeCAD 1.1.
        # <freecadmin> is a MAJOR.MINOR.BUILD semver string per the
        # manifest spec, and must also appear at package level: that is
        # the copy the Addon Manager filters installs on.
        assert workbench.find("p:freecadmin", NS).text == "1.1.0"
        assert _package_xml().find("p:freecadmin", NS).text == "1.1.0"
        tags = {tag.text for tag in workbench.findall("p:tag", NS)}
        assert {"faceting", "gemstone", "lapidary"} <= tags


class TestDocs:
    def test_readme_links_resolve(self):
        """Every relative link in the README points at a file that exists.
        The repository deliberately ships only deployment-relevant docs
        (README, CHANGELOG, LICENSE); development documentation lives in
        the git history."""
        readme = _read("README.md")
        for target in re.findall(r"\]\((?!https?:|#)([^)\s]+)\)", readme):
            assert os.path.exists(os.path.join(ROOT, target)), target

    def test_no_dev_doc_stragglers(self):
        """The dev-only documentation set must not silently return.

        Checked against the git index, not the working tree: what the
        Addon Manager deploys is the repository content, and on a network
        share a deleted file can linger as an unreadable delete-pending
        ghost while another process holds a handle."""
        import subprocess
        try:
            tracked = subprocess.run(
                ["git", "ls-files"], cwd=ROOT, capture_output=True,
                text=True, check=True).stdout.splitlines()
        except (OSError, subprocess.CalledProcessError):
            import pytest
            pytest.skip("git unavailable; tracked-file check impossible")
        # (docs/screenshots.md returned deliberately: it is the capture
        # guide for the README's screenshots, a shipping-docs concern.)
        for name in ("CLAUDE.md", "CLAUDE_CODE_PROMPTS.md", "DESIGN.md",
                     "DESIGN_OPTICS.md", "docs/dev-notes.md",
                     "CONTRIBUTING.md"):
            assert name not in tracked, name
