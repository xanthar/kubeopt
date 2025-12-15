Add a custom delegation rule.

Ask me:
1. Rule name?
2. Task patterns (comma-separated regex patterns)?
3. Subagent type (explore, test, document, review, general)?
4. Priority (1-10, higher = more important)?

Run:
```bash
claude-harness delegation add-rule \
  -n "<name>" \
  -p "<pattern1>,<pattern2>" \
  -t <type> \
  --priority <priority>
```
