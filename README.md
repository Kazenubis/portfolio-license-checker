# Portfolio License Checker

A meta-tool that scans `requirements.txt` across a whole portfolio of
repos and reports the license of every dependency — built to check my
own 68+ project folders at once, since manually opening each one's
requirements file and looking up its license would be tedious and easy
to get wrong.

Real output, running it against this batch's own 9 projects that have
a `requirements.txt`:

```
59-portfolio-activity-dashboard:
  requests        Apache Software License [permissive]
  matplotlib      Python Software Foundation License [permissive]

60-changelog-generator:
  GitPython       BSD-3-Clause         [permissive]

61-heroes-vs-villains-connect-four:
  pygame-ce       GNU Library or Lesser General Public License (LGPL) [weak-copyleft] <-- REVIEW

62-cairo-weather-dashboard:
  flask           BSD-3-Clause         [permissive]
  requests        Apache Software License [permissive]

63-titanic-survival-exploration:
  pandas          BSD License          [permissive]
  scikit-learn    BSD-3-Clause         [permissive]
  matplotlib      Python Software Foundation License [permissive]

64-uptime-checker:
  requests        Apache Software License [permissive]

65-hash-table-from-scratch:
  (no dependencies listed)

66-supplier-holiday-calendar:
  requests        Apache Software License [permissive]

67-portfolio-license-checker:
  (no dependencies listed)

=== Summary ===
Scanned 9 projects with dependencies.
Projects with a copyleft/weak-copyleft dependency worth reviewing: 61-heroes-vs-villains-connect-four
```

That's a genuinely correct flag: `pygame-ce` is LGPL-licensed, which is
weaker than a plain permissive license (MIT/BSD/Apache) even though it's
still fine to depend on for an application (as opposed to distributing
modified library source) — the point of the tool is to surface that
distinction automatically rather than relying on remembering which of
68 requirements.txt files might have one.

## Features

- Parses any `requirements.txt`, stripping version specifiers, extras,
  and comments down to bare package names
- Looks up each package's license through a layered fallback chain:
  the modern `License-Expression` metadata field (PEP 639, a short SPDX
  identifier) first, then OSI `Classifier` entries, then the legacy
  `License` field (only when it's actually short — some packages dump
  their *entire* license text into that field), then a small built-in
  table for common packages that aren't installed in the scanning
  environment
- Classifies each result as permissive, copyleft, weak-copyleft
  (LGPL — allows linking from proprietary code, unlike GPL/AGPL), or
  unknown, and flags anything other than permissive
- `--project` scans one folder; `--portfolio` walks every immediate
  subdirectory and prints a cross-project summary

## Tech Stack

Python 3, standard library only (`importlib.metadata`)

## Getting Started

```bash
git clone https://github.com/Kazenubis/portfolio-license-checker.git
cd portfolio-license-checker
python3 license_checker.py --project /path/to/one/project
python3 license_checker.py --portfolio /path/to/100-github-projects
```

Run the tests:

```bash
python3 -m unittest test_license_checker.py -v
```

## What I Learned

Real package metadata is a lot messier than I expected before actually
inspecting it. Checking a handful of installed packages directly with
`importlib.metadata` turned up three different shapes for the same
piece of information: `requests` has a normal short `License` field
("Apache-2.0"); `pandas` puts its *entire* multi-thousand-character
license text into that same field, which would be useless to print as
a "license" in a report; and modern packages like `flask` and
`scikit-learn` don't populate the legacy `License` field at all — they
use the newer PEP 639 `License-Expression` field instead, which
`importlib.metadata` also exposes but under a different key entirely.

A checker that only reads one of those sources will silently miss or
mis-report a real chunk of packages. The layered fallback (prefer the
short SPDX expression, fall through to classifiers, then a short legacy
field, then a small manual table) came directly out of testing this
against packages this portfolio actually depends on rather than
assuming any single metadata field would be reliable.
