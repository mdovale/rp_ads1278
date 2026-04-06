# Commit Message

## Objective

Check the git repo and provide a vim-ready commit message in a plaintext code block, using Conventional Commits style.

## Steps

1. Run `git status` and `git diff --staged` (or `git diff` if nothing staged) to inspect changes
2. Summarize the changes
3. Output a commit message in this format:

```
type(scope): brief description

- Change 1
- Change 2
- Change 3
```

## Output

A single plaintext code block containing the full commit message, ready to paste into vim or use with `git commit -F -`.
