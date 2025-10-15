# Release Process

This document describes the process for creating and publishing releases of the MongoDB Session Manager.

## Table of Contents

- [Version Numbering](#version-numbering)
- [Pre-Release Checklist](#pre-release-checklist)
- [Release Steps](#release-steps)
- [Version Update Locations](#version-update-locations)
- [Changelog Management](#changelog-management)
- [Git Tagging](#git-tagging)
- [Building the Package](#building-the-package)
- [Testing the Build](#testing-the-build)
- [Publishing to PyPI](#publishing-to-pypi)
- [GitHub Release](#github-release)
- [Post-Release Tasks](#post-release-tasks)
- [Hotfix Releases](#hotfix-releases)

## Version Numbering

This project follows [Semantic Versioning](https://semver.org/) (SemVer):

```
MAJOR.MINOR.PATCH
```

### Version Components

- **MAJOR** (X.0.0): Incompatible API changes (breaking changes)
- **MINOR** (0.X.0): New functionality in a backwards-compatible manner
- **PATCH** (0.0.X): Backwards-compatible bug fixes

### Examples

```
0.1.14 -> 0.1.15  # Bug fix
0.1.14 -> 0.2.0   # New feature
0.1.14 -> 1.0.0   # Breaking change
```

### Pre-Release Versions

For pre-releases, use these suffixes:

```
0.2.0-alpha.1    # Alpha release
0.2.0-beta.1     # Beta release
0.2.0-rc.1       # Release candidate
```

### Determining Version Bump

**PATCH (0.0.X)** - Increment when:
- Fixing bugs
- Performance improvements
- Documentation updates
- Internal refactoring (no API changes)

**MINOR (0.X.0)** - Increment when:
- Adding new features
- Adding new methods to public API
- Deprecating functionality (but not removing)
- Significant internal changes that don't break API

**MAJOR (X.0.0)** - Increment when:
- Removing deprecated functionality
- Changing method signatures
- Changing behavior of existing methods
- Restructuring package imports

## Pre-Release Checklist

Before starting the release process, ensure:

### Code Quality

- [ ] All tests pass locally
  ```bash
  uv run pytest tests/
  ```

- [ ] Code is formatted and linted
  ```bash
  uv run ruff format .
  uv run ruff check .
  ```

- [ ] Test coverage is satisfactory
  ```bash
  uv run pytest --cov=mongodb_session_manager tests/
  ```

### Documentation

- [ ] README.md is up to date
- [ ] CLAUDE.md reflects current implementation
- [ ] API documentation in `docs/` is current
- [ ] All examples work correctly
- [ ] CHANGELOG.md has entries for all changes

### Functionality

- [ ] All features work as expected
- [ ] Example scripts run without errors
- [ ] Integration with Strands Agents works
- [ ] MongoDB operations are correct
- [ ] Connection pooling works properly

### Dependencies

- [ ] All dependencies are up to date
- [ ] No security vulnerabilities in dependencies
  ```bash
  uv pip list --outdated
  ```

- [ ] Lock file is up to date
  ```bash
  uv sync
  ```

## Release Steps

### Step 1: Update Version Numbers

The current version is **0.1.14**. When releasing a new version, you must update version numbers in three locations:

#### 1. Update `src/mongodb_session_manager/__init__.py`

```python
# src/mongodb_session_manager/__init__.py

# ... imports ...

__version__ = "0.1.15"  # Update this line
__author__ = "Iñaki Guinea Beristain"
__author_email__ = "iguinea@gmail.com"
```

#### 2. Update `pyproject.toml`

```toml
# pyproject.toml

[project]
name = "mongodb-session-manager"
version = "0.1.15"  # Update this line
description = "MongoDB session management for Strands Agents"
# ...
```

#### 3. Verify Updates

```bash
# Check version in __init__.py
uv run python -c "from mongodb_session_manager import __version__; print(__version__)"

# Check version in pyproject.toml
grep "^version" pyproject.toml
```

**CRITICAL**: All three locations must have the same version number!

### Step 2: Update CHANGELOG.md

Update the CHANGELOG to document all changes in this release.

#### Format

```markdown
## [0.1.15] - 2025-10-15

### Added
- New feature X that does Y
- New method `do_something()` in MongoDBSessionManager

### Changed
- Improved performance of connection pooling by 20%
- Updated metadata update to use bulk operations

### Fixed
- Fixed bug where sessions were not properly closed
- Resolved memory leak in factory pattern

### Deprecated
- Method `old_method()` is now deprecated, use `new_method()` instead

### Removed
- Removed deprecated method `very_old_method()`

### Security
- Updated dependency X to address CVE-YYYY-NNNN
```

#### Breaking Changes

If there are breaking changes, add a migration guide:

```markdown
## [1.0.0] - 2025-10-15

### Changed - BREAKING CHANGE ⚠️
- Renamed `update_metadata()` to `set_metadata()`
- Changed signature of `create_session_manager()` to require `session_id` as first parameter

### Migration Guide

**Before (v0.x):**
```python
manager = create_session_manager(
    connection_string="mongodb://...",
    session_id="test"
)
manager.update_metadata({"key": "value"})
```

**After (v1.0):**
```python
manager = create_session_manager(
    session_id="test",  # Now first parameter
    connection_string="mongodb://..."
)
manager.set_metadata({"key": "value"})  # Renamed method
```
```

#### Add Comparison Links

At the bottom of CHANGELOG.md, add comparison link:

```markdown
[0.1.15]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.14...v0.1.15
```

### Step 3: Commit Version Changes

```bash
# Stage version updates
git add src/mongodb_session_manager/__init__.py
git add pyproject.toml
git add CHANGELOG.md

# Commit with version bump message
git commit -m "chore: bump version to 0.1.15 for release

- Update version in __init__.py
- Update version in pyproject.toml
- Update CHANGELOG.md with release notes"

# Push to main branch
git push origin main
```

### Step 4: Create Git Tag

```bash
# Create annotated tag
git tag -a v0.1.15 -m "Release version 0.1.15

- Feature: Add agent configuration persistence
- Fix: Resolve connection pool leak
- Docs: Update FastAPI integration examples"

# Push tag to remote
git push origin v0.1.15
```

**Note**: Use annotated tags (`-a`) not lightweight tags. Annotated tags include tagger information and can have a message.

### Step 5: Build the Package

```bash
# Clean previous builds
rm -rf dist/ build/ *.egg-info

# Build package with UV
uv build

# Verify build artifacts
ls -lh dist/
# Should see:
# mongodb_session_manager-0.1.15.tar.gz
# mongodb_session_manager-0.1.15-py3-none-any.whl
```

#### Build Verification

```bash
# Check package contents
tar -tzf dist/mongodb_session_manager-0.1.15.tar.gz

# Should include:
# - src/mongodb_session_manager/
# - README.md
# - LICENSE
# - pyproject.toml
```

### Step 6: Test the Build

Before publishing, test the built package:

```bash
# Create test environment
python -m venv test-env
source test-env/bin/activate

# Install built package
pip install dist/mongodb_session_manager-0.1.15-py3-none-any.whl

# Test import
python -c "from mongodb_session_manager import __version__; print(__version__)"

# Test basic functionality
python -c "
from mongodb_session_manager import create_mongodb_session_manager
print('✓ Import successful')
"

# Deactivate and remove test environment
deactivate
rm -rf test-env
```

### Step 7: Publish to PyPI

**IMPORTANT**: This step will be done when the package is ready for public release.

Currently, the package is not published to PyPI. When ready:

#### Test PyPI (Recommended First)

```bash
# Install twine for uploading
uv add --dev twine

# Upload to Test PyPI
uv run twine upload --repository testpypi dist/*

# Test installation from Test PyPI
pip install --index-url https://test.pypi.org/simple/ mongodb-session-manager
```

#### Production PyPI

```bash
# Upload to PyPI
uv run twine upload dist/*

# Verify on PyPI
# Visit: https://pypi.org/project/mongodb-session-manager/
```

**Authentication**: You'll need PyPI credentials or API token. Configure in `~/.pypirc`:

```ini
[pypi]
username = __token__
password = pypi-...your-token...

[testpypi]
username = __token__
password = pypi-...your-token...
```

### Step 8: Create GitHub Release

1. Go to https://github.com/iguinea/mongodb-session-manager/releases
2. Click "Draft a new release"
3. Select the tag you created (v0.1.15)
4. Release title: `v0.1.15`
5. Description: Copy from CHANGELOG.md

Example release notes:

```markdown
# MongoDB Session Manager v0.1.15

## What's New

### Added
- Agent configuration persistence: Automatically capture and store agent model and system_prompt
- New methods: `get_agent_config()`, `update_agent_config()`, `list_agents()`
- Example: `examples/example_agent_config.py`

### Fixed
- Connection pool leak in factory pattern
- Index creation race condition

### Documentation
- Updated FastAPI integration guide
- Added agent configuration documentation

## Installation

```bash
pip install mongodb-session-manager==0.1.15
```

## Full Changelog

See [CHANGELOG.md](https://github.com/iguinea/mongodb-session-manager/blob/v0.1.15/CHANGELOG.md) for complete details.

## Upgrade Guide

This release is backwards compatible. No breaking changes.

To upgrade:
```bash
pip install --upgrade mongodb-session-manager
```
```

6. Attach build artifacts (optional):
   - Upload `dist/mongodb_session_manager-0.1.15.tar.gz`
   - Upload `dist/mongodb_session_manager-0.1.15-py3-none-any.whl`

7. Click "Publish release"

## Version Update Locations

**CRITICAL**: When releasing, update version in these THREE files:

1. **`src/mongodb_session_manager/__init__.py`**
   ```python
   __version__ = "0.1.15"
   ```

2. **`pyproject.toml`**
   ```toml
   version = "0.1.15"
   ```

3. **`CHANGELOG.md`** (add new section)
   ```markdown
   ## [0.1.15] - 2025-10-15
   ```

Use this command to verify all versions match:

```bash
# Check all version references
grep -r "0.1.14" src/mongodb_session_manager/__init__.py pyproject.toml CHANGELOG.md

# After update, verify new version
grep -r "0.1.15" src/mongodb_session_manager/__init__.py pyproject.toml CHANGELOG.md
```

## Changelog Management

### During Development

Maintain an "Unreleased" section in CHANGELOG.md:

```markdown
## [Unreleased]

### Added
- Feature in progress

### Changed
- Improvement being worked on
```

### At Release Time

1. Replace `[Unreleased]` with version and date: `## [0.1.15] - 2025-10-15`
2. Add new `[Unreleased]` section at top for next development cycle
3. Add comparison link at bottom

### Changelog Sections

Use these sections in order (omit empty sections):

- **Added**: New features
- **Changed**: Changes in existing functionality
- **Deprecated**: Soon-to-be removed features
- **Removed**: Removed features
- **Fixed**: Bug fixes
- **Security**: Security vulnerability fixes

## Git Tagging

### Creating Tags

```bash
# Annotated tag (RECOMMENDED)
git tag -a v0.1.15 -m "Release v0.1.15"

# Lightweight tag (not recommended)
git tag v0.1.15

# Tag with detailed message
git tag -a v0.1.15 -m "Release v0.1.15

Major changes:
- Agent configuration persistence
- Connection pool improvements
- Bug fixes and performance enhancements

See CHANGELOG.md for full details."
```

### Pushing Tags

```bash
# Push specific tag
git push origin v0.1.15

# Push all tags
git push origin --tags
```

### Managing Tags

```bash
# List all tags
git tag

# Show tag details
git show v0.1.15

# Delete local tag
git tag -d v0.1.15

# Delete remote tag
git push origin --delete v0.1.15
```

## Building the Package

### Build Process

UV uses Hatchling as the build backend (configured in `pyproject.toml`):

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mongodb_session_manager"]
```

### Build Commands

```bash
# Clean previous builds
rm -rf dist/ build/ *.egg-info

# Build both wheel and source distribution
uv build

# Build only wheel
uv build --wheel

# Build only source distribution
uv build --sdist
```

### Build Output

```
dist/
├── mongodb_session_manager-0.1.15-py3-none-any.whl    # Wheel (binary)
└── mongodb_session_manager-0.1.15.tar.gz              # Source distribution
```

## Testing the Build

### Local Installation Test

```bash
# Create clean test environment
python -m venv /tmp/test-install
source /tmp/test-install/bin/activate

# Install from wheel
pip install dist/mongodb_session_manager-0.1.15-py3-none-any.whl

# Run basic tests
python -c "
from mongodb_session_manager import (
    MongoDBSessionManager,
    __version__,
    create_mongodb_session_manager
)
print(f'Version: {__version__}')
assert __version__ == '0.1.15'
print('✓ Installation successful')
"

# Clean up
deactivate
rm -rf /tmp/test-install
```

### Package Content Verification

```bash
# Inspect wheel contents
unzip -l dist/mongodb_session_manager-0.1.15-py3-none-any.whl

# Inspect source distribution
tar -tzf dist/mongodb_session_manager-0.1.15.tar.gz

# Verify metadata
uv run python -m pip show mongodb-session-manager
```

## Publishing to PyPI

### Prerequisites

1. **PyPI Account**: Register at https://pypi.org/
2. **API Token**: Generate at https://pypi.org/manage/account/token/
3. **Twine**: Install with `uv add --dev twine`

### Configuration

Create `~/.pypirc`:

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-...your-production-token...

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-...your-test-token...
```

Protect the file:
```bash
chmod 600 ~/.pypirc
```

### Upload to Test PyPI

```bash
# Upload to Test PyPI
uv run twine upload --repository testpypi dist/*

# Test installation
pip install --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    mongodb-session-manager==0.1.15
```

### Upload to Production PyPI

```bash
# Final check
uv run twine check dist/*

# Upload to PyPI
uv run twine upload dist/*

# Verify on PyPI
# Visit: https://pypi.org/project/mongodb-session-manager/0.1.15/
```

## GitHub Release

### Release Notes Template

```markdown
# MongoDB Session Manager v0.1.15

## Highlights

Brief summary of major changes (2-3 sentences)

## What's New

### Added
- Feature 1 with brief description
- Feature 2 with brief description

### Changed
- Change 1
- Change 2

### Fixed
- Bug fix 1
- Bug fix 2

## Installation

```bash
pip install mongodb-session-manager==0.1.15
```

Or with UV:
```bash
uv add mongodb-session-manager==0.1.15
```

## Upgrade Instructions

This release is backwards compatible.

To upgrade:
```bash
pip install --upgrade mongodb-session-manager
```

## Breaking Changes

None in this release.

## Documentation

- [README](https://github.com/iguinea/mongodb-session-manager#readme)
- [API Documentation](https://github.com/iguinea/mongodb-session-manager/tree/main/docs)
- [Examples](https://github.com/iguinea/mongodb-session-manager/tree/main/examples)

## Full Changelog

**Full Changelog**: [v0.1.14...v0.1.15](https://github.com/iguinea/mongodb-session-manager/compare/v0.1.14...v0.1.15)

See [CHANGELOG.md](https://github.com/iguinea/mongodb-session-manager/blob/v0.1.15/CHANGELOG.md) for complete details.
```

## Post-Release Tasks

After publishing a release:

### 1. Update Documentation

- [ ] Verify documentation is current
- [ ] Update any version-specific documentation
- [ ] Check that examples work with new version

### 2. Announce Release

Announce the release on relevant channels:
- GitHub Discussions
- Project Slack/Discord
- Social media (if applicable)

### 3. Monitor for Issues

- [ ] Watch for bug reports
- [ ] Monitor PyPI download statistics
- [ ] Check for installation issues

### 4. Update Development Branch

```bash
# Pull latest
git pull origin main

# Start new development cycle
# Add [Unreleased] section to CHANGELOG.md
```

### 5. Close Milestone

If using GitHub Milestones:
- Close the milestone for this release
- Move any incomplete issues to next milestone

## Hotfix Releases

For urgent bug fixes that can't wait for the next regular release:

### Hotfix Process

1. **Create Hotfix Branch**
   ```bash
   git checkout -b hotfix/0.1.15-fix main
   ```

2. **Make Fix**
   - Fix the critical bug
   - Add tests
   - Update CHANGELOG.md

3. **Bump Patch Version**
   - 0.1.14 → 0.1.15
   - Update in all three locations

4. **Test Thoroughly**
   ```bash
   uv run pytest tests/
   ```

5. **Merge and Release**
   ```bash
   git checkout main
   git merge --no-ff hotfix/0.1.15-fix
   git tag -a v0.1.15 -m "Hotfix: Critical bug fix"
   git push origin main --tags
   ```

6. **Build and Publish**
   Follow normal release process

### Hotfix Changelog

```markdown
## [0.1.15] - 2025-10-15

### Fixed
- **CRITICAL**: Fixed connection pool exhaustion causing service outages
- Resolved memory leak in session manager factory

This is a hotfix release addressing critical issues found in v0.1.14.
All users are strongly encouraged to upgrade immediately.
```

## Release Checklist

Use this checklist for every release:

```markdown
## Release Checklist for v0.1.15

### Pre-Release
- [ ] All tests pass
- [ ] Code is formatted (ruff format)
- [ ] Code is linted (ruff check)
- [ ] Test coverage is adequate
- [ ] Documentation is up to date
- [ ] Examples work correctly
- [ ] Dependencies are current

### Version Updates
- [ ] Update src/mongodb_session_manager/__init__.py
- [ ] Update pyproject.toml
- [ ] Update CHANGELOG.md
- [ ] Verify all versions match

### Git Operations
- [ ] Commit version changes
- [ ] Push to main branch
- [ ] Create and push git tag

### Build and Test
- [ ] Build package with uv build
- [ ] Verify build artifacts
- [ ] Test installation from wheel
- [ ] Run basic functionality tests

### Publish (when ready)
- [ ] Upload to Test PyPI
- [ ] Test installation from Test PyPI
- [ ] Upload to Production PyPI
- [ ] Verify on PyPI

### GitHub
- [ ] Create GitHub Release
- [ ] Add release notes
- [ ] Attach build artifacts
- [ ] Publish release

### Post-Release
- [ ] Announce release
- [ ] Monitor for issues
- [ ] Close milestone
- [ ] Start new development cycle
```

## Troubleshooting

### Version Mismatch

**Problem**: Versions don't match across files

**Solution**:
```bash
# Check all files
grep -r "0.1.14" src/mongodb_session_manager/__init__.py pyproject.toml

# Update manually and verify
grep -r "0.1.15" src/mongodb_session_manager/__init__.py pyproject.toml
```

### Build Failures

**Problem**: `uv build` fails

**Solution**:
```bash
# Clean and rebuild
rm -rf dist/ build/ *.egg-info
uv sync
uv build
```

### PyPI Upload Failures

**Problem**: `twine upload` fails with authentication error

**Solution**:
- Verify API token is correct in `~/.pypirc`
- Check token has not expired
- Ensure token has upload permissions

### Tag Already Exists

**Problem**: Tag already exists on remote

**Solution**:
```bash
# Delete remote tag
git push origin --delete v0.1.15

# Delete local tag
git tag -d v0.1.15

# Recreate tag
git tag -a v0.1.15 -m "Release v0.1.15"
git push origin v0.1.15
```

## Additional Resources

- [Semantic Versioning](https://semver.org/)
- [Keep a Changelog](https://keepachangelog.com/)
- [Python Packaging Guide](https://packaging.python.org/)
- [Twine Documentation](https://twine.readthedocs.io/)
- [UV Documentation](https://github.com/astral-sh/uv)

## Questions?

If you have questions about the release process:
1. Check this document
2. Review previous releases for examples
3. Ask in GitHub Discussions
4. Contact maintainers

---

**Remember**: Every release should be stable, well-tested, and properly documented. When in doubt, test more!
