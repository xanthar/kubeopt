Add a new feature to the harness.

If arguments are provided, use them. Otherwise, ask me:
1. What is the feature name?
2. What priority (1=highest, 5=lowest)? Default: 3
3. What are the subtasks? (comma-separated or one per line)
4. Any initial notes?

Then run:
```bash
claude-harness feature add "<feature_name>" -p <priority> \
  -s "<subtask1>" \
  -s "<subtask2>" \
  [-n "<notes>"]
```

Show the created feature ID and confirm success.

Arguments provided: $ARGUMENTS
