# Security

## Supported versions

Security fixes are applied to the latest published 0.x release.

## Reporting

Report a vulnerability privately to the CLIFF maintainers. Do not open a public issue before a fix is available.

## Untrusted input

CLIFF documents, converted resources and file names are untrusted input.

- The parser enforces documented resource limits for lines, line length and decoded string length.
- CLIFF strings, ICU payloads and extension values are never evaluated.
- The package does not resolve `dependency` or `reference` paths. Callers that load dependencies must resolve them inside an explicit project root and reject paths that escape it.
- UI code must escape document text before inserting it into HTML.
- Converters preserve context through documented metadata channels; an importer does not invent missing context.
- The YAML converter depends on PyYAML. Treat YAML input as untrusted and keep PyYAML current.

## File I/O

`load` reads the path it is given. The library does not write files unless a caller or CLI explicitly requests output. Do not pass paths derived from untrusted input without validating them against a project root.
