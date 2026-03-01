# Code Quality Conventions

## Function & Method Design
- Keep functions under 30 lines — extract when they grow larger
- Single responsibility: one function does one thing
- Prefer return-early (guard clauses) over deeply nested if-else
- Name functions with verbs: `calculate_total()`, not `total()`

## Naming
- Variables: descriptive nouns (`user_count`, not `n`)
- Booleans: prefix with `is_`, `has_`, `can_` (`is_valid`, `has_permission`)
- Constants: UPPER_SNAKE_CASE
- Avoid abbreviations unless universally understood (`i`, `e`, `ctx` are OK)

## Code Cleanliness
- Delete dead code — don't comment it out
- No magic numbers — extract to named constants
- Avoid deep nesting (> 3 levels is a smell)
- Prefer explicit over implicit

## Refactoring Approach
1. Understand the current behavior completely before changing anything
2. Add tests for the current behavior if none exist
3. Make the smallest change that improves readability
4. Run tests after every meaningful change
