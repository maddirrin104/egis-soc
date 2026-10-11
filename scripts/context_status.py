#!/usr/bin/env python3
"""Check persistent context; optionally archive an explicitly written handoff.

No repo files are edited by --check. --snapshot adds an archival Markdown file
and never changes HEAD, branches, or the working tree beyond that new file.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    'AGENTS.md', 'docs/EGIS_SOC_Ke_hoach_8_tuan.md',
    'docs/context/INDEX.md', 'docs/context/PROJECT_BRIEF.md',
    'docs/context/CURRENT_STATE.md', 'docs/context/HANDOFF.md',
    'docs/context/TASK_BOARD.md', 'docs/context/AGENT_POLICY.md',
]

def git(*args):
    p = subprocess.run(['git', '-C', str(ROOT), *args], text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return p.stdout.strip() if p.returncode == 0 else f'UNAVAILABLE ({p.stderr.strip()})'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check expected context files (default)')
    parser.add_argument('--snapshot', action='store_true', help='Archive the current verified HANDOFF.md verbatim')
    a = parser.parse_args()
    print('Workspace:', ROOT)
    missing = [p for p in FILES if not (ROOT / p).is_file()]
    print('Context:', 'OK' if not missing else f'MISSING: {missing}')
    print('Branch:', git('branch', '--show-current'))
    print('HEAD:', git('rev-parse', 'HEAD'))
    print('Git status:', git('status', '--short') or '(clean)')
    if a.snapshot:
        if missing:
            print('Cannot snapshot incomplete context.', file=sys.stderr)
            return 2
        handoff = (ROOT / 'docs/context/HANDOFF.md').read_text(encoding='utf-8')
        if 'NOT VERIFIED' in handoff or 'NOT SET' in handoff:
            print('Handoff still has unverified placeholders; no snapshot written.', file=sys.stderr)
            return 2
        dest = ROOT / 'docs/context/handoffs'
        dest.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        out = dest / f'handoff-{stamp}.md'
        out.write_text(handoff, encoding='utf-8')
        print('Saved:', out)
    return 1 if missing else 0

if __name__ == '__main__':
    raise SystemExit(main())
