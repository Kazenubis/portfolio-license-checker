"""
Portfolio License Checker — scans every requirements.txt across a
portfolio of repos (built to check Mahmoud's own 60+ project folders,
but works on any directory tree), looks up each dependency's license via
`importlib.metadata`, and flags copyleft licenses that would be worth a
second look before reuse in a project meant to stay MIT-licensed.

    python3 license_checker.py --project /path/to/one/project
    python3 license_checker.py --portfolio /path/to/100-github-projects
"""

import argparse
import importlib.metadata as metadata
import os
import re

REQUIREMENT_LINE_PATTERN = re.compile(r"^([A-Za-z0-9._-]+)")

# SPDX-ish identifiers, classified by category. Checked case-insensitively
# against whatever short license string we manage to extract.
PERMISSIVE_MARKERS = ["mit", "bsd", "apache", "isc", "psf", "python software foundation",
                      "zlib", "0bsd", "cc0", "unlicense", "wtfpl"]
COPYLEFT_MARKERS = ["gpl", "agpl", "mpl", "eupl", "osl"]
# LGPL specifically is "weak copyleft" — it allows linking from
# proprietary code (unlike GPL/AGPL), but still deserves its own flag
# since it's stricter than a permissive license.
WEAK_COPYLEFT_MARKERS = ["lgpl", "lesser general public"]

# Used only when a package genuinely isn't installed in the environment
# doing the scan (so `importlib.metadata` has nothing to look up) — a
# small, manually-curated fallback for common packages that show up
# across this portfolio's own requirements.txt files. Anything not
# covered here (and not installed) reports as "Unknown".
KNOWN_LICENSE_FALLBACK = {
    "flask": ("BSD-3-Clause", "permissive"),
    "requests": ("Apache-2.0", "permissive"),
    "pandas": ("BSD-3-Clause", "permissive"),
    "numpy": ("BSD-3-Clause", "permissive"),
    "matplotlib": ("PSF-based", "permissive"),
    "scikit-learn": ("BSD-3-Clause", "permissive"),
    "pygame-ce": ("LGPL-2.1", "weak-copyleft"),
    "gitpython": ("BSD-3-Clause", "permissive"),
    "pillow": ("HPND", "permissive"),
    "pyyaml": ("MIT", "permissive"),
    "jinja2": ("BSD-3-Clause", "permissive"),
    "click": ("BSD-3-Clause", "permissive"),
    "beautifulsoup4": ("MIT", "permissive"),
    "pytest": ("MIT", "permissive"),
}


def parse_requirements(path):
    """Extracts bare package names from a requirements.txt, stripping
    version specifiers, extras, comments, and blank lines."""
    if not os.path.exists(path):
        return []

    packages = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = REQUIREMENT_LINE_PATTERN.match(line)
            if match:
                packages.append(match.group(1))
    return packages


def _classify(license_text):
    lowered = license_text.lower()
    if any(marker in lowered for marker in WEAK_COPYLEFT_MARKERS):
        return "weak-copyleft"
    if any(marker in lowered for marker in COPYLEFT_MARKERS):
        return "copyleft"
    if any(marker in lowered for marker in PERMISSIVE_MARKERS):
        return "permissive"
    return "unknown"


def lookup_license(package_name):
    """Returns (license_text, category) for a package name. Tries, in
    order: the modern PEP 639 `License-Expression` metadata field (a
    short SPDX identifier — the most reliable source when present), then
    OSI classifier entries, then the legacy free-text `License` field
    (only if it's short — some packages dump the *entire* license text
    in there, which isn't useful as a short label), then a small offline
    fallback table, then "Unknown"."""
    try:
        meta = metadata.metadata(package_name)
    except metadata.PackageNotFoundError:
        meta = None

    if meta is not None:
        license_expression = meta.get("License-Expression")
        if license_expression:
            return license_expression, _classify(license_expression)

        classifiers = meta.get_all("Classifier") or []
        license_classifiers = [c for c in classifiers if c.startswith("License ::")]
        if license_classifiers:
            label = license_classifiers[0].split("::")[-1].strip()
            return label, _classify(label)

        legacy_license = meta.get("License")
        if legacy_license and len(legacy_license) <= 100:
            return legacy_license, _classify(legacy_license)

    fallback = KNOWN_LICENSE_FALLBACK.get(package_name.lower())
    if fallback:
        return fallback

    return "Unknown", "unknown"


def scan_project(project_dir):
    """Reports on <project_dir>/requirements.txt. Returns None if the
    project has no requirements.txt at all (e.g. a stdlib-only project)
    rather than reporting an empty scan."""
    requirements_path = os.path.join(project_dir, "requirements.txt")
    if not os.path.exists(requirements_path):
        return None

    packages = parse_requirements(requirements_path)
    results = []
    for package in packages:
        license_text, category = lookup_license(package)
        results.append({
            "package": package,
            "license": license_text,
            "category": category,
        })
    return results


def scan_portfolio(root_dir):
    """Walks every immediate subdirectory of `root_dir` that has a
    requirements.txt and reports on each."""
    report = {}
    for entry in sorted(os.listdir(root_dir)):
        project_dir = os.path.join(root_dir, entry)
        if not os.path.isdir(project_dir):
            continue
        result = scan_project(project_dir)
        if result is not None:
            report[entry] = result
    return report


def has_flagged_license(results):
    return any(r["category"] in ("copyleft", "weak-copyleft") for r in results)


def format_project_report(project_name, results):
    lines = [f"{project_name}:"]
    if not results:
        lines.append("  (no dependencies listed)")
    for r in results:
        flag = " <-- REVIEW" if r["category"] in ("copyleft", "weak-copyleft") else ""
        lines.append(f"  {r['package']:<15} {r['license']:<20} [{r['category']}]{flag}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Portfolio License Checker")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--project", help="Path to a single project directory")
    group.add_argument("--portfolio", help="Path to a directory containing multiple project folders")
    args = parser.parse_args()

    if args.project:
        results = scan_project(args.project)
        if results is None:
            print(f"No requirements.txt found in {args.project}")
            return
        print(format_project_report(os.path.basename(os.path.normpath(args.project)), results))
        return

    report = scan_portfolio(args.portfolio)
    flagged_projects = []
    for project_name, results in report.items():
        print(format_project_report(project_name, results))
        print()
        if has_flagged_license(results):
            flagged_projects.append(project_name)

    print("=== Summary ===")
    print(f"Scanned {len(report)} projects with dependencies.")
    if flagged_projects:
        print(f"Projects with a copyleft/weak-copyleft dependency worth reviewing: {', '.join(flagged_projects)}")
    else:
        print("No copyleft dependencies found.")


if __name__ == "__main__":
    main()
