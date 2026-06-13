# Third-Party Licenses

This project uses the following third-party Python packages.  
Each package retains its own license.  
Links to the project homepages or PyPI entries are provided for full license texts.

---

## Runtime Dependencies

### PySide6 (LGPL-3.0-only)
- **pyside6** — https://pypi.org/project/PySide6/
- **pyside6-addons** — https://pypi.org/project/PySide6-Addons/
- **pyside6-essentials** — https://pypi.org/project/PySide6-Essentials/
- **shiboken6** — https://pypi.org/project/shiboken6/

These packages are the official Qt for Python bindings provided by The Qt Company.
They are licensed under the **GNU Lesser General Public License v3.0 (LGPL-3.0-only)**.

### Panda3D (BSD-3-Clause)
- **panda3d** — https://pypi.org/project/panda3d/

---

## Development / Testing Dependencies

### pytest (MIT)
- **pytest** — https://pypi.org/project/pytest/

### pytest-cov (MIT)
- **pytest-cov** — https://pypi.org/project/pytest-cov/

### pytest-qt (MIT)
- **pytest-qt** — https://pypi.org/project/pytest-qt/

### coverage (Apache-2.0)
- **coverage** — https://pypi.org/project/coverage/

### flake8 (MIT)
- **flake8** — https://pypi.org/project/flake8/

### autopep8 (MIT)
- **autopep8** — https://pypi.org/project/autopep8/

---

## Indirect / Transitive Dependencies

The following packages are installed automatically as dependencies of the above packages.
They are not imported directly by this project's source code.

| Package | License | Pulled in by |
|---|---|---|
| colorama | BSD-3-Clause | pytest |
| iniconfig | MIT | pytest |
| mccabe | MIT | flake8 |
| packaging | Apache-2.0 | pytest |
| pluggy | MIT | pytest |
| pycodestyle | MIT | flake8, autopep8 |
| pyflakes | MIT | flake8 |
| pygments | BSD-2-Clause | pytest |
| typing-extensions | PSF-2.0 | pytest-qt |

---

## Notes

- Numerical computation uses the Python standard library only (numpy / scipy are not used).
- License texts are not reproduced here; refer to each package's homepage for the full license.
- No modifications have been made to any third-party packages.
