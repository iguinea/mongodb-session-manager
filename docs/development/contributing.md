# Contributing to MongoDB Session Manager

Thank you for your interest in contributing to MongoDB Session Manager! This document provides guidelines and instructions for contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Code Style and Formatting](#code-style-and-formatting)
- [Commit Message Conventions](#commit-message-conventions)
- [Pull Request Process](#pull-request-process)
- [Review Process](#review-process)
- [What to Contribute](#what-to-contribute)
- [Documentation](#documentation)
- [Testing Requirements](#testing-requirements)
- [License](#license)

## Code of Conduct

### Our Pledge

We pledge to make participation in our project a harassment-free experience for everyone, regardless of age, body size, disability, ethnicity, gender identity and expression, level of experience, nationality, personal appearance, race, religion, or sexual identity and orientation.

### Our Standards

**Positive behavior includes:**
- Using welcoming and inclusive language
- Being respectful of differing viewpoints and experiences
- Gracefully accepting constructive criticism
- Focusing on what is best for the community
- Showing empathy towards other community members

**Unacceptable behavior includes:**
- Trolling, insulting/derogatory comments, and personal or political attacks
- Public or private harassment
- Publishing others' private information without permission
- Other conduct which could reasonably be considered inappropriate

### Enforcement

Instances of abusive, harassing, or otherwise unacceptable behavior may be reported by contacting the project maintainer at iguinea@gmail.com. All complaints will be reviewed and investigated promptly and fairly.

## Getting Started

### Prerequisites

Before you begin contributing, ensure you have:

1. **Development Environment Set Up**
   - See [setup.md](setup.md) for detailed instructions
   - Python 3.13+, UV, and MongoDB installed
   - Project dependencies installed with `uv sync`

2. **GitHub Account**
   - Create an account at [github.com](https://github.com)
   - Set up SSH keys for easier authentication

3. **Git Configuration**
   ```bash
   git config --global user.name "Your Name"
   git config --global user.email "your.email@example.com"
   ```

### Finding Something to Work On

1. **Browse Issues**: Look for issues labeled:
   - `good first issue`: Great for newcomers
   - `help wanted`: Issues where maintainers need help
   - `bug`: Bug fixes needed
   - `enhancement`: New features to implement

2. **Check the Roadmap**: See what's planned in the project roadmap

3. **Propose New Ideas**: Open an issue to discuss your idea before implementing

## Development Workflow

### 1. Fork the Repository

1. Go to https://github.com/iguinea/mongodb-session-manager
2. Click "Fork" button in the top right
3. Select your account as the destination

### 2. Clone Your Fork

```bash
git clone https://github.com/YOUR_USERNAME/mongodb-session-manager.git
cd mongodb-session-manager
```

### 3. Add Upstream Remote

```bash
git remote add upstream https://github.com/iguinea/mongodb-session-manager.git

# Verify remotes
git remote -v
# origin    https://github.com/YOUR_USERNAME/mongodb-session-manager.git (fetch)
# origin    https://github.com/YOUR_USERNAME/mongodb-session-manager.git (push)
# upstream  https://github.com/iguinea/mongodb-session-manager.git (fetch)
# upstream  https://github.com/iguinea/mongodb-session-manager.git (push)
```

### 4. Create a Feature Branch

```bash
# Update your main branch
git checkout main
git pull upstream main

# Create feature branch
git checkout -b feature/your-feature-name

# Or for bug fixes
git checkout -b fix/issue-description
```

**Branch Naming Conventions:**
- `feature/descriptive-name`: New features
- `fix/bug-description`: Bug fixes
- `docs/what-changed`: Documentation updates
- `refactor/what-changed`: Code refactoring
- `test/what-added`: Test additions

### 5. Make Your Changes

```bash
# Install dependencies
uv sync

# Make your changes
# ... edit files ...

# Run tests frequently
uv run pytest tests/

# Run linting
uv run ruff check .
uv run ruff format .
```

### 6. Commit Your Changes

```bash
# Stage your changes
git add .

# Or stage specific files
git add src/mongodb_session_manager/file.py

# Commit with descriptive message
git commit -m "Add feature X that does Y"
```

See [Commit Message Conventions](#commit-message-conventions) for details.

### 7. Keep Your Branch Updated

```bash
# Fetch latest changes from upstream
git fetch upstream

# Rebase your branch on upstream/main
git rebase upstream/main

# Or merge if you prefer
git merge upstream/main

# If there are conflicts, resolve them and continue
git add .
git rebase --continue
```

### 8. Push Your Changes

```bash
# Push to your fork
git push origin feature/your-feature-name

# If you rebased, you may need to force push
git push --force-with-lease origin feature/your-feature-name
```

### 9. Create a Pull Request

1. Go to your fork on GitHub
2. Click "Compare & pull request" button
3. Fill in the PR template (see below)
4. Click "Create pull request"

## Code Style and Formatting

We use **Ruff** for both linting and formatting. Ruff is a fast Python linter and formatter.

### Running Ruff

```bash
# Check for linting issues
uv run ruff check .

# Auto-fix linting issues
uv run ruff check --fix .

# Format code
uv run ruff format .

# Check formatting without making changes
uv run ruff format --check .
```

### Code Style Guidelines

1. **Follow PEP 8**: Python's style guide
   - Line length: 88 characters (Ruff default)
   - Use 4 spaces for indentation
   - Use snake_case for functions and variables
   - Use PascalCase for classes

2. **Type Hints**: Use type hints for function signatures
   ```python
   def create_session_manager(
       session_id: str,
       connection_string: Optional[str] = None,
       database_name: str = "database_name"
   ) -> MongoDBSessionManager:
       """Create a session manager."""
       pass
   ```

3. **Docstrings**: Use Google-style docstrings
   ```python
   def update_metadata(self, metadata: dict) -> None:
       """Update session metadata with partial updates.

       This method performs a partial update, preserving existing
       metadata fields that are not included in the update.

       Args:
           metadata: Dictionary of metadata fields to update

       Raises:
           ValueError: If metadata is not a dictionary

       Example:
           >>> manager.update_metadata({"priority": "high"})
       """
       pass
   ```

4. **Comments**: Write clear, concise comments
   ```python
   # Good: Explains why, not what
   # Use dot notation to preserve existing fields
   update_dict = {f"metadata.{k}": v for k, v in metadata.items()}

   # Bad: Obvious comment
   # Create a dictionary
   update_dict = {}
   ```

5. **Imports**: Organize imports in three groups
   ```python
   # Standard library
   import os
   from datetime import datetime
   from typing import Optional, Dict

   # Third-party
   from pymongo import MongoClient
   from strands import Agent

   # Local
   from .mongodb_connection_pool import MongoDBConnectionPool
   ```

6. **Error Handling**: Use specific exceptions
   ```python
   # Good
   if not isinstance(metadata, dict):
       raise ValueError("Metadata must be a dictionary")

   # Bad
   if not isinstance(metadata, dict):
       raise Exception("Invalid input")
   ```

### Pre-commit Checks

Before committing, always run:

```bash
# Format code
uv run ruff format .

# Check linting
uv run ruff check --fix .

# Run tests
uv run pytest tests/

# All in one command
uv run ruff format . && uv run ruff check --fix . && uv run pytest tests/
```

## Commit Message Conventions

We follow [Conventional Commits](https://www.conventionalcommits.org/) specification.

### Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, no logic change)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks (dependencies, build config)
- `perf`: Performance improvements

### Examples

**Simple commit:**
```
feat: add agent configuration persistence

Add methods to capture and store agent model and system_prompt
during sync_agent() operation.
```

**With scope:**
```
fix(repository): handle missing agent gracefully

Return None instead of raising exception when agent_id
is not found in session document.
```

**Breaking change:**
```
feat(hooks)!: redesign feedback SNS hook for multiple topics

BREAKING CHANGE: create_feedback_sns_hook() now requires three
topic ARNs (good, bad, neutral) instead of a single topic.

Migration guide:
- Old: create_feedback_sns_hook(topic_arn="...")
- New: create_feedback_sns_hook(
    topic_arn_good="...",
    topic_arn_bad="...",
    topic_arn_neutral="..."
  )
```

**With issue reference:**
```
fix: prevent connection pool exhaustion

Fixes #123
```

### Commit Message Guidelines

1. **Subject line:**
   - Use imperative mood ("add" not "added" or "adds")
   - Don't capitalize first letter
   - No period at the end
   - Keep under 50 characters

2. **Body (optional):**
   - Explain what and why, not how
   - Wrap at 72 characters
   - Separate from subject with blank line

3. **Footer (optional):**
   - Reference issues: `Fixes #123` or `Closes #456`
   - Note breaking changes: `BREAKING CHANGE: description`

## Pull Request Process

### PR Title

Use the same format as commit messages:

```
feat: add metadata field deletion support
fix: resolve connection pool leak in factory
docs: update FastAPI integration examples
```

### PR Description Template

```markdown
## Description
Brief description of what this PR does.

## Motivation and Context
Why is this change needed? What problem does it solve?

Fixes # (issue)

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to change)
- [ ] Documentation update
- [ ] Refactoring (no functional changes)

## How Has This Been Tested?
Describe the tests you ran and how to reproduce them.

- [ ] Test A
- [ ] Test B

## Checklist
- [ ] My code follows the code style of this project
- [ ] I have run `ruff format` and `ruff check`
- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] New and existing unit tests pass locally with my changes
- [ ] I have added necessary documentation (if appropriate)
- [ ] I have updated the CHANGELOG.md (if appropriate)
- [ ] My commit messages follow the commit message conventions

## Screenshots (if appropriate)

## Additional Notes
Any additional information that reviewers should know.
```

### Before Submitting

1. **Ensure CI passes:**
   - All tests pass
   - No linting errors
   - Code is formatted

2. **Update documentation:**
   - Update README.md if needed
   - Update CLAUDE.md if needed
   - Add/update docstrings
   - Update relevant docs/ files

3. **Update CHANGELOG.md:**
   - Add entry under "Unreleased" section
   - Follow existing format
   - Include breaking changes if any

4. **Rebase on main:**
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

5. **Self-review:**
   - Review your own changes on GitHub
   - Check for typos, debug code, commented code
   - Ensure all files are necessary

## Review Process

### What Reviewers Look For

1. **Functionality:**
   - Does the code do what it's supposed to do?
   - Are there any edge cases not handled?
   - Is error handling appropriate?

2. **Code Quality:**
   - Is the code readable and maintainable?
   - Are there any code smells?
   - Is it following project conventions?

3. **Tests:**
   - Are there sufficient tests?
   - Do tests cover edge cases?
   - Are tests clear and maintainable?

4. **Documentation:**
   - Are new features documented?
   - Are docstrings clear and complete?
   - Is the CHANGELOG updated?

5. **Performance:**
   - Are there any performance concerns?
   - Is the implementation efficient?

### Responding to Feedback

1. **Be receptive:** Reviews help improve code quality
2. **Ask questions:** If feedback is unclear, ask for clarification
3. **Make changes:** Address all feedback or explain why you disagree
4. **Request re-review:** After making changes, request another review

### Making Changes After Review

```bash
# Make the requested changes
# ... edit files ...

# Commit changes
git add .
git commit -m "address review feedback"

# Push to your branch
git push origin feature/your-feature-name
```

The PR will automatically update with your new commits.

### Approval and Merging

- PRs require at least 1 approval from a maintainer
- All CI checks must pass
- Maintainers will merge approved PRs
- The merge commit will reference the PR number

## What to Contribute

### Bug Fixes

Found a bug? Great! Here's how to fix it:

1. **Search for existing issues** to avoid duplicates
2. **Create an issue** describing the bug if none exists
3. **Follow the workflow** to create a fix
4. **Add tests** that verify the fix
5. **Submit a PR** referencing the issue

Example:
```bash
git checkout -b fix/connection-pool-leak
# ... make fixes ...
git commit -m "fix: prevent connection pool exhaustion in factory

Ensure MongoDB client is properly closed when factory is
closed, preventing connection leaks in long-running applications.

Fixes #123"
```

### New Features

Want to add a feature? Follow these steps:

1. **Open an issue** to discuss the feature first
2. **Wait for approval** from maintainers
3. **Create a plan** in `features/<n>_<short_description>/plan.md`
4. **Implement the feature** following the plan
5. **Add comprehensive tests**
6. **Update documentation**
7. **Submit a PR**

Example feature structure:
```
features/
  2_metadata_caching/
    plan.md           # Feature plan and design
    implementation.md # Implementation notes (optional)
```

### Documentation

Documentation improvements are always welcome:

1. **Fix typos and grammar**
2. **Improve clarity** of existing docs
3. **Add examples** to illustrate usage
4. **Write tutorials** for common use cases
5. **Translate documentation** (if multilingual support exists)

Documentation files:
- `README.md`: User-facing documentation
- `CLAUDE.md`: Developer guidance for Claude Code
- `docs/`: Comprehensive documentation
- Docstrings: Inline code documentation

### Examples

More examples help users understand the library:

1. **Add new example scripts** in `examples/`
2. **Demonstrate specific use cases**
3. **Show best practices**
4. **Include comments** explaining the code

Example naming:
- `example_feature_name.py`: Demonstrates a specific feature
- `example_integration_framework.py`: Shows framework integration

### Tests

Help improve test coverage:

1. **Add unit tests** for untested code
2. **Add integration tests** for real-world scenarios
3. **Improve existing tests** for clarity
4. **Add performance tests** for critical paths

See [testing.md](testing.md) for testing guidelines.

### Performance Improvements

Optimize the library:

1. **Identify bottlenecks** with profiling
2. **Propose optimization** in an issue
3. **Implement optimization** with benchmarks
4. **Add performance tests** to prevent regression

## Documentation

### When to Update Documentation

Update documentation when you:
- Add a new feature
- Change existing behavior
- Fix a significant bug
- Add new examples
- Change the API

### Documentation Files to Update

1. **README.md**: User-facing documentation
   - Update feature list
   - Add new examples
   - Update API reference

2. **CLAUDE.md**: Developer guidance
   - Update architecture notes
   - Add new patterns
   - Update package exports

3. **CHANGELOG.md**: Version history
   - Add entry under "Unreleased"
   - Follow existing format
   - Note breaking changes

4. **docs/** files: Comprehensive documentation
   - Update relevant guide pages
   - Add new sections if needed
   - Keep examples up to date

5. **Docstrings**: Inline documentation
   - Update affected functions/classes
   - Include examples
   - Document parameters and return values

## Testing Requirements

All code contributions must include tests:

### Minimum Requirements

1. **Unit tests** for new functions/methods
2. **Integration tests** for new features
3. **Tests must pass** locally before submitting PR
4. **Coverage** should not decrease

### Running Tests

```bash
# Run all tests
uv run pytest tests/

# Run specific test file
uv run pytest tests/test_session_manager.py

# Run with coverage
uv run pytest --cov=mongodb_session_manager tests/

# Run with verbose output
uv run pytest -v tests/
```

See [testing.md](testing.md) for detailed testing guidelines.

## License

By contributing to MongoDB Session Manager, you agree that your contributions will be licensed under the same license as the project.

## Questions?

- **Documentation issues?** Open an issue with the `docs` label
- **Need help?** Ask in GitHub Discussions
- **Found a bug?** Open an issue with the `bug` label
- **Have an idea?** Open an issue with the `enhancement` label

## Thank You!

Thank you for contributing to MongoDB Session Manager! Your efforts help make this project better for everyone.

---

**Remember:** The best contribution is one that helps other developers. Write code you'd be happy to maintain, and documentation you'd want to read.

Happy contributing!
