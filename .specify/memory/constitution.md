# MongoDB Session Manager Constitution

## Core Principles

### I. Single Responsibility (SRP)
Every module, class, and function SHALL have exactly one reason to change. A component that requires the conjunction "and" to describe its purpose MUST be decomposed into separate units.

### II. Open-Closed Architecture (OCP)
Software entities SHALL be open for extension but closed for modification. New behavior MUST be achievable by adding new code, not by changing existing code. Strategy patterns, plugin architectures, and dependency injection are the preferred extension mechanisms.

### III. Test-First Imperative (TDD)
No production code SHALL be written without a failing test that requires it. The development cycle MUST follow Red -> Green -> Refactor. Minimum coverage thresholds: 80% for business logic, 70% for handlers, 60% for data layer.

### IV. Domain-Driven Organization (DDD)
Code SHALL be organized by business domain, not by technical layer. Each bounded context MUST have its own models, even when representing the same real-world concept. The ubiquitous language of the domain MUST be reflected in code identifiers.

### V. Simplicity Gate (KISS)
Every abstraction, pattern, or indirection MUST justify its existence with a concrete, current use case. Premature abstraction is a defect. If a simple function suffices, a class hierarchy is forbidden.

### VI. YAGNI Constraint
No feature, parameter, or configuration option SHALL be implemented until there is a demonstrated, current requirement. Speculative generality is a defect. Three similar lines of code are preferred over a premature abstraction.

### VII. Dependency Inversion (DIP)
High-level modules SHALL NOT depend on low-level modules. Both MUST depend on abstractions. Concrete implementations MUST be injected, never instantiated directly by their consumers.

### VIII. Interface Segregation (ISP)
No client SHALL be forced to depend on methods it does not use. Large interfaces MUST be split into smaller, role-specific interfaces.

### IX. Liskov Compliance (LSP)
Subtypes MUST be substitutable for their base types without altering the correctness of the program.

## Technology Stack

- **Language**: Python 3.12+
- **Package Manager**: UV
- **Database**: MongoDB (pymongo)
- **Framework**: Strands Agents SDK
- **Linting/Formatting**: Ruff
- **Testing**: pytest (unit + integration)

## Quality Gates

- All tests pass (unit + integration)
- Ruff check and format clean
- Code review approved
- Documentation updated with code changes
- CHANGELOG.md updated for user-facing changes

## Governance

This constitution supersedes all other practices. Amendments require documentation, team discussion, and a clear migration plan for existing code.

**Version**: 1.0.0 | **Ratified**: 2026-03-20 | **Last Amended**: 2026-03-20
