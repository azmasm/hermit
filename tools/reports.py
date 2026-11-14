#!/usr/bin/env python3
"""Players' reports from the How it ran form (.github/ISSUE_TEMPLATE/how-it-ran.yml) as rows of a game's reports table (games/<game>/reports.tsv).

  tools/reports.py from-issue <number> [--apply]   read the issue (gh), check it, print what it gives as one JSON line; --apply adds the row

A row needs a game this repository has and a Mac it can read: a chip (M1 ... M9, with Pro / Max / Ultra) and its memory in GB. The build is the engine the
form names, or, when it names none, the one Hermit picks for that chip and memory; its version is the one the form gives,
else the commit the build pins today. Every field is plain text with tabs and line breaks removed, and capped: the form asks only about the Mac, and
the pull request the workflow opens lets a maintainer read the row before it goes in. A form edited later replaces its own row (the source names the issue).
The GitHub workflow .github/workflows/reports.yml runs it for every new or edited [How it ran] issue.
"""
import importlib.util, json, re, subprocess, sys, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_s = importlib.util.spec_from_file_location('s2m', ROOT / 'hermit.py'); S2M = importlib.util.module_from_spec(_s); _s.loader.exec_module(S2M)
BUILD_LABELS = {'pokopia': 'pokopia-native', 'nxnative': 'nxnative', 'azmasm': 'switch2mac', 'switch2mac': 'switch2mac'}   # words in the Build answer, the more particular first


def plain(s, n):   # one line of plain text, at most n characters
    s = re.sub(r'\s+', ' ', (s or '').replace('\t', ' ')).strip()
    return '' if s in ('_No response_', 'None') else s[:n]


def fold(s): return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower().strip()


def fields(body):   # an issue form's answers: "### Label" headings, each followed by its answer
    out, label = {}, None
    for line in (body or '').splitlines():
        if line.startswith('### '): label = line[4:].strip(); out[label] = ''
        elif label is not None: out[label] = (out[label] + '\n' + line).strip()
    return out


def which_build(g, label, version, commit):   # the game's build a report is about: its own id or name in the Build answer (kid-with-sword, mkw-neo, ...), then the
    # version's commit as a build pins it (the overlay's Engine line says "nxnative <commit>" for every build made on nxnative), then its project in the version
    # (kid-with-sword-remake), then the general words; None when nothing says
    bs = S2M.builds(g)
    generic = set(BUILD_LABELS) | set(BUILD_LABELS.values())
    for b in sorted(bs, key=lambda b: -len(b['id'])):
        if b['id'] not in generic and (b['id'] in label or (b.get('name') or '').lower() in (label,)): return b['id']
    if commit:
        hit = [b['id'] for b in bs if b['engine'].get('commit', '').startswith(commit[:8])]
        if len(hit) == 1: return hit[0]
    for b in bs:
        repo = b['engine'].get('repo', '').rstrip('/').rsplit('/', 1)[-1].lower()
        if repo and repo not in generic and repo in version: return b['id']
    if 'untested' in label: return 'untested'
    ids = {b['id'] for b in bs}
    for k, v in BUILD_LABELS.items():
        if k in label: return v if v in ids or v == 'untested' else (k if k in ids else v)
    return None


def from_issue(issue):
    f = fields(issue.get('body')); n = issue['number']
    game_name = plain(f.get('Game'), 80)
    g = next((g for g in S2M.GAMES.values() if fold(g['name']) == fold(game_name)), None)
    if not g: return {'ok': False, 'problem': f'"{game_name or "no game"}" is not a game this repository has a page for yet, so a maintainer adds it by hand.'}
    mac_text = plain(f.get('Mac'), 80)
    chip = re.search(r'\bM(\d{1,2})(?:\s*(Pro|Max|Ultra))?\b', mac_text, re.I)
    mem = re.search(r'(\d{1,3})\s*GB\b', mac_text, re.I)
    if not chip or not mem: return {'ok': False, 'problem': 'The Mac line needs its chip and memory, as About This Mac shows them (for example "MacBook Air, M3, 16 GB").'}
    chip_name = f'M{chip[1]}' + (f' {chip[2].capitalize()}' if chip[2] else '')
    model = plain(mac_text[:chip.start()].replace(',', ' '), 30) or 'Mac'
    label = plain(f.get('Build'), 60).lower()
    version = plain(f.get('Build version (optional)'), 40)
    m = re.search(r'\b([0-9a-f]{7,12})\b', version)
    bid = which_build(g, label, version.lower(), m[1] if m else '')
    if not bid: bid = S2M.recommend(g, {'generation': int(chip[1]), 'memory_gb': int(mem[1])})[0]
    pin = next((b['engine']['commit'] for b in S2M.builds(g) if b['id'] == bid), '')
    build = f'{bid} {m[1][:8]}' if m else (f'{bid} {pin[:8]}' if pin else bid)
    macos = re.search(r'\d+(?:\.\d+){0,2}', plain(f.get('macOS version'), 20))
    used = re.search(r'\d+(?:\.\d+)?', plain(f.get('Memory used (optional)'), 20))
    fps = re.search(r'\d+(?:\s*-\s*\d+)?', plain(f.get('Frame rate'), 40))
    row = [model, chip_name, mem[1], macos[0] if macos else '', build, fps[0].replace(' ', '') if fps else '', used[0] if used else '',
           plain(f.get('How it went'), 300) or plain(f.get('Frame rate'), 60), f'switch2mac#{n}', (issue.get('created_at') or '')[:10]]
    return {'ok': True, 'game': g['name'], 'dir': str(g['dir'].relative_to(ROOT)), 'row': row}


def apply(result):   # the row in its game's table; a row from the same issue is replaced
    t = ROOT / result['dir'] / 'reports.tsv'; src = result['row'][8]
    lines = [l for l in t.read_text().splitlines() if l.split('\t')[8:9] != [src]] if t.exists() else []
    t.write_text('\n'.join(lines + ['\t'.join(result['row'])]) + '\n')


def main():
    a = sys.argv[1:]
    if len(a) < 2 or a[0] != 'from-issue' or not a[1].isdigit(): sys.exit(__doc__)
    issue = json.loads(subprocess.run(['gh', 'api', f'repos/azmasm/hermit/issues/{a[1]}'], capture_output=True, text=True, check=True).stdout)
    r = from_issue(issue)
    if r['ok'] and '--apply' in a: apply(r)
    print(json.dumps(r, ensure_ascii=False))


if __name__ == '__main__':
    main()
