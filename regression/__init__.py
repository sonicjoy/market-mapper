"""Engine-independent regression harness — see README.md.

Must not import from mappers/: engines are invoked as subprocesses in
SHA-pinned worktrees so the harness works against any commit.
"""
