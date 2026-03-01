# TODO/FIXME Tracking Context

When you encounter TODO or FIXME markers in the codebase:
- **TODO**: Planned feature or improvement — implement if in scope, else leave with a note
- **FIXME**: Known bug or broken code — always address these before new features
- **HACK**: Temporary workaround — flag for refactoring when addressing technical debt
- **NOTE**: Documentation comment — preserve unless the described behavior has changed

## Workflow
1. When asked to resolve TODOs, first `search_in_files` for all markers
2. Prioritize FIXME over TODO (bugs before features)
3. Group related TODOs and resolve them together
4. After resolving, remove the marker comment entirely
