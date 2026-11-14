#!/usr/bin/env python3
"""Hermit: build a native Mac app of a Switch 2 game from your own dump.

  ./hermit.py setup                       Python packages into .venv (once)
  ./hermit.py build <dump folder>         the whole build: game files, code, shaders, host, app
  ./hermit.py build <dump> --engine <id>  a game with several builds (Mario Kart World: switch2mac, nxnative): that one, not the one chosen for this Mac
  ./hermit.py builds <dump folder>        which builds the game has, which one this Mac gets and why, and how they ran on players' Macs
  ./hermit.py refresh                     take in the shaders the app saved while you played, and pack the app again
  ./hermit.py install                     move the finished app to /Applications (replacing the old one)
  ./hermit.py run [VAR=value ...]         run the build straight from ./work with a log in work/logs (for porting and debugging: docs/porting.md)

The dump folder holds exefs/ (main, main.npdm, sdk, ...) and romfs/, or base/exefs and base/romfs; or the dump is one .nup file (a NUP container: base, updates and DLC),
which the nxnative-based builds open themselves (tools/nup.py reads its title ID and version first).
Everything the build writes goes to ./work (--work names another folder). Nothing of the game is in this repository.
Each supported game has a folder in games/ (game.json names it); its profile is in its engine (Mario Kart World: hermit-builds' dm/games/<title ID>).
A game whose game.json names an "engine" (upstream nxnative or pokopia-native) is built by that engine's own builder at the pinned commit (fetched once into ./engines),
with Mario Kart World's overlay and key-2 settings panel added (tools/engine/patch.py); refresh and run are not for those.
A game can have several builds (game.json "builds", each with its own engine and shader list): game.json "choose" picks one for this Mac (its chip and memory),
from what players reported (games/<game>/reports.tsv); --engine overrides it.
"""
import base64, collections, argparse, datetime, hashlib, json, os, re, shutil, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NX = None   # the engine of the game being built on Hermit's engine: engines/switch2mac-<commit> (use_engine)
VENV = ROOT / '.venv'
ENGINES = ROOT / 'engines'   # pinned checkouts of the other engines some games are built with (game.json "engine")
GAMES = {g['title_id']: dict(g, dir=p.parent) for p in sorted((ROOT / 'games').glob('*/game.json')) for g in [json.loads(p.read_text())]}
SKIP = {'.listing', '.DS_Store'}   # a dump tool's FTP listings and Finder's files: never game files


def say(msg): print(f'\n== {msg}', flush=True)


def builds(g):   # a game's tested builds (game.json "builds"); a game with one "engine" has one build, named after its engine; a game not in games/ has none
    if 'builds' in g: return g['builds']
    return [{'id': g['engine']['kind'], 'name': KINDS.get(g["engine"]["kind"], g["engine"]["kind"]), 'engine': g['engine'], 'shader_list': 'shader_list.tsv'}] if 'engine' in g else []


def unknown_game(tid):   # a game Hermit has no folder for: it can still be tried with the untested builds (a Switch 1 game: nxnative's, which knows most of them)
    s1 = tid.startswith('01')
    return {'title_id': tid, 'name': engine_game_name(tid) or listed_name(tid) or file_game_name(tid) or f'Switch {1 if s1 else 2} game {tid}', 'version': '', 'builds': [], 'dir': None, 'switch1': s1}


def file_game_name(tid):   # an unlisted Switch game's name from its own file name, tags and version left out ("Red Dead Redemption v0 (01007820196A6000).nsp" → "Red Dead Redemption"); '' without one
    for p in DUMP_S1:
        if any(int(t, 16) & ~0x1FFF == int(tid, 16) for t in s1_ids(p)):
            n = re.sub(r'\s+', ' ', re.sub(r'\[[^\]]*\]|\([^)]*\)|\bv\d+(\.\d+)*\b', ' ', p.stem)).strip(' -_.')
            if n: return n
    return ''


def listed_name(tid):   # the game's name in games/titles.tsv (nxnative's profiles), '' when it has none
    t = ROOT / 'games/titles.tsv'
    return next((l.rstrip('\n').split('\t')[1] for l in t.open(encoding='utf-8') if l.upper().startswith(tid + '\t')), '') if t.exists() else ''


def engine_game_name(tid):   # the game's name in the nxnative profile at the pin Hermit keeps (dm/games/<title ID>/game.tsv "name"), '' when that engine is not fetched or has none
    for d in sorted(ENGINES.glob('nxnative-*')):
        f = d / f'dm/games/{tid}/game.tsv'
        if f.is_file():
            for l in f.read_text(errors='replace').splitlines():
                if l.startswith('name\t'): return l.split('\t', 1)[1].strip()
    return ''


def this_mac():   # what the build choice reads: the chip (its generation: 1 for M1, ...) and memory
    def sysctl(k): return subprocess.run(['sysctl', '-n', k], capture_output=True, text=True).stdout.strip()
    chip = sysctl('machdep.cpu.brand_string'); m = re.search(r'\bM(\d+)\b', chip)
    try: model = json.loads(subprocess.run(['system_profiler', 'SPHardwareDataType', '-json'], capture_output=True, text=True, timeout=20).stdout)['SPHardwareDataType'][0].get('machine_name', '')
    except Exception: model = ''   # "MacBook Air", "MacBook Pro", "Mac mini" ...: a "choose" rule's "model"
    return {'chip': chip, 'generation': int(m[1]) if m else 0, 'memory_gb': int(sysctl('hw.memsize') or 0) >> 30, 'model': model, 'macos': macos()}


def update_name(b, ver, upd=None):   # the dump's update as players name it ("1.2.0"): from its file name, else the build's version_names for its number; '' for none or unknown
    if upd:
        m = re.search(r'(?<!\d)(?<!\d\.)(\d{1,2})\.(\d{1,2})\.(\d{1,2})(?!\.?\d)', Path(upd).stem)
        if m: return '.'.join(m.groups())
    return (b.get('version_names') or {}).get(ver or '', '')


def plays_text(b):   # the game versions a build plays, in words: game.json build "plays", else from its "versions" and "version_names"; '' when it lists none (any version)
    if b.get('plays'): return b['plays']
    names = b.get('version_names') or {}
    vs = ['the base game alone' if v == 'v0' else f'update {names[v]} ({v})' if v in names else f'update {v}' for v in b.get('versions') or []]
    return ' or '.join(vs)


def fit_note(b, ver, upd=None, name=''):   # why a build does not play this dump, in words, '' when it does (game.json build "plays", "update_versions", "needs_update", "no_update")
    has_upd = bool(upd) or (ver not in (None, '', 'v0'))
    name = name or update_name(b, ver, upd)
    plays = plays_text(b)
    if b.get('no_update') and has_upd: return f'plays {plays}: leave your update out (Clear it under Update and DLC, or build from the base file alone)'
    if b.get('needs_update') and not has_upd: return f'plays {plays}: add your update'
    if 'update_versions' in b and has_upd and name and name not in b['update_versions']: return f'plays {plays}; your update is {name}'
    if has_upd and not name and ver in (None, '', 'v0'): return ''   # an update whose version cannot be told (inside a card image): the builder checks it
    if b.get('versions') and ver and ver not in b['versions']:
        return f'plays {plays}; your files are ' + (f'update {name}' if has_upd and name else f'an update ({ver})' if has_upd and ver not in (None, '', 'v0') else 'an update of unknown version' if has_upd else 'the base game alone')
    return ''


def fits(b, ver):   # whether a build plays this game version (game.json build "versions": the update folders its profile knows, "v0" the base game; none listed: any),
    # and this dump's form: Hermit's own engine reads a dump's folders, so a .nup goes to the engines whose builders open it (nxnative, pokopia-native);
    # Switch 1 files (NSP / XCI, opened with the player's keys) to the builders that take them (S1_KINDS)
    if DUMP_NUP and b['engine']['kind'] == 'switch2mac': return False
    if DUMP_S1 and b['engine']['kind'] not in S1_KINDS: return False
    return not ver or not b.get('versions') or ver in b['versions']


def recommend(g, mac, ver=None):   # (build id, why): the first game.json "choose" rule this Mac meets (chip_min, chip_max, memory_min, memory_max, model) whose build plays the dump's version, else the first build that does
    bs = {b['id']: b for b in builds(g)}
    if not ver and builds(g) and builds(g)[0].get('versions'): ver = builds(g)[0]['versions'][0]   # version unknown (no dump at hand): the game's main one, its first build's
    for r in g.get('choose', []):
        if r['build'] in bs and not fits(bs[r['build']], ver): continue
        models = [r['model']] if isinstance(r.get('model'), str) else r.get('model', [])
        if models and mac.get('model', '').lower() not in [m.lower() for m in models]: continue   # the Mac's model name, as "About This Mac" gives it ("MacBook Air")
        if mac['generation'] < r.get('chip_min', 0) or mac['generation'] > r.get('chip_max', 99): continue
        if mac['memory_gb'] < r.get('memory_min', 0) or mac['memory_gb'] > r.get('memory_max', 1 << 20): continue
        return r['build'], r.get('why', '')
    if not builds(g):   # no tested build: nxnative's guess is the most complete (its survey and memory check)
        u = [b['id'] for b in untested_builds(g)]
        return ('nxnative-untested' if 'nxnative-untested' in u else (u[0] if u else '')), 'No tested build of this game yet: every build here is untested'
    ok = [b for b in builds(g) if fits(b, ver)]
    if ver and not ok: return builds(g)[0]['id'], f'No build here knows your dump\'s version ({ver}); this one may not start'
    return (ok or builds(g))[0]['id'], ''


S1_KINDS = ('nxnative', 'macnativegames')   # the engines whose builders take a Switch 1 game's NSP / XCI files and the player's prod.keys
NO_UNTESTED = ('macnativegames',)   # builders made for their own games only (MacNativeGames' build_app.py: Tears of the Kingdom and Breath of the Wild): never offered as a guess for others
KINDS = {'macnativegames': 'MacNativeGames', 'switch2mac': "azmasm's build", 'nxnative': 'nxnative', 'pokopia-native': 'pokopia-native'}   # a build's name in the app: the project it comes from
RISK = ' Nobody has built the game this way yet: it may stop partway, or build and not start. Try it at your own risk; Stop ends it at any time.'
ABOUT = {
    'switch2mac': "Untested: azmasm's build with a profile guessed from this game's own files." + RISK,
    'nxnative': "Untested: nxnative's builder guesses a profile from this game's own files (it may boot the game for a few seconds to size its memory)." + RISK,
    'pokopia-native': "Untested: pokopia-native's engine (nxnative with xFractals' Switch 2 changes) with a profile guessed from this game's own files." + RISK,
}
PROFILE = None   # an untested build on Hermit's engine: the profile guessed from the game's files (<work>/guessed/<title ID>); None: the engine's own


def engine_pins():   # each engine's pin that an untested build uses: the ones the updater keeps current (Mario Kart World's two)
    # A build named after its kind is that project's own (nxnative's build is seedds/nxnative); a game's other builds of the kind are forks (mkw-neo,
    # Thijs2004's 1.8.0 port, kid-with-sword, ...) and are used only for a kind no game has its own build of
    pins, forks = {}, {}
    for g in GAMES.values():
        for b in builds(g): (pins if b['id'] == b['engine']['kind'] else forks).setdefault(b['engine']['kind'], b['engine'])
    for tid, kind in (('0400C3F00006E000', 'switch2mac'), ('0400C3F00006E000', 'nxnative')):
        for b in builds(GAMES.get(tid, {})):
            if b['engine']['kind'] == kind and b['id'] == kind: pins[kind] = b['engine']
    return {**forks, **pins}


CUSTOM = None   # --custom URL[@branch or commit]: the player's own nxnative fork, offered as the untested build "custom" (custom_build)


def custom_build():   # the player's own fork as a build: nxnative's builder at the fork's commit (a branch or tag is resolved to its commit once, here)
    url, _, ref = CUSTOM.partition('@')
    url = url.strip().rstrip('/')
    if not re.fullmatch(r'https://[\w.-]+/[\w.-]+/[\w.-]+(\.git)?', url): sys.exit(f'--custom takes a repository link such as https://github.com/<you>/nxnative (then @branch if not the main one): {url}')
    if re.fullmatch(r'[0-9a-f]{40}', ref): sha = ref
    else:
        r = subprocess.run(['git', 'ls-remote', url, ref or 'HEAD'], capture_output=True, text=True, timeout=60, env=dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_ASKPASS='/usr/bin/false'))   # never a password prompt
        heads = [l.split('\t')[0] for l in r.stdout.splitlines() if l.strip()]
        if r.returncode or not heads: sys.exit(f'could not reach {url}{" branch " + ref if ref else ""}: check the link (a public repository) and the branch name')
        sha = heads[0]
    repo = '/'.join(url.removesuffix('.git').split('/')[-2:])
    return {'id': 'custom', 'name': f'Your build ({repo}{"@" + ref if ref and len(ref) < 40 else ""})', 'engine': {'kind': 'nxnative', 'repo': url, 'commit': sha}, 'untested': True,
            'about': f'Your own build: {url} at {sha[:12]}, built with nxnative\'s builder. Hermit has not checked it: it may stop partway or not start.'}


CUSTOM_PROBLEM = ''


def custom_builds():   # [the player's own build], or [] with CUSTOM_PROBLEM saying why (a link that does not answer never stops the game being read)
    global CUSTOM_PROBLEM
    if not CUSTOM: return []
    try: return [custom_build()]
    except (SystemExit, subprocess.TimeoutExpired) as x: CUSTOM_PROBLEM = str(x) or 'the link did not answer'; return []


UNTESTED_KINDS = ('nxnative',)   # the one engine offered untested for any game; the others stay with the games they were made for (pokopia-native: Pokopia; switch2mac, mkw-neo: Mario Kart World)


def untested_builds(g):
    """Every engine the game has no tested build on, as an untested build: each guesses a profile from the game's own files (never another engine's
    profile). They will often fail; someone may take one further in a port of their own, which then becomes a tested build here."""
    have = {b['engine']['kind'] for b in builds(g)}; pins = engine_pins()
    wip = g.get('wip', {})   # game.json "wip": {kind: engine pin}, a port of this game on that engine still in progress, at its own pin (Ocarina of Time on Hermit's oot work)
    pins.update(wip)
    s1 = g.get('switch1') or g.get('title_id', '').startswith('01')   # a Switch 1 game: only the builders that open its files
    known = s1 and bool(engine_game_name(g.get('title_id', '')))   # nxnative's own profile for it (it has about 150 Switch 1 games): no guess
    return [{'id': f'{k}-untested', 'name': f'{KINDS[k]} (untested)', 'engine': pins[k], 'untested': True,
             'about': (f"Work in progress: {KINDS[k]} with its own profile for this game, not finished yet." + RISK) if k in wip else
                      (f"Not tried through Hermit yet: {KINDS[k]} with its own profile for this game. Needs your own prod.keys." + RISK) if known else ABOUT[k]}
            for k in KINDS if k in UNTESTED_KINDS and k not in have and k in pins and k not in NO_UNTESTED and (not s1 or k in S1_KINDS)] + custom_builds()


def profile_src(tid): return PROFILE or NX / f'dm/games/{tid}'


def with_build(g, bid=None, ver=None):   # the game as one of its builds: its engine and shader list (bid None: the one game.json "choose" picks for this Mac and the dump's version)
    bs = builds(g) + untested_builds(g)
    if not bid: bid = recommend(g, this_mac(), ver)[0]
    b = next((b for b in bs if b['id'] == bid), None)
    if not b: sys.exit(f'{g["name"]} has no build {bid!r} (its builds: {", ".join(b["id"] for b in bs)})')
    return dict(g, engine=b['engine'], build=b, disk_gb=b.get('disk_gb', g.get('disk_gb')))   # a build may need more disk than the game's usual (Pokopia's full nxnative build)


def list_keys(g, b):   # how many shaders a build's shared list names (games/<game>/<its shader_list>: S and C rows), 0 for none
    f = g['dir'] / b.get('shader_list', 'shader_list.tsv') if g.get('dir') else None
    try: return len(re.findall(r'^[SC]\t[0-9a-f]{16}(?:_[a-z]+)?(?:\t|$)', f.read_text(errors='replace'), re.M)) if f else 0
    except OSError: return 0


def engine_seen(commit, tid):   # the engine profile at that commit ships a list of the shaders players used (shader_seen.tsv). Noted in engine-seen.json
    # ("<commit12>/<title ID>": true / false) while the download is here, so the Build page still offers a quick try after trim_build removed it
    key, d, SEEN_MEMO = f'{commit[:12]}/{tid}', ENGINES / f'nxnative-{commit[:12]}', app_folder() / 'engine-seen.json'
    try: memo = json.loads(SEEN_MEMO.read_text())
    except (OSError, ValueError): memo = {}
    if not (d / '.git').is_dir(): return bool(memo.get(key))
    have = (d / 'dm/games' / tid / 'shader_seen.tsv').is_file()
    if memo.get(key) != have:
        memo[key] = have; memo = dict(list(memo.items())[-300:])
        try: SEEN_MEMO.write_text(json.dumps(memo))
        except OSError: pass
    return have


def quick_ok(g, b):   # a quick try (--quick) needs nxnative's builder and a list of the shaders players used: the game's shared list, or the engine profile's own shader_seen.tsv
    if b['engine']['kind'] != 'nxnative' or b.get('untested'): return False
    if list_keys(g, b): return True
    return bool(g.get('title_id')) and engine_seen(b['engine']['commit'], g['title_id'])


def reports(g):   # how the game ran on players' Macs (games/<game>/reports.tsv): one dict a report
    if not g.get('dir'): return []
    f = g['dir'] / 'reports.tsv'; keys = ('mac', 'chip', 'memory_gb', 'macos', 'build', 'fps', 'peak_gb', 'notes', 'source', 'date')
    return [dict(zip(keys, l.split('\t'))) for l in (f.read_text().splitlines() if f.exists() else []) if l.strip() and not l.startswith('#')]


def built_game(w):   # the game a finished build in w is, as the build it was made with (title.txt, build.txt)
    tf = w / 'title.txt'
    if not tf.exists(): sys.exit('no finished build in ' + str(w) + ': run build first')
    tid = tf.read_text().strip(); bf = w / 'build.txt'
    if tid not in GAMES: GAMES[tid] = unknown_game(tid)
    GAMES[tid] = with_build(GAMES[tid], bf.read_text().strip() if bf.exists() else builds(GAMES[tid])[0]['id'])
    global PROFILE
    guessed = w / 'guessed' / tid
    PROFILE = guessed if GAMES[tid]['build'].get('untested') and (guessed / 'game.tsv').is_file() else None
    return tid


class Progress:
    """The build's stages. --progress json writes one event per line, the form the Hermit app reads (NX2Apple's launcher, from nxnative's build script):
    {"ev": "stage", "k": 2, "n": 7, "name": ...}, {"ev": "step", "k", "step"}, {"ev": "stage_end", "k", "name", "ok", "elapsed", "summary"}, {"ev": "say", "msg"}.
    Anything else on the output (the tools' own lines) is log text. Without it, a stage is the usual '== name' line."""
    # Time left: each stage's expected length is how long it took the last time (history: <work>/stage_times.json), else a first-build guess
    # (FIRST: Mario Kart World on an M1 Max with nothing cached). While a stage runs, a progress event a second gives its share done and the
    # seconds left (marked as an estimate); the app shows them as the bar and the time left. The history is written when a stage ends well.
    FIRST = {'the dump': 1, 'game files': 140, 'code': 90, 'shader split': 15, 'Metal shaders': 900, 'host': 30, 'app': 160, 'engine': 60,
             'game code': 160, 'game data': 60, 'startup shaders': 1200, 'the app': 450}   # the last four: MacNativeGames' steps (Tears of the Kingdom, M1 Max, nothing cached)
    order = []   # the stages still to come after the running one, for the time left in all (Mario Kart World's build sets them)
    def __init__(self): self.json, self.k, self.n, self.name, self.t0, self.open, self.step_text, self.hist, self.hist_path = False, 0, 0, '', 0.0, False, '', {}, None
    def history(self, path):
        self.hist_path = Path(path)
        try: self.hist = json.loads(self.hist_path.read_text())
        except (OSError, ValueError): self.hist = {}
    def _tick(self, k):
        exp = self.hist.get(self.name) or self.FIRST.get(self.name)
        if not exp: return
        while self.open and self.k == k:
            t = time.time() - self.t0; left = max(1.0, exp - t)
            later = sum(self.hist.get(n) or self.FIRST.get(n, 0) for n in self.order[self.order.index(self.name) + 1:]) if self.name in self.order else 0
            total = left + later; mins = round(total / 60)
            note = f'about {mins} min left in all' if mins >= 2 else 'about a minute left in all' if total > 30 else 'almost done'
            self.emit('progress', k=k, frac=round(min(0.99, t / exp), 3), eta=round(left), step=self.step_text, note=note, est=True)
            time.sleep(1)
    def emit(self, ev, **kw):
        if self.json: print(json.dumps(dict(ev=ev, **kw), ensure_ascii=False), flush=True)
    def plan(self, n): self.n = n
    def stage(self, name, step=''):   # ends the stage before it (done) and starts the next
        if self.open: self.end()
        self.k += 1; self.name, self.t0, self.open, self.step_text = name, time.time(), True, step
        if self.json:
            self.emit('stage', k=self.k, n=max(self.n, self.k), name=name, step=step)
            import threading; threading.Thread(target=self._tick, args=(self.k,), daemon=True).start()
        else: say(name + (f' ({step})' if step else ''))
    def step(self, text):
        if self.json and self.open: self.emit('step', k=self.k, step=text)
        else: print(f'  {text}', flush=True)
    def end(self, ok=True, summary=''):
        if not self.open: return
        self.open = False
        took = round(time.time() - self.t0, 1)
        self.emit('stage_end', k=self.k, name=self.name, ok=ok, elapsed=took, summary=summary)
        if ok and self.hist_path:
            self.hist[self.name] = took
            try: self.hist_path.parent.mkdir(parents=True, exist_ok=True); self.hist_path.write_text(json.dumps(self.hist, indent=1))
            except OSError: pass


P = Progress()


HIDE = {}   # paths never written to the output (the build log the app keeps and players may share): the player's prod.keys → a placeholder


def hide(text):
    for path, label in HIDE.items(): text = text.replace(path, label)
    return text


def run(cmd, env=None, cwd=None, shift=None, watch=None):   # shift: the tool writes --progress json events of its own: number its stages after ours (shift = our stages before it); watch: called with each output line
    print('$', hide(' '.join(str(c) for c in cmd)), flush=True)
    if shift is None and not HIDE and not watch:
        r = subprocess.run([str(c) for c in cmd], env=env, cwd=cwd); rc = r.returncode
    else:
        pr = subprocess.Popen([str(c) for c in cmd], env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
        for line in pr.stdout:
            ev = None
            if line.startswith('{'):
                try: ev = json.loads(line)
                except ValueError: pass
            if isinstance(ev, dict) and 'ev' in ev:
                if 'k' in ev: ev['k'] += shift or 0
                if 'n' in ev: ev['n'] += shift or 0; P.plan(ev['n'])
                line = json.dumps(ev, ensure_ascii=False) + '\n'
            sys.stdout.write(hide(line)); sys.stdout.flush()
            if watch: watch(line)
        rc = pr.wait()
    if rc:
        P.end(False, f'{Path(str(cmd[1] if len(cmd) > 1 and str(cmd[0]).endswith("python") else cmd[0])).name} failed ({rc})')
        sys.exit(f'\nstopped: {Path(str(cmd[0])).name} failed ({rc})')


MNG_STEPS = ('game code', 'game data', 'startup shaders', 'the app')   # MacNativeGames' builder says "[time] 1/4 code: ...", "2/4 data: ..." (build_app.py say): one stage each


def mng_watch(line):   # a MacNativeGames builder line → our stage (its time left from the last build of this game, else FIRST) or the running stage's step text
    m = re.search(r'\]\s+([1-4])/4 \w+: ?(.*)', line)
    if not m: return
    name, text = MNG_STEPS[int(m[1]) - 1], hide(m[2].strip())[:140]
    if name != P.name and (P.name not in MNG_STEPS or MNG_STEPS.index(name) > MNG_STEPS.index(P.name)): P.stage(name, text)
    else: P.step(text)


def has_packages():   # the build's Python packages are importable here (the Hermit app's bundled Python): no .venv needed
    import importlib.util
    return sys.version_info >= (3, 12) and all(importlib.util.find_spec(m) for m in ('capstone', 'lz4', 'fontTools', 'zstandard'))


def py():   # the Python the build's tools run under: .venv (Terminal setup), else this one when it has the packages (the Hermit app's own Python, which never makes a .venv)
    p = VENV / 'bin/python'
    if p.exists(): return p
    if has_packages(): return Path(sys.executable)
    sys.exit('run ./hermit.py setup first')


def env():
    e = dict(os.environ, PATH=f'{VENV / "bin"}:{os.environ["PATH"]}', DMSH_BORDER_EMU='0', DM_ALLOW_OTHER_METAL='1')
    if 'DOTNET_ROOT' not in e:
        for d in ('/usr/local/share/dotnet', '/opt/homebrew/opt/dotnet/libexec', str(Path.home() / '.dotnet')):
            if Path(d, 'dotnet').exists(): e['DOTNET_ROOT'] = d; break
    return e


def macos():   # this Mac's macOS as major.minor (e.g. 26.5): the app is built for the Mac that builds it, like its Metal shaders
    v = subprocess.run(['sw_vers', '-productVersion'], capture_output=True, text=True).stdout.strip().split('.')
    return f'{v[0]}.{v[1] if len(v) > 1 else 0}'


def good_python():   # a Python 3.12 or later for .venv: this one, else the newest Homebrew or python.org one (macOS's own python3 is 3.9)
    if sys.version_info >= (3, 12): return sys.executable
    cands = [shutil.which(f'python3.{m}') for m in range(20, 11, -1)] + [f'/opt/homebrew/bin/python3.{m}' for m in range(20, 11, -1)] + ['/opt/homebrew/bin/python3', '/usr/local/bin/python3'] \
            + [f'/Library/Frameworks/Python.framework/Versions/3.{m}/bin/python3' for m in range(20, 11, -1)]
    for c in cands:
        if not c or not os.access(c, os.X_OK): continue
        r = subprocess.run([c, '-c', 'import sys; print(sys.version_info >= (3, 12))'], capture_output=True, text=True)
        if r.stdout.strip() == 'True': return c
    return None


def setup(a):
    say('checks')   # each missing piece with the exact fix; setup stops before anything else when one is missing
    bad = []
    def check(name, ok, fix):
        print(f'  {"ok     " if ok else "MISSING"}  {name}' + ('' if ok else f'\n           fix: {fix}'))
        if not ok: bad.append(name)
    v = macos()
    check(f'macOS 26 or later (this Mac: {v})', int(v.split('.')[0]) >= 26, 'update macOS in System Settings → General → Software Update (the games draw with Metal 4, new in macOS 26)')
    xc = subprocess.run(['xcode-select', '-p'], capture_output=True, text=True)
    check('Xcode', xc.returncode == 0 and 'Xcode' in xc.stdout and shutil.which('clang++') is not None,
          'install Xcode from the App Store, open it once, then in Terminal: sudo xcode-select -s /Applications/Xcode.app')
    r = subprocess.run(['xcrun', '-sdk', 'macosx', 'metal', '--version'], capture_output=True, text=True)
    check('Metal Toolchain', r.returncode == 0, 'open Xcode → Settings → Components, and install Metal Toolchain')
    check('.NET 10', 'DOTNET_ROOT' in env(), 'install the .NET 10 SDK from https://dot.net (or: brew install --cask dotnet-sdk)')
    gp = good_python()
    if VENV.exists() and subprocess.run([py(), '-c', 'import sys; sys.exit(sys.version_info < (3, 12))']).returncode: shutil.rmtree(VENV)   # an old .venv made with Python 3.9
    check('Python 3.12 or later' + (f' ({gp})' if gp else ''), gp is not None, 'install Python from https://www.python.org/downloads (or: brew install python), then run setup again')
    check('git', shutil.which('git') is not None, 'comes with Xcode: install Xcode first')
    if bad: sys.exit(f'\nsetup stopped: {len(bad)} thing(s) missing ({", ".join(bad)}). Install them as shown above, then run setup again.')
    say('Python packages (.venv)')
    if not VENV.exists(): run([gp, '-m', 'venv', VENV])
    run([py(), '-m', 'pip', 'install', '-q', '--disable-pip-version-check', '-r', ROOT / 'requirements.txt'])
    print('\nsetup done: everything is ready to build a game.')


def free_space(w, g):   # stop before a build that cannot fit (game.json "disk_gb": the free space a first build needs); S2M_SKIP_DISK_CHECK=1 skips it
    need = g.get('disk_gb'); w.mkdir(parents=True, exist_ok=True)
    have = shutil.disk_usage(w).free / 1e9
    if need and have < need and os.environ.get('S2M_SKIP_DISK_CHECK') != '1':
        sys.exit(f'not enough free disk space: {g["name"]} needs about {need} GB for its first build, this disk has {have:.0f} GB free.\n'
                 'Free some space (or build on another disk with --work <folder>), then try again.')


def dump_dirs(d):
    d = Path(d).expanduser().resolve()
    for base in (d, d / 'base'):
        if (base / 'exefs/main').is_file() and (base / 'romfs').is_dir(): return base / 'exefs', base / 'romfs'
    sys.exit(f'no exefs/main and romfs/ in {d} (or in {d}/base)')


EMPTY_TABLES = {   # a guessed profile's shader tables before the shader split fills them (as nxnative's builder writes them for its provisional profiles)
    'shader_map.tsv': '# kind: evidence  provisional profile: filled by the shader split\npackage\tindex\tstage\tdm_ctl_sha16\tsource\n',
    'shader_facts.tsv': '# Answer table for translation queries. Provisional profile: filled by the shader split\n',
    'shader_pairs.tsv': '# kind: evidence  vertex / pixel shader pairs within BNSH variations\n',
    'shader_map.tsv.conflicts.tsv': '# kind: evidence  control-section key conflict rulings: empty\ndm_ctl_sha16\tchosen_pc\tclass\tcandidates\trecords\n',
    'bf_want.tsv': '# generated\n',
    'pso_manifest.tsv': '# Prewarm seed list. Provisional profile: empty\n'}


def guess_profile(w, tid, exefs, romfs, version, name):
    """A provisional profile for Hermit's engine, guessed from the game's own files by the engine's dm/games/profile_guess.py (the keys and layout
    nxnative's builder writes for a game it has no profile for, without its memory check). In <work>/guessed/<title ID>; an existing one is kept, so it can be edited by hand."""
    out = w / 'guessed' / tid
    if (out / 'game.tsv').is_file(): print(f'  reusing the guessed profile {out / "game.tsv"} (delete it to guess again)'); return out
    sys.path.insert(0, str(NX / 'dm/games')); import profile_guess as pg
    F = pg.facts_of(exefs, romfs); G, R = pg.guess(F), F['romfs']
    groups, seen = [], {'main', 'other'}
    for d, _ in R['dirs'].most_common(24):
        g = re.sub(r'[^a-z0-9]', '', d.lower())[:16] or 'g'
        while g in seen: g += 'x'
        seen.add(g); groups.append(f'/{d}/={g}')
    store = sorted(x for x, n in R['extb'].items() if x and R['exts'][x] and (n / R['exts'][x] >= 1 << 20 or 2 * R['extc'][x] >= R['exts'][x]))
    mods = G['modules'][0].split(); T = '\t'
    def key(k, default=None):
        v, why = G[k] if k in G else (default, '')
        return [] if v is None else ([f'# {why}'] if why else []) + [f'{k}{T}{v}']
    ipa = (''.join(re.findall(r'[A-Za-z0-9]+', name))[:48] or tid) + '.ipa'
    L = ['# Provisional game profile (guessed by hermit.py with dm/games/profile_guess.py for an untested build, not checked by hand)', f'# {name}, SDK {F["sdk"] or "?"}', '',
         f'title_id{T}{tid}', f'program_id{T}{(F["program"] or int(tid, 16)):016X}', '',
         f'name{T}{name}', f'ipa{T}{ipa}', f'app_category{T}public.app-category.games', *key('pad_layout'), *key('op_mode'), '',
         T.join(['build', version, version] + [f'{m}={F["mods"][m]["bid"]}' for m in mods if m in F['mods']]), f'package{T}{version}', f'shader_versions{T}{version}', '',
         *key('modules'), f'romfs_marker{T}{R["biggest"][1]}', f'zip_store{T}{":".join(store + [".metallib"])}', '',
         *key('mem_reserve'), *key('mem_alias'), *key('mem_stack'), *key('app_pool'), *key('sys_resource'), '',
         *key('shader_groups', " ".join(groups) or "/=romfs"), f'shader_note{T}{name} shaders']
    out.mkdir(parents=True, exist_ok=True); (out / 'game.tsv').write_text('\n'.join(L) + '\n', encoding='utf-8')
    for n, text in EMPTY_TABLES.items(): (out / n).write_text(text)
    print(f'  guessed a provisional profile: {out / "game.tsv"}')
    return out


def update_dirs(d):   # the newest update's exefs and romfs when it holds both (updates/exefs + updates/romfs, or updates/<version>/...): an update RomFS is the whole patched tree
    d = Path(d).expanduser().resolve(); found = []
    for u in [d / 'updates'] + sorted((p for p in (d / 'updates').glob('*') if p.name.isdigit()), key=lambda p: int(p.name), reverse=True):
        if (u / 'exefs/main').is_file() and (u / 'romfs').is_dir(): found.append(u)
    return (found[0] / 'exefs', found[0] / 'romfs') if found else None


DUMP_NUP = None; NUP_BASE = True   # the .nup the dump path names (read_dump), or None for a dump folder


def nup_file(d):   # the NUP container a dump path names: the .nup file itself, or the one .nup in a folder holding no exefs/ or base/; None for a dump folder
    d = Path(d).expanduser().resolve()
    sys.path.insert(0, str(ROOT / 'tools')); import nup
    if d.is_file(): return d if nup.is_nup(d) else None
    if d.is_dir() and not any((d / x).is_dir() for x in ('exefs', 'base')):
        found = [p for p in sorted(d.glob('*.nup')) if nup.is_nup(p)]
        if len(found) > 1: sys.exit(f'more than one .nup in {d}: {", ".join(p.name for p in found)}; keep one game per folder, or choose the .nup file itself')
        if found: return found[0]
    return None


def nup_scan(p):   # (title ID, newest update version or 0) of a NUP: its table of contents and main.npdm, every file read checked against its SHA-256
    sys.path.insert(0, str(ROOT / 'tools')); import nup
    try:
        with nup.Nup(p) as n:
            app, base, vers, _ = nup.scan(n)
            global NUP_BASE; NUP_BASE = base is not None   # a NUP of standalone updates has none: builds marked "nup_needs_base" cannot take it
            return f'{app:016X}', max(vers) if vers else 0
    except nup.Error as x: sys.exit(f'{x}. Copy the .nup again, or extract it to a dump folder.')


def read_dump(d):   # once per command: whether the dump is a .nup (DUMP_NUP) or Switch 1 files (DUMP_S1), so the build choice and the checks know
    global DUMP_NUP, DUMP_S1
    there = Path(d).expanduser().exists()
    DUMP_NUP = nup_file(d) if there else None
    DUMP_S1 = s1_files(d) if there and not DUMP_NUP else []
    if DUMP_S1 and S1_EXTRA: DUMP_S1 = sorted(set(DUMP_S1) | {p for p in S1_EXTRA if p.is_file() and p.suffix.lower() in S1_EXT})   # an update or DLC the player added (--add)
    return DUMP_NUP


# Switch 1 games come as their own console's NSP / NSZ / XCI / XCZ files (base game, update, DLC), which are encrypted: only the builder opens them, with the
# player's own prod.keys (passed to it as a path at build time, never read, copied or stored here). Hermit reads no game data from them: which game and
# version they are comes from what a dump tool writes in the clear, the "[title ID][v<version>]" in the file names and an NSP's ticket names (<rights ID>.tik,
# whose first 16 hex digits are the title ID). Hermit holds no decryption code (LEGAL.md).
DUMP_S1 = []   # the Switch 1 files the dump path names (read_dump), or [] for a Switch 2 dump
S1_EXT = ('.nsp', '.nsz', '.xci', '.xcz')
S1_PICK = None   # --title-id: which game of a cartridge with several (or of files of several games) to build
S1_EXTRA = []    # --add: update and DLC files the player added to a Switch game
S1_NO_UPDATE = False   # --no-update: build the game without the update found beside it (a version the chosen build does not play)


def s1_family(p):   # a Switch 1 file's game, from the first title ID in its name: base, update (+0x800) and DLC (+0x1000...) share it; None without one
    t = re.search(r'(?<![0-9A-Fa-f])(01[0-9A-Fa-f]{14})(?![0-9A-Fa-f])', p.name)
    return int(t.group(1), 16) & ~0x1FFF if t else None


def s1_files(d):   # the Switch 1 game files a dump path names: the file itself, or those in a folder that holds no Switch 2 dump (exefs/, base/, a .nup)
    d = Path(d).expanduser().resolve()
    if d.is_file():   # one game's file, perhaps in a folder of many games: it, and its own update and DLC beside it or one folder up (matched by title ID)
        if d.suffix.lower() not in S1_EXT: return []
        fam = s1_family(d)
        if fam is None: fam = next(iter({int(t, 16) & ~0x1FFF for t in s1_ids(d)}), None)   # a file named only after its game: its tickets, or its name
        if fam is None: return [d]
        # beside it, one folder up, and in the folders beside its own (a ROMs folder split by kind: Switch/Games, Switch/Updates, Switch/DLC)
        up = d.parent.parent
        folders = {d.parent, up} | ({x for x in up.iterdir() if x.is_dir() and not x.name.startswith('.')} if up.is_dir() and up != d.parent else set())
        near = [x for folder in folders if folder.is_dir() for x in folder.iterdir()
                if x.is_file() and x.suffix.lower() in S1_EXT and not x.name.startswith('.') and x != d
                and (s1_family(x) == fam or (s1_family(x) is None and fam in {int(t, 16) & ~0x1FFF for t in s1_ids(x)}))]
        return sorted(set(near) | {d})
    if not d.is_dir() or any((d / x).is_dir() for x in ('exefs', 'base')): return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in S1_EXT and not p.name.startswith('.'))


def pfs0_names(p):   # the file names inside an NSP / NSZ (a PFS0 container: its plain table of contents), [] for anything else
    try:
        with p.open('rb') as f:
            head = f.read(0x10)
            if len(head) < 0x10 or head[:4] != b'PFS0': return []
            n, size = struct.unpack_from('<II', head, 4)
            if not 0 < n <= 4096 or size > 1 << 20: return []
            table = f.read(n * 0x18 + size); names = table[n * 0x18:]
        return [names[o:names.index(b'\0', o)].decode('utf-8', 'replace') if b'\0' in names[o:] else names[o:].decode('utf-8', 'replace')
                for o in (struct.unpack_from('<I', table, i * 0x18 + 0x10)[0] for i in range(n)) if o < len(names)]
    except (OSError, ValueError, struct.error): return []


def hfs0_names(f, off):   # [(name, offset from the data start)] of an HFS0 table of contents (a card image's partitions), and where its data starts
    f.seek(off); h = f.read(0x10)
    if len(h) < 0x10 or h[:4] != b'HFS0': return [], 0
    n, ssize = struct.unpack_from('<II', h, 4)
    if not 0 < n <= 4096 or ssize > 1 << 20: return [], 0
    ents, strs = f.read(n * 0x40), f.read(ssize)
    return [(strs[no:strs.index(b'\0', no)].decode('utf-8', 'replace'), o) for o, _, no in (struct.unpack_from('<QQI', ents, i * 0x40) for i in range(n))], off + 0x10 + n * 0x40 + ssize


def xci_names(p):   # the file names in a card image's secure partition (XCI / XCZ: plain HFS0 tables of contents; nothing is decrypted), [] for anything else
    try:
        with p.open('rb') as f:
            f.seek(0x100); h = f.read(0x40)
            if h[:4] != b'HEAD': return []
            root, start = hfs0_names(f, struct.unpack_from('<Q', h, 0x30)[0])
            sec = next((o for n, o in root if n == 'secure'), None)
            return [] if sec is None else [n for n, _ in hfs0_names(f, start + sec)[0]]
    except (OSError, ValueError, struct.error): return []


def inner_names(p):   # the names inside a Switch 1 game file: an NSP's / NSZ's PFS0, or a card image's secure partition
    return pfs0_names(p) or (xci_names(p) if p.suffix.lower() in ('.xci', '.xcz') else [])


def packages_in(p):   # how many titles (game, update, DLC) a file holds: its content meta NCAs (<hash>.cnmt.nca), 0 when unknown
    return sum(1 for n in inner_names(p) if n.lower().endswith('.cnmt.nca'))


def norm_title(s):   # a game name or file name as words: no brackets, tags, accents, punctuation or case ("Pokémon Legends: Arceus [v0] (US)" → "pokemon legends arceus")
    import unicodedata
    s = unicodedata.normalize('NFKD', re.sub(r'\[[^\]]*\]|\([^)]*\)', ' ', s)).encode('ascii', 'ignore').decode().lower().replace('&', ' and ')
    return ' '.join(w for w in re.sub(r'[^a-z0-9]+', ' ', s).split() if w not in ('the', 'nsp', 'xci', 'nsz', 'xcz', 'base', 'game') and not re.fullmatch(r'v\d+', w))


def title_by_name(p):   # a Switch 1 game file named only after its game ("Metroid Dread.xci"): its title ID from games/titles.tsv and the games here, by name (the longest that fits)
    stem = norm_title(p.stem)
    if not stem: return None
    names = {g['title_id']: g['name'] for g in GAMES.values() if g['title_id'].startswith('01')}
    t = ROOT / 'games/titles.tsv'
    if t.exists(): names.update(l.rstrip('\n').split('\t')[:2] for l in t.open(encoding='utf-8') if l.startswith('01') and '\t' in l)
    hits = [(len(k), tid) for tid, name in names.items() if (k := norm_title(name)) and (stem == k or stem.startswith(k + ' '))]
    return max(hits)[1] if hits else None


def s1_ids(p):   # the Switch 1 title IDs a file names: in its file name (any brackets) and its tickets (NSP, card image); else the game its name is (title_by_name)
    if BUILDER_IDS.get(p): return set(BUILDER_IDS[p])   # read from the file itself (builder_titles)
    ids = {t.upper() for t in re.findall(r'(?<![0-9A-Fa-f])(01[0-9A-Fa-f]{14})(?![0-9A-Fa-f])', p.name)} | \
          {n[:16].upper() for n in inner_names(p) if re.fullmatch(r'[0-9A-Fa-f]{32}\.tik', n)}
    if not ids and (t := title_by_name(p)): ids = {t}
    return ids


def s1_apps(files):   # the games (base title IDs) a set of Switch 1 files belongs to, in order
    return sorted({f'{int(t, 16) & ~0x1FFF:016X}' for p in files for t in s1_ids(p)})


def s1_cart(files):   # whether one file carries several games (a cartridge like "Vol. 1 + Vol. 2": "[<id>+<id>]"): then its first game is built unless --title-id picks another
    apps = s1_apps(files)
    return len(apps) > 1 and any({f'{int(t, 16) & ~0x1FFF:016X}' for t in s1_ids(p)} >= set(apps) for p in files)


def s1_scan(files):   # (base game title ID or None, newest update version or 0, every title ID seen) of a set of Switch 1 files, from the names a dump tool gives them
    ids, vers = set(), {}
    for p in files:
        v = re.findall(r'(?:^|[\[\(\s_-])v(\d+)(?=$|[\]\)\s_.-])', p.name)
        found = s1_ids(p)
        for t in found:
            if not t.startswith('01'): continue   # Switch 1 titles start 01
            ids.add(t)
            if v and t.endswith('800'): vers[t] = max(vers.get(t, 0), int(v[-1]))   # an update's title ID is its game's with 800 at the end
    apps = sorted({f'{int(t, 16) & ~0x1FFF:016X}' for t in ids})   # the game each title belongs to (an update's or a DLC's base game)
    pick = (S1_PICK or '').upper()
    base = apps[0] if len(apps) == 1 else pick if pick in apps else apps[0] if s1_cart(files) else None
    return base, max((v for t, v in vers.items() if base and t == f'{int(base, 16) | 0x800:016X}'), default=0), sorted(ids)


KEYS = None          # --keys: the player's prod.keys, for nxnative's own reader of files whose names do not say which game they are (builder_titles)
BUILDER_IDS = {}     # file → title IDs that reader found (s1_ids takes them first)
def app_folder():   # the app's own folder: Hermit's, or switch2mac's (the app's name before it became Hermit) where an app from before the rename still runs
    s = Path.home() / 'Library/Application Support'
    return s / 'Hermit' if (s / 'Hermit').exists() or not (s / 'switch2mac').exists() else s / 'switch2mac'
TITLES_CACHE = app_folder() / 'titles.json'   # what it found, by path, size and date: it reads each file once


def builder_titles(paths):   # the title IDs inside Switch files whose names do not say, read by nxnative's own package reader (nx_extract --contents, with the player's
    # keys: Hermit holds no decryption code), into BUILDER_IDS. Needs the keys and .NET; the first read builds nx_extract (about a minute). Nothing when it cannot
    if not KEYS or not paths: return
    try: cache = json.loads(TITLES_CACHE.read_text())
    except (OSError, ValueError): cache = {}
    key = lambda p: f'{p}|{p.stat().st_size}|{int(p.stat().st_mtime)}'
    want = [p for p in paths if key(p) not in cache]
    if want:
        pins = collections.Counter(json.dumps(b['engine'], sort_keys=True) for g in GAMES.values() for b in builds(g)
                                   if b['engine']['kind'] == 'nxnative' and b['engine']['repo'].rstrip('/').endswith('seedds/nxnative'))
        if not pins: return
        d = engine_dir({'engine': json.loads(pins.most_common(1)[0][0])})   # the nxnative commit most games are pinned at (the updater keeps it recent)
        tool = TITLES_CACHE.parent / f'nx_extract-{d.name}'   # nxnative's extractor, built once per engine commit and kept
        sys.path.insert(0, str(d / 'scripts'))
        got = {}
        try:
            import build_ipa_from_nsp as nb
            say(f'reading which game {len(want)} file(s) are, with nxnative\'s reader and your keys (once)')
            nx = next((x for x in sorted(tool.glob('**/nx_extract')) if x.is_file() and os.access(x, os.X_OK)), None) if tool.is_dir() else None
            if not nx: tool.mkdir(parents=True, exist_ok=True); nx = Path(nb.build_nx_extract(d, tool, tool / 'logs', env()))
            for p in want:
                r = subprocess.run([str(nx), str(Path(KEYS).expanduser().resolve()), '--contents', str(p)], capture_output=True, text=True, env=env())
                got[p] = [(t, int(i, 16), int(v)) for t, i, v in re.findall(r'^content (\w+) ([0-9a-f]{16}) (\d+)$', r.stdout + r.stderr, re.M)] or 'unreadable'
        except Exception as x:   # no .NET, keys that cannot open the file, a damaged file: say so; the name rules stay
            print(f'  could not read the files\' titles: {x}')
        finally: sys.path.remove(str(d / 'scripts'))
        for p, m in got.items():
            cache[key(p)] = [] if isinstance(m, str) else [f'{i:016X}' for t, i, _ in m if t in ('Application', 'Patch', 'AddOnContent')]
        TITLES_CACHE.parent.mkdir(parents=True, exist_ok=True); TITLES_CACHE.write_text(json.dumps(cache))
    for p in paths: BUILDER_IDS[p] = set(cache.get(key(p), []))


def s1_title(d):   # the Switch 1 game a dump path is, or a stop that says what to do
    base, _, ids = s1_scan(DUMP_S1)
    if base: return base
    if not ids:   # nothing in the names: nxnative's reader opens them with the player's keys
        builder_titles([p for p in DUMP_S1 if not s1_ids(p)])
        base, _, ids = s1_scan(DUMP_S1)
        if base: return base
    names = ', '.join(p.name for p in DUMP_S1[:3]) + (' …' if len(DUMP_S1) > 3 else '')
    if not ids: sys.exit(f'Hermit can\'t tell which game {names} is' + ('' if KEYS else ' (choose your prod.keys and it opens the file to find out)') + ': name the files the way dump tools do, with the title ID in brackets, '
                         'e.g. "Game [0100F2C0115B6000][v0].nsp" and "Game [0100F2C0115B6800][v458752].nsp"')
    sys.exit(f'these files are more than one game ({", ".join(ids)}): keep one game (its base game, update and DLC) per folder')


def s1_parts(files, tid):   # (base game file, update file or None, DLC files) of one Switch game, by the title IDs in their names or tickets (s1_scan)
    base_id, upd_id = int(tid, 16), int(tid, 16) | 0x800
    def ids(p): return {int(t, 16) for t in s1_ids(p)}
    base = [p for p in files if base_id in ids(p) or (p.suffix.lower() in ('.xci', '.xcz') and ids(p) and all(i & ~0x1FFF == base_id for i in ids(p)))]   # a card image's game needs no
    # ticket: one that names only this game's titles (its update's ticket, say) is the base game
    upd = [p for p in files if upd_id in ids(p) and p not in base]
    dlc = [p for p in files if p not in base and p not in upd and (not ids(p) or any(base_id + 0x1000 <= i < base_id + 0x2000 for i in ids(p)))]   # this game's DLC (another game's files on a cartridge stay out)
    if not base: sys.exit(f'no base game file of {tid} among {", ".join(p.name for p in files)}: the base game must be there too')
    if len(base) > 1: base.sort(key=lambda p: p.suffix.lower() != '.xci')   # a card image first: it may carry its own update
    if len(upd) > 1: upd.sort(key=lambda p: max(map(int, re.findall(r'\[v(\d+)\]', p.name) or ['0'])), reverse=True)
    return base[0], (upd[0] if upd and not S1_NO_UPDATE else None), dlc


def find_firmware(keys):   # the player's unpacked firmware kept near their prod.keys ("Keys/prod.keys" beside "Firmware/", 50 or more .nca files), for builders that need the system fonts;
    # only its path goes to the builder, as with the keys. None when there is none
    if not keys: return None
    k = Path(keys).expanduser().resolve()
    for root in (k.parent, k.parent.parent):
        try: dirs = [root] + [d for d in root.iterdir() if d.is_dir()]
        except OSError: continue
        for d in sorted(dirs, key=lambda d: 'firmware' not in d.name.lower()):
            try:
                if sum(1 for f in d.iterdir() if f.name.lower().endswith('.nca')) >= 50: return d
            except OSError: pass
    return None


def check_keys(path):   # a quick look at a prod.keys file by its key NAMES only (no value is used): (ok, what to tell the player). The builder makes the real check when it opens the game
    p = Path(path).expanduser()
    try: text = p.read_text(errors='replace')
    except OSError: return False, f'The keys file can\'t be read: {p.name}'
    names = {l.split('=', 1)[0].strip().lower() for l in text.splitlines() if '=' in l}
    if 'header_key' not in names: return False, f'{p.name} has no header_key: it isn\'t a prod.keys file from a Switch, or it is cut short. Dump it from your Switch again'
    masters = sorted(int(n[len('master_key_'):], 16) for n in names if re.fullmatch(r'master_key_[0-9a-f]{2}', n))
    if not masters: return False, f'{p.name} has no master keys: dump prod.keys from your Switch again'
    return True, f'prod.keys with master keys up to {masters[-1]:02x} (the builder checks they open this game when the build starts)'


def version_name(g, v):   # an update version as players know it ("1.8.0") when a build of the game names it ("... (update 1.8.0)" with versions v<v>), else v<number>
    for b in builds(g) if g else []:
        if f'v{v}' in b.get('versions', []):
            m = re.search(r'update (\d+(?:\.\d+)+)', b.get('name', ''))
            if m: return m[1]
    return f'v{v}'


def dump_version(d):   # the dump's game version as the profiles name it: "v<update>" for the newest update folder (updates/<number>/), "v0" with no update, None when it cannot tell
    if read_dump(d): return f'v{nup_scan(DUMP_NUP)[1]}'
    if DUMP_S1: return f'v{s1_scan(DUMP_S1)[1]}'
    d = Path(d).expanduser().resolve(); u = update_dirs(d)
    if not u: return 'v0'
    return f'v{u[0].parent.name}' if u[0].parent.name.isdigit() else None


def title_id(npdm):
    npdm = npdm.read_bytes()
    aci = struct.unpack_from('<I', npdm, 0x70)[0]   # ACI0 offset in the META header
    return f'{struct.unpack_from("<Q", npdm, aci + 0x10)[0]:016X}'


def dump_title(d):   # the title ID from exefs/main.npdm or base/exefs/main.npdm, whatever else the folder holds (updates/, dlc/); a .nup's from its own main.npdm
    if read_dump(d): return nup_scan(DUMP_NUP)[0]
    if DUMP_S1: return s1_title(d)
    d = Path(d).expanduser().resolve()
    for base in (d, d / 'base'):
        if (base / 'exefs/main.npdm').is_file(): return title_id(base / 'exefs/main.npdm')
    sys.exit(f'no exefs/main.npdm in {d} (or in {d}/base), and no Switch 1 game file (.nsp, .nsz, .xci, .xcz)')


def title_and_build(exefs):
    sys.path.insert(0, str(NX / 'dm/tools')); import nso
    return title_id(exefs / 'main.npdm'), nso.read(exefs / 'main').build_id[:16].hex()


def own_engine(g): return g.get('engine', {}).get('kind') == 'switch2mac'   # built step by step here (Mario Kart World), not by another builder


def use_engine(g):   # Hermit's engine at the commit the game pins, fetched once: every step below reads it through NX
    global NX
    NX = engine_dir(g)
    return NX


def engine_dir(g):   # the game's engine at its pinned commit (game.json "engine": upstream nxnative or pokopia-native), fetched once: that commit only, no history
    eng = g['engine']; d = ENGINES / f'{eng["kind"]}-{eng["commit"][:12]}'
    if (d / '.git').is_dir() and not d.with_name(d.name + '.part').exists(): return d
    say(f'engine: {eng["kind"]} {eng["commit"][:12]} from {eng["repo"]} (once)')
    tmp = d.with_name(d.name + '.part'); shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    for c in (['init', '-q'], ['remote', 'add', 'origin', eng['repo']], ['fetch', '-q', '--depth', '1', 'origin', eng['commit']], ['checkout', '-q', 'FETCH_HEAD']): run(['git', '-C', tmp] + c)
    tmp.rename(d)
    return d


def unused_engines():   # engine copies no game's build pins any more (each 0.5-0.7 GB; a new one comes with most updates) and downloads cut short. A copy whose checkout is
    # not the commit its name says (one moved by hand, a maintainer's test engine) is left alone; the next build of a game fetches its pin again
    pins = set()
    for p in (ROOT / 'games').glob('*/game.json'):
        try: g = json.loads(p.read_text())
        except ValueError: continue
        for e in [g.get('engine')] + [b.get('engine') for b in g.get('builds', [])] + list((g.get('wip') or {}).values()):
            if isinstance(e, dict) and e.get('kind') and e.get('commit'): pins.add(f'{e["kind"]}-{e["commit"][:12]}')
    out = []
    for d in sorted(ENGINES.glob('*-*')) if ENGINES.is_dir() else []:
        if d.name.endswith('.part'):
            if time.time() - d.stat().st_mtime > 86400: out.append(d)   # a download stopped more than a day ago (a running one is fresh)
            continue
        if d.name in pins or not (d / '.git').is_dir(): continue
        head = subprocess.run(['git', '-C', d, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        if head and d.name.endswith(head[:12]): out.append(d)
    return out


def disk_bytes(path):   # bytes the folder takes on disk (allocated blocks; APFS clones shared with an installed app count in both, so freeing can give less)
    total = 0
    for root, dirs, files in os.walk(path):
        for f in files + dirs:
            try: total += os.lstat(os.path.join(root, f)).st_blocks * 512
            except OSError: pass
    return total


def prune_engines():   # after a build
    freed = 0
    for d in unused_engines(): freed += disk_bytes(d); shutil.rmtree(d, ignore_errors=True)
    if freed: print(f'  removed engine copies no build uses any more: {freed / 1e9:.1f} GB freed')


BULKY = ('extract', 'extract.partial', 'nsp', 'tmp', 'aoc', 'aoc.partial', 'ipa', 'xcode', 'switch-files', 'out')   # in a build folder (or nxnative's <title ID> folder in it)


def trim_build(w, tid, g):   # after an install: the game unpacked (tens of GB), converted files, temporary files and the build's engine download. The app is whole without them,
    # and a rebuild makes them again in minutes; the shader caches (the hours of a build), logs and stage times stay. Not for MacNativeGames (its apps name their builder's
    # folders), nor with HERMIT_KEEP_BUILD=1 (a maintainer who runs or refreshes builds from the folder)
    if g['engine'].get('kind') == 'macnativegames' or os.environ.get('HERMIT_KEEP_BUILD'): return
    gone = [d for base in (w, w / tid) for d in [base / n for n in BULKY] + sorted(base.glob('patched_*')) if d.is_dir()]
    eng = ENGINES / f'{g["engine"].get("kind")}-{(g["engine"].get("commit") or "")[:12]}'
    if g['engine'].get('commit') and (eng / '.git').is_dir():
        head = subprocess.run(['git', '-C', eng, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        if head and eng.name.endswith(head[:12]):   # one Hermit fetched (a copy moved by hand is left alone)
            if g['engine'].get('kind') == 'nxnative': engine_seen(g['engine']['commit'], tid)   # noted first: a quick try is still offered without it
            gone.append(eng)
    freed = 0
    for d in gone: freed += disk_bytes(d); shutil.rmtree(d, ignore_errors=True)
    if freed > 1e8: print(f'  removed the build files the app no longer needs: {freed / 1e9:.1f} GB freed (shader caches kept, so a rebuild stays quick)')


BUILDS = app_folder() / 'builds'   # where the app builds each game (BuildStore+Hermit.swift: builds/<title ID>)


def storage(a):   # what building leaves behind, and --clean removes it: each game's build folder (a built app is whole without it: a rebuild only takes longer)
    # and engine copies no build uses. Never: the games, their saves and settings, the shader caches the games keep themselves, the dumps and keys
    items = []
    for d in sorted(Path(x).expanduser() for x in (a.builds or [str(BUILDS)])):
        for w in sorted(d.iterdir()) if d.is_dir() else []:
            if not w.is_dir(): continue
            tid = w.name.upper(); name = GAMES[tid]['name'] if tid in GAMES else (w / 'title.txt').read_text().strip() if (w / 'title.txt').exists() else w.name
            items.append({'kind': 'build', 'id': tid, 'name': name, 'path': str(w), 'bytes': disk_bytes(w)})
    for d in unused_engines():
        items.append({'kind': 'engine', 'id': d.name, 'name': d.name, 'path': str(d), 'bytes': disk_bytes(d)})
    if a.clean:
        freed = 0
        for i in items:
            shutil.rmtree(i['path'], ignore_errors=True)
            if not Path(i['path']).exists(): freed += i['bytes']; i['removed'] = True
        if a.json: print(json.dumps({'items': items, 'freed': freed}))
        else: print(f'removed {sum(1 for i in items if i.get("removed"))} of {len(items)}: {freed / 1e9:.1f} GB freed')
        return
    if a.json: print(json.dumps({'items': items, 'total': sum(i['bytes'] for i in items)})); return
    for i in items: print(f'{i["bytes"] / 1e9:7.1f} GB  {"build files" if i["kind"] == "build" else "unused engine"}: {i["name"]}  ({i["path"]})')
    print(f'{sum(i["bytes"] for i in items) / 1e9:7.1f} GB in all; ./hermit.py storage --clean removes it')


# Every engine game is built as Mario Kart World is: the game starts at once (DM_LAUNCHER=0 in the app's switches: no settings window first, the saved choices apply),
# with the performance overlay top right (key 1) and the engine's own launch settings on key 2 in the Mario Kart style (tools/engine/patch.py adds them to the engine's host)
# S2M_ENGINE names the engine in the shader list contribution the app writes, so a game's list only ever takes rows from its own build (tools/shader_list.py)
S2M_LAUNCHER = ROOT / 'tools/engine/s2m_launcher.swift'
def launcher_window(nx):   # Hermit's "Ready to play" window in place of nxnative's settings window (dm/mac/Launcher.swift), shown when a game is opened outside Hermit
    """Hermit's own Play starts games with DM_LAUNCHER=0 (its sheet is the window there), so the game's window shows only from Finder, the Dock or Spotlight. An engine
    whose launcher model lacks what the window reads keeps nxnative's own window: a build never fails over this."""
    lw, model = Path(nx) / 'dm/mac/Launcher.swift', Path(nx) / 'dm/ios/Sources/LauncherSettings.swift'
    if not lw.is_file() or not model.is_file(): return
    m = model.read_text(errors='replace')
    need = ('struct SettingsFile', 'func sections(basic: Bool)', 'func rows(in section: String, basic: Bool)', 'func rangeLabel', 'var changed', 'func reset()', 'func apply()', 'let fixed: Set<String>', 'var basic: Bool', 'var onValue')
    if not all(k in m for k in need) or 'dm_mac_launcher' not in lw.read_text(errors='replace'):
        print("  settings window: nxnative's own (this engine's launcher model is older than Hermit's window needs)"); return
    src = launcher_source()
    if lw.read_bytes() != src: lw.write_bytes(src); print("  settings window: Hermit's Ready to play")


S2M_FONT = ROOT / 'app/fonts/Manrope.ttf'   # Hermit's interface face (SIL OFL 1.1, app/fonts/Manrope-OFL.txt)
def launcher_source():   # the window's source with Manrope written into its empty `let s2mManrope = ""` line (the system face when the font is missing)
    src = S2M_LAUNCHER.read_text()
    if S2M_FONT.is_file():
        src = src.replace('let s2mManrope = ""', 'let s2mManrope = "' + base64.b64encode(S2M_FONT.read_bytes()).decode() + '"', 1)
    return src.encode()


def app_switches(g):   # an untested build says so in the overlay (S2M_ENGINE=<kind>-untested); a build's own "switches" in game.json follow (a port's recommended settings)
    b = g.get('build', {}); label = b.get('name', '') if not b.get('untested') else ''
    return '\n'.join([f'S2M_ENGINE={g["engine"]["kind"]}-' + ('untested' if b.get('untested') else g["engine"]["commit"][:12])]
                     + ([f'S2M_BUILD={label}'] if re.fullmatch(r"[\w' .()-]{1,40}", label or '') else []) + b.get('switches', []))   # S2M_BUILD: the build's name for the overlay ("azmasm's build"); S2M_ENGINE stays <kind>-<commit> (the app matches builds by it)


def mng_args(args, vals):   # a MacNativeGames port's command line from game.json: "--flag?" "{value}" is the pair only when the value is there,
    """"{value}" alone is required, and "{value}" inside a word ("VERSION={version}") is put in place. Values are paths or words; a missing one
    stops the build with its name (a mistake in game.json, not the player's)."""
    out, args = [], list(args)
    while args:
        x = args.pop(0)
        if x.startswith('{') and x.endswith('*}'): out += list(vals.get(x[1:-2]) or [])   # "{dlc*}": every file of a list, none when empty
        elif x.startswith('{') and x.endswith('}?'):   # "{update}?": a value given only when there is one
            if vals.get(x[1:-2]): out.append(vals[x[1:-2]])
        elif x.endswith('?'):
            v = vals.get(args.pop(0)[1:-1])
            if v: out += [x[:-1], v]
        elif x.startswith('{') and x.endswith('}') and x.count('{') == 1:
            if vals.get(x[1:-1]) is None: sys.exit(f'game.json: the port\'s command needs {x}, which this build has no value for')
            out.append(vals[x[1:-1]])
        elif '{' in x:
            names = re.findall(r'\{(\w+)\}', x)
            missing = [n for n in names if vals.get(n) is None]
            if missing: sys.exit(f'game.json: the port\'s command needs {", ".join("{" + n + "}" for n in missing)}, which this build has no value for')
            out.append(re.sub(r'\{(\w+)\}', lambda m: str(vals[m[1]]), x))
        else: out.append(x)
    return out


MNG_LABEL = (r'@(TOTK_UI("版本 %s\n","build %s\n")),commit]', r'@"%s\n","MacNativeGames"]')
def mng_label(d):   # the grey build line of MacNativeGames' overlay says "MacNativeGames" (as Hermit's overlay names each build), not the commit.
    """Only that line's text changes: the app still records the commit (Info.plist MNGSourceCommit), which MacNativeGames' own update check,
    shader lists and reports use, and its settings panel still shows it. A port whose overlay has no such line is left as it is."""
    for f in Path(d).glob('games/*/runtime/frontend.m'):
        t = f.read_text(encoding='utf-8')
        if MNG_LABEL[0] in t: f.write_text(t.replace(MNG_LABEL[0], MNG_LABEL[1]), encoding='utf-8')


def app_file(g):   # the built app's file name: the game's name, with ": " as " - " (Finder shows a ":" in a file name as "/")
    return g['name'].replace(':', ' -') + '.app'


def mng_fixes(app, fixes, sign=True):   # game.json build "fixes": small code fixes Hermit adds to a MacNativeGames app after its builder, until MacNativeGames has them
    """Each fix names the game version it is for (its version folder and main's build ID), the bytes to find in that version's rewritten code and
    what they become. It is applied only where those bytes are found exactly once; bytes already as the fix makes them mean MacNativeGames fixed it
    (nothing to do); anything else leaves the app as it is, with a note. The app checks its code against a SHA-256 in runtime-tables.bin: that entry
    is moved to the new code's. Then the app is signed again (ad hoc, as the builder signs it). Returns the ids applied."""
    res, done = Path(app) / 'Contents/Resources', []
    game = next((x for x in res.iterdir() if (x / 'rewritten').is_dir()), None) if res.is_dir() else None
    for f in fixes:
        v = f['version_dir']; bid = game / f'extracted/{v}/exefs/main.build-id' if game else None
        if not bid or not bid.exists() or bid.read_text().strip().upper() != f['build_id'].upper(): continue   # not this game version
        code, table = game / f['file'].format(v=v), game / f['table'].format(v=v)
        old, new = bytes.fromhex(f['find']), bytes.fromhex(f['replace'])
        data = code.read_bytes()
        at = int(f['at'], 16) if f.get('at') else None   # where the bytes are in the version Hermit checked (the fix's own bytes may appear elsewhere too)
        if data.count(old) != 1:
            fixed = at is not None and data[at:at + len(new)] == new
            print(f'  fix {f["id"]}: ' + ('already in MacNativeGames\' build, nothing to add' if fixed else 'its code is not where Hermit knows it: not applied (the build is unchanged)'))
            continue
        t = table.read_bytes(); h0 = hashlib.sha256(data).hexdigest().encode()
        if t.count(h0) != 1: print(f'  fix {f["id"]}: the app\'s check of its code is not the one Hermit knows: not applied'); continue
        data = data.replace(old, new); t = t.replace(h0, hashlib.sha256(data).hexdigest().encode())
        for p, d in ((code, data), (table, t)):   # a new file moved over the old one (never written in place)
            tmp = p.with_name(p.name + '.s2m'); tmp.write_bytes(d); os.replace(tmp, p)
        done.append(f['id']); print(f'  fix {f["id"]}: {f["what"]}')
    if done and sign: run(['codesign', '--force', '--sign', '-', app])
    return done


def engine_build(a, tid, w, e):   # a game on another engine: its own builder does it all (game files, code, shaders, host, app), checking the version itself
    g = GAMES[tid]; eng = g['engine']; d = engine_dir(g); dump = Path(a.dump).expanduser().resolve()
    if sys.version_info < (3, 12): sys.exit(f'{eng["kind"]}\'s builder needs Python 3.12 or later: make .venv again with a newer python3 (./hermit.py setup)')
    print(f'  {g["name"]} ({tid}): built with {eng["kind"]} {eng["commit"][:12]}')
    e = {k: v for k, v in e.items() if k != 'DMSH_BORDER_EMU'}   # Mario Kart World's translator setting, not this engine's
    w.mkdir(parents=True, exist_ok=True); app = w / app_file(g)
    untested = g['build'].get('untested')
    if untested: print(f'  UNTESTED: {g["name"]} on {KINDS[eng["kind"]]}, with a profile it guesses from the game\'s files. It may stop partway or not start.')
    if getattr(a, 'quick', False):
        if eng['kind'] != 'nxnative': sys.exit(f'--quick is for builds on nxnative\'s builder; {g["name"]} is built with {KINDS[eng["kind"]]}')
        if not quick_ok(dict(g, title_id=tid), g['build']): sys.exit(f'{g["name"]}: no list of the shaders players used yet, so a quick try has nothing to build from: build it whole (without --quick)')
        seen = w / 'quick-shaders.tsv'; ship_list(tid, seen); e = dict(e, S2M_SEEN=str(seen))   # the game's shared list joins the profile's shader_seen.tsv (tools/engine/patch.py teaches the builder S2M_SEEN)
        print('  QUICK TRY: only the shaders players have used (the game\'s shared shader list, its profile\'s playtests and what your last runs reported missing): about half the time. Places nobody has played yet may miss parts until a full build')
    if eng['kind'] == 'nxnative' or (untested and eng['kind'] == 'pokopia-native'):
        nx = d
        P.plan(2); P.stage('engine', f'{eng["kind"]} {eng["commit"][:12]} with Hermit\'s overlay and settings')
        if eng['kind'] == 'pokopia-native':   # its nxnative tree, patched with xFractals' Switch 2 changes: nxnative's own builder, which guesses a profile for any game
            run([py(), d / 'nxs2.py', 'setup', '--no-ios'], env=e, cwd=d); nx = d / 'nxnative'; e = dict(e, NXNATIVE=str(nx))
        run([py(), ROOT / 'tools/engine/patch.py', nx], env=e); launcher_window(nx)
        if not untested:
            seed = w / f'{tid}-engine-seed.tsv'   # the engine's own seed list at its pinned commit, then the game's shared list after it
            seed.write_text(subprocess.run(['git', '-C', nx, 'show', f'HEAD:dm/games/{tid}/pso_manifest.tsv'], capture_output=True, text=True).stdout)
            ship_list(tid, nx / f'dm/games/{tid}/pso_manifest.tsv', seed)
        sw = w / 'app_switches.txt'; sw.write_text(app_switches(g) + '\n')
        P.end()
        s1 = []
        if DUMP_S1:   # nxnative's builder reads a folder of one game's files: links to this game's base, update and DLC only (its folder may hold other games)
            base, upd, dlc = s1_parts(DUMP_S1, tid)
            dump = w / 'switch-files' / tid
            if dump.exists(): shutil.rmtree(dump)
            dump.mkdir(parents=True)
            for f in [base] + ([upd] if upd else []) + dlc: (dump / f.name).symlink_to(f)
            print(f'  base {base.name}' + (f', update {upd.name}' if upd else '') + (f', {len(dlc)} DLC' if dlc else ''))
            s1 = ['--title-id', tid]
        run([py(), nx / 'scripts/build_ipa_from_nsp.py', dump, '--platform', 'mac-app', '--allow-other-metal', '--env-file', sw,
             '--work-dir', w / tid, '-o', app, '--progress', 'json' if P.json else 'lines'] + (['-k', Path(a.keys).expanduser().resolve()] if DUMP_S1 else [])
            + (['--seen-shaders'] if getattr(a, 'quick', False) else []) + s1
            + eng.get('args', []), env=e, cwd=nx, shift=P.k if P.json else None)
    elif eng['kind'] == 'macnativegames':   # MacNativeGames (ly05010419, MIT): its own runtime and builder (build_app.py) for Tears of the Kingdom and Breath of the Wild
        if not DUMP_S1: sys.exit(f'{g["name"]}: MacNativeGames builds from the game\'s .xci / .nsp files with your prod.keys')
        py314 = shutil.which('python3.14') or next((p for p in ('/opt/homebrew/bin/python3.14', '/usr/local/bin/python3.14') if Path(p).exists()), None)
        miss = [] if py314 else ['python@3.14']
        miss += [f for f in ('opus', 'libvpx') if not any(Path(r, 'opt', f).exists() for r in ('/opt/homebrew', '/usr/local'))]
        if miss:   # installed here when Homebrew is there (the player pressed Build for this game): no Terminal needed
            brew = shutil.which('brew') or next((b for b in ('/opt/homebrew/bin/brew', '/usr/local/bin/brew') if Path(b).exists()), None)
            if not brew: sys.exit(f'MacNativeGames\' builds need {", ".join(miss)} from Homebrew, and Homebrew is not installed: install it from https://brew.sh (it asks for your password once), then press Build again')
            P.step(f'installing what MacNativeGames\' builder needs, with Homebrew: {", ".join(miss)} (once, a few minutes)')
            run([brew, 'install'] + miss, env=dict(e, HOMEBREW_NO_AUTO_UPDATE='1', HOMEBREW_NO_INSTALL_CLEANUP='1', NONINTERACTIVE='1'))
            py314 = shutil.which('python3.14') or next((p for p in ('/opt/homebrew/bin/python3.14', '/usr/local/bin/python3.14') if Path(p).exists()), None)
            if not py314: sys.exit('Homebrew installed python@3.14, but python3.14 is not where it should be: open Terminal and run brew doctor')
        base, upd, dlc = s1_parts(DUMP_S1, tid)
        fw = Path(a.firmware).expanduser().resolve() if getattr(a, 'firmware', None) else None if getattr(a, 'shared_fonts', None) else find_firmware(a.keys)
        if fw and not getattr(a, 'firmware', None): print(f'  using the firmware beside your prod.keys for the system fonts: {fw.name}'); HIDE[str(fw)] = '<your firmware>'
        fonts = (['--firmware', fw] if fw else ['--shared-fonts', Path(a.shared_fonts).expanduser().resolve()] if getattr(a, 'shared_fonts', None) else [])
        if not fonts and not eng.get('builder') and (base.suffix.lower() in ('.nsp', '.nsz') or tid == '01007EF00011E000'):
            print('  NOTE: from an .nsp, and always for Breath of the Wild, MacNativeGames needs the Switch\'s system fonts: --firmware <your firmware dump> or --shared-fonts <a TotK build\'s fonts>')
        print(f'  base {base.name}' + (f', update {upd.name}' if upd else '') + (f', {len(dlc)} DLC' if dlc else ''))
        mng_label(d)
        P.plan(P.k + 4); P.order = list(MNG_STEPS)   # its four steps as our stages, so the bar and the time left follow them (mng_watch)
        P.stage('game code', 'MacNativeGames\' builder: the game\'s code for Apple silicon')
        b = eng.get('builder')
        if b:   # a community port with its own builder script (games/<port>/...): game.json names it and its arguments, as that port's README gives them
            m = re.search(r'v(\d{5,})', upd.name) if upd and b.get('updates') else None
            if m and f'v{m[1]}' not in b['updates']:   # an update the port cannot run (Wonder's port: 1.2.1 only): built without it
                print(f'  NOTE: this port takes only update {", ".join(b["updates"])}; {upd.name} is left out (the base game is built)'); upd = None
            vals = {'base': base, 'update': upd, 'keys': Path(a.keys).expanduser().resolve(), 'app': app, 'work': w / tid,
                    'firmware': Path(a.firmware).expanduser().resolve() if getattr(a, 'firmware', None) else find_firmware(a.keys),
                    'shared_fonts': Path(a.shared_fonts).expanduser().resolve() if getattr(a, 'shared_fonts', None) else None}
            if vals['firmware']: HIDE[str(vals['firmware'])] = '<your firmware>'
            for need in b.get('needs', []):
                if not vals.get(need) and not (need == 'firmware' and vals['shared_fonts'] and '{shared_fonts}' in json.dumps(b)): sys.exit(f'{g["name"]}: MacNativeGames\' port needs ' + {'update': 'the game\'s update file (' + b.get('update_note', 'see its README') + ') next to the base game',
                                                                                              'firmware': 'the Switch\'s system fonts: --firmware <your unpacked firmware dump>' + (' or --shared-fonts <a TotK build\'s fonts>' if '{shared_fonts}' in json.dumps(b) else ' (in the app: Firmware on the Build page)')}.get(need, need))
            runner = py314
            if b.get('pip'):   # the port's own Python packages (its requirements.txt), in a Python 3.14 environment of this game's build folder
                venv = w / tid / 'mng-venv'
                if not (venv / 'bin/python').exists():
                    P.step('a Python environment for MacNativeGames\' port (once)')
                    (w / tid).mkdir(parents=True, exist_ok=True); run([py314, '-m', 'venv', venv])
                run([venv / 'bin/python', '-m', 'pip', 'install', '-q', '--disable-pip-version-check'] + b['pip'])
                runner = venv / 'bin/python'
            vals['py'] = runner
            if 'version_dirs' in b:   # the port's own name for the game version it builds (Xenoblade 3: v100, v221), by the update's number
                m = re.search(r'v(\d{5,})', upd.name) if upd else None
                key = f'v{m[1]}' if m else ('' if not upd else None)
                if key not in b['version_dirs']: sys.exit(f'{g["name"]}: MacNativeGames\' port plays {plays_text(g["build"])}; {upd.name if upd else "the base game"} is not one of them')
                vals['version'] = b['version_dirs'][key]
            if b.get('script'):
                cmd = mng_args(b['args'], vals)
                if 'dlc' in b and dlc: cmd += [z for f in dlc for z in (b['dlc'], f)]
                print(f'  MacNativeGames port: {b["script"]}')
                run([runner, d / b['script']] + cmd + eng.get('args', []), env=e, cwd=d / b.get('cwd', ''), watch=mng_watch)
            else:   # a port built in several steps (its README's commands, in order), each a command line with the same {values}
                stages = list(dict.fromkeys(s['stage'] for s in b['steps']))
                P.plan(P.k - 1 + len(stages)); P.order = stages
                for x in b.get('fresh', []):   # folders the steps make and refuse to find already there: a rebuild starts them again
                    p = Path(mng_args([x], vals)[0])
                    if p.exists(): shutil.rmtree(p)
                vals['dlc'] = dlc
                for s in b['steps']:
                    if {'update': not upd, 'no_update': bool(upd), 'dlc': not (upd and dlc)}.get(s.get('when'), False): continue
                    if s['stage'] != P.name: P.stage(s['stage'], s.get('what', ''))
                    for item in s.get('each', [None]):
                        cmd = mng_args(s['cmd'], dict(vals, item=item))
                        run(cmd, env=dict(e, **s.get('env', {})), cwd=d / b.get('cwd', ''))
            if b.get('app_out'):   # where the port leaves its app, when it cannot be told where to put it
                out = Path(mng_args([b['app_out']], vals)[0])
                if not out.is_dir(): sys.exit(f'{g["name"]}: MacNativeGames\' port finished without making {out.name}')
                if app.exists(): shutil.rmtree(app)
                shutil.move(str(out), app)
        else:
            run([py314, d / 'build_app.py', base] + (['--update', upd] if upd else []) + [x for f in dlc for x in ('--dlc', f)]
                + ['-k', Path(a.keys).expanduser().resolve(), '-o', app, '--work', w / tid] + fonts + eng.get('args', []), env=e, cwd=d, watch=mng_watch)
        mng_fixes(app, g['build'].get('fixes', []))   # Hermit's fixes for this build, on any MacNativeGames commit (game.json "fixes")
    elif DUMP_S1: sys.exit(f'{g["name"]}: {KINDS[eng["kind"]]} builds Switch 2 games only')
    elif eng['kind'] == 'pokopia-native':
        nx = d / 'nxnative'; e = dict(e, NXNATIVE=str(nx)); P.plan(4)
        P.stage('engine', f'pokopia-native {eng["commit"][:12]} with Hermit\'s overlay and settings')
        run([py(), d / 'nxs2.py', 'setup', '--no-ios'], env=e, cwd=d)   # nxnative at its pinned commit with pokopia-native's Switch 2 patch, and its shader lowering
        run([py(), ROOT / 'tools/engine/patch.py', nx], env=e); launcher_window(nx)
        ship_list(tid, d / f'profile/{tid}/pso_manifest.tsv')   # pokopia-native ships no list of its own: the game's shared list is the app's
        script = d / 'nxs2.py'; t = script.read_text()   # once: its app's baked switches (APP_ENV) get Hermit's, and its profile step copies the list
        if 'S2M_ENGINE=' not in t:
            k = "DM_NVN_SHDUMP=shdump\\n'\n"
            if t.count(k) != 1: sys.exit(f'{script}: its APP_ENV line is not the one Hermit knows')
            t = t.replace(k, k[:-2] + app_switches(g).replace('\n', '\\n') + "\\n'   # (switch2mac)\n", 1)
        if "'shader_facts.seed.tsv', 'pso_manifest.tsv')" not in t:
            k = "'shader_facts.seed.tsv'):"
            if t.count(k) != 1: sys.exit(f'{script}: its profile step is not the one Hermit knows')
            t = t.replace(k, "'shader_facts.seed.tsv', 'pso_manifest.tsv'):", 1)
        script.write_text(t)
        P.stage('build', 'game files, code, shaders (the long step) and host, by pokopia-native')
        run([py(), script, 'build', dump, '--out', w / tid, '--mac-app', '--no-ios'], env=e, cwd=d)
        P.stage('app')
        if app.exists(): shutil.rmtree(app)
        shutil.move(str(w / tid / 'out' / f'{g["name"]}.app'), app)
    else: sys.exit(f'{g["name"]}: engine kind {eng["kind"]!r} is not one Hermit builds with')
    (w / 'title.txt').write_text(tid + '\n'); (w / 'build.txt').write_text(g['build']['id'] + '\n')
    P.end(summary=str(app))
    print(f'\nbuilt: {app}\n./hermit.py install moves it to /Applications.')


def profile_builds(tid):   # main build ID → version name, from the profile's build lines
    rows = [l.split('\t') for l in (profile_src(tid) / 'game.tsv').read_text().splitlines() if l.startswith('build\t')]
    return {c.split('=', 1)[1]: r[2] for r in rows for c in r[3:] if c.startswith('main=')}


def check_version(tid, bid):
    if tid not in GAMES: sys.exit(f'title {tid} is not supported yet (this repository has: {", ".join(g["name"] + " " + t for t, g in GAMES.items())}).\n'
                                  'Adding a game: docs/porting.md')
    rows = [l.split('\t') for l in (profile_src(tid) / 'game.tsv').read_text().splitlines() if l.startswith('build\t')]
    known = {c.split('=', 1)[1]: r[2] for r in rows for c in r[3:] if c.startswith('main=')}
    if bid in known:
        print(f'  {GAMES[tid]["name"]} {known[bid]} (main {bid}): tested')
        return
    sys.exit(f'main build ID {bid} is not a version this profile knows ({", ".join(known.values())}).\n'
             f'This version is UNTESTED: its build line (game.tsv) and module list must be added first (see {GAMES[tid]["dir"].relative_to(ROOT) if GAMES[tid].get("dir") else "docs/porting.md"}/README.md, "Other versions").')


def stage(romfs, out):   # a symlink tree of the RomFS without the dump tool's dot-files, so they never end up in the image
    if out.exists(): shutil.rmtree(out)
    n = 0
    for root, _, files in os.walk(romfs):
        rel = Path(root).relative_to(romfs); (out / rel).mkdir(parents=True, exist_ok=True)
        for f in files:
            if f in SKIP: continue
            os.symlink(Path(root) / f, out / rel / f); n += 1
    print(f'  {n:,} game files linked')


def paths(a):
    w = Path(a.work).resolve()
    return w, w / 'extract', w / 'build', w / 'shader', w / 'cache/metal_shader_cache'


def profile(w, tid):   # a fresh copy of the repo's profile in work/profile: the shader split rewrites its tables, the repo stays as it is
    prof = w / 'profile' / tid
    if prof.exists(): shutil.rmtree(prof)
    shutil.copytree(profile_src(tid), prof)
    if not PROFILE: ship_list(tid, prof / 'pso_manifest.tsv')   # an untested build has no shared list (keys differ between engines)
    return prof


def ship_list(tid, out, base=None):   # the build's shared shader list (games/<game>/shader_list.tsv, or the build's own) as the pso_manifest.tsv its app ships, after the engine's own rows when it has some
    b = GAMES[tid].get('build')
    run([py(), ROOT / 'tools/shader_list.py', 'ship', tid, out] + (['--base', base] if base else []) + (['--build', b['id']] if b else []))


def runtime_shaders(tid, w):
    """Shaders the game assembles while it runs are not in its usual shader containers, but their parts are in its files. games/<game>/runtime_shaders.tsv says where each
    one's control section and code are (file + offset, as positions only: no game data), and its key, sha256(control + code), checks what is read. They go to work/runtime
    as <key>.ctl / <key>.code, the way the app saves shaders it meets (refresh), so the first launch already has them."""
    import zstandard
    table = GAMES[tid]['dir'] / 'runtime_shaders.tsv' if GAMES[tid].get('dir') else ROOT / 'games/none'
    out = w / 'runtime'; out.mkdir(exist_ok=True)
    if not table.exists(): return None
    rows = [l.rstrip('\n').split('\t') for l in table.open() if l.strip() and not l.startswith('#')]
    blobs, bad = {}, 0
    def blob(name):
        if name not in blobs:
            if name == 'main': blobs[name] = (w / 'shader/main.img').read_bytes()
            else:
                b = (w / 'input/romfs' / name).read_bytes()
                blobs[name] = zstandard.ZstdDecompressor().stream_reader(b).read(1 << 31) if name.endswith('.zs') else b
        return blobs[name]
    for key, cf, co, kf, ko, n in rows:
        ctl = blob(cf)[int(co, 16):int(co, 16) + 0xd8]; code = blob(kf)[int(ko, 16):int(ko, 16) + int(n)]
        if hashlib.sha256(ctl + code).hexdigest()[:16] != key: bad += 1; continue
        (out / f'{key}.ctl').write_bytes(ctl); (out / f'{key}.code').write_bytes(code)
    print(f'  {len(rows) - bad} of {len(rows)} run-time shaders taken from the dump' + (f' ({bad} did not match: another game version?)' if bad else ''))
    return out


def shaders(a, tid, w, sh, cache, e):
    prof = profile(w, tid); tools = NX / 'dm/gfx/tools'
    e.update(DM_GAMES_DIR=str(w / 'profile'), DM_GAMES_FIRST='1')   # every tool (and the host build) takes the work copy
    lower = tools / 'nx2_lower/nx2_lower'
    if not lower.exists():
        P.step('building the shader lowering tool (nx2_lower)')
        run(['clang++', '-std=c++20', '-O2', '-w', '-Wno-c++11-narrowing', '-I.', 'nx2_lower.cpp', '-o', 'nx2_lower'], cwd=tools / 'nx2_lower')
    if (tools / 'nx2_lower/next/nx2_lower.cpp').exists() and not (tools / 'nx2_lower/next/nx2_lower_next').exists():   # the fallback lowering, for programs nx2_lower rejects (engines from 9ae37886 on)
        P.step('building the fallback shader lowering tool (nx2_lower/next)')
        run(['clang++', '-std=c++20', '-O2', '-w', '-Wno-c++11-narrowing', '-I.', 'nx2_lower.cpp', '-o', 'nx2_lower_next'], cwd=tools / 'nx2_lower/next')
    e = dict(e, DM_GAME=tid, **GAMES[tid].get('shader_env', {}))   # game.json shader_env: switches for the shader tools (Ocarina of Time: EDEN_NX2_TENSOR=1, its movie's matrix maths)
    run([py(), NX / 'dm/tools/nso.py', w / 'extract/ExeFS/main', sh / 'main.img'], env=e)
    P.stage('shader split', 'with the run-time shaders listed for this game' + (' and those the app saved while you played' if (w / 'captures').is_dir() and any((w / 'captures').iterdir()) else ''))
    rt = runtime_shaders(tid, w)
    caps = [str(p) for p in (rt, w / 'captures') if p and p.is_dir() and any(p.iterdir())]
    e = dict(e, NX2_DUMPS=':'.join(caps))
    run([py(), tools / 'nx2_split.py', w / 'input/romfs', sh / 'main.img', sh / 'pkg', prof / 'shader_map.tsv', prof / 'shader_facts.tsv', prof / 'shader_pairs.tsv', sh / 'rejects.tsv'], env=e)
    P.stage('Metal shaders', 'the long step: 10-20 minutes the first time, all cores')
    run([py(), tools / 'own_compilers.py', sh / 'pkg', cache], env=e)
    chain = re.search(r'"([0-9a-f]{12})"', (NX / 'dm/gfx/nvn/dmsh_chain.h').read_text())[1]   # the translator chain version names the library folder
    lib = cache / f'b-{chain}'
    run([py(), tools / 'nx2_res.py', prof / 'shader_map.tsv', sh / 'pkg', sh / 'pkg/cs_layout.tsv', sh / 'res'], env=e)
    run([py(), tools / 'nx2_reflect.py', lib, sh / 'pkg/cs_layout.tsv', sh / 'res'], env=e)
    return lib


def host_and_app(a, tid, w, lib, e):
    g = GAMES[tid]; prof = w / 'profile' / tid
    P.stage('host', 'the native runtime')
    run(['make', '-C', NX / 'dm/host', f'GAME={tid}', f'MACOS_MIN={macos()}', 'dmhost'], env=e)   # for this Mac's macOS, not nxnative's fixed 26.6
    font = w / 'build/font'
    if not (font / 'nintendo_ext.ttf').exists():
        font.mkdir(parents=True, exist_ok=True); run([py(), NX / 'dm/tools/make_ext_font.py', font / 'nintendo_ext.ttf'], env=e)
    P.stage('app')
    if PROFILE:   # an untested build: the generic settings, its own switches, the marker from the borrowed profile
        run([py(), ROOT / 'tools/engine/launcher_generic.py', NX, w / 'build/patched', w / 'build/launcher.json', tid], env=e)
        envf = w / 'build/env_untested.txt'; envf.write_text(f'S2M_ENGINE=switch2mac-untested\n')
        marker = next((l.split()[1] for l in (prof / 'game.tsv').read_text().splitlines() if l.startswith('romfs_marker')), '')
    else:
        run([py(), g['dir'] / 'launcher.py', NX, w / 'build/patched', w / 'build/launcher.json'], env=e)
        envf, marker = g['dir'] / 'env.txt', g['marker']
    app = w / app_file(g)
    launcher_window(NX)
    run([py(), NX / 'dm/mac/pack_app.py', app, '--host', NX / 'dm/host/dmhost', '--patched', w / 'build/patched', '--romfs', w / 'extract/RomFS.img',
         '--msl', lib, '--tables', prof, '--font', font, '--env-file', envf, '--settings', w / 'build/launcher.json', '--launcher-window', 'off',
         '--title-id', tid, '--name', g['name'], '--version', g['version'] or 'untested', '--lang', 'en-US'] + (['--marker', marker] if marker else []), env=e)
    (w / 'title.txt').write_text(tid); (w / 'build.txt').write_text(g['build']['id'] + '\n')
    P.end(summary=str(app))
    print(f'\ndone: {app}\nnext: ./hermit.py install')


def build(a):
    e = env(); w, ex, b, sh, cache = paths(a)
    if 'DOTNET_ROOT' not in e: sys.exit('.NET is missing: run ./hermit.py setup for the checks')
    P.json = getattr(a, 'progress', None) == 'json'; P.plan(7); P.history(w / 'stage_times.json')
    P.order = ['the dump', 'game files', 'code', 'shader split', 'Metal shaders', 'host', 'app']
    P.stage('the dump'); tid = dump_title(a.dump)
    if DUMP_S1:   # a Switch 1 game: its files are opened by the builder with the player's own keys, whose path goes to the builder alone
        if not getattr(a, 'keys', None): sys.exit('A Switch 1 game needs your own prod.keys, dumped from your Switch: choose it (--keys <path of prod.keys>)')
        ok, why = check_keys(a.keys)
        if not ok: sys.exit(why)
        HIDE[str(Path(a.keys).expanduser().resolve())] = '<your prod.keys>'; HIDE[str(a.keys)] = '<your prod.keys>'
        print(f'  Switch 1 game files: {len(DUMP_S1)}; {why}')
    bad = damaged_modules(a.dump)   # before anything is fetched or copied: a damaged dump stops here with what to do (the app's identify says the same)
    if bad: sys.exit(f'The dump is damaged: {", ".join(bad)} {"is" if len(bad) == 1 else "are"} cut short. Copy it off your Switch 2 again (over FTP, in binary mode).')
    if tid not in GAMES: GAMES[tid] = unknown_game(tid)   # any Switch 2 game can be tried with the untested builds
    if True:
        ver = dump_version(a.dump); GAMES[tid] = with_build(GAMES[tid], a.engine, ver); chosen = GAMES[tid]['build']   # not `b`: that is the build folder
        print(f'  {GAMES[tid]["name"]} ({tid})' + (f', {chosen["name"]}' + ('' if a.engine else f' ({recommend(GAMES[tid], this_mac(), ver)[1] or "this Mac"})') if len(builds(GAMES[tid])) > 1 else ''))
        if not fits(chosen, ver) and not (DUMP_NUP and chosen['engine']['kind'] == 'switch2mac'): print(f'  NOTE: {chosen["name"]} lists {", ".join(chosen["versions"])}, and this dump is {ver}: it may not build or start')
        if DUMP_NUP and ((not NUP_BASE and chosen.get('nup_needs_base')) or own_engine(GAMES[tid])):   # a builder that cannot read this .nup (one from before NUPs without a base
            # game, nxnative 777a5f6c, or Hermit's engine, which reads folders): Hermit reads it itself into the dump folder layout, as it reads a Switch game's .xci
            print(f'  {chosen["name"]} reads dump folders' + (' or NUPs with a base game' if not own_engine(GAMES[tid]) else '') + f': unpacking {DUMP_NUP.name} into the build folder (once; every file checked)')
            sys.path.insert(0, str(ROOT / 'tools')); import nup
            try:
                with nup.Nup(DUMP_NUP) as n: folder = nup.unpack(n, w / 'nup-dump')
            except nup.Error as x: sys.exit(f'{x}. Copy the .nup again, or extract it to a dump folder.')
            except OSError as x: sys.exit(f'Unpacking {DUMP_NUP.name} failed: {x.strerror or x} (free space? it needs about the size of the .nup)')
            a.dump = str(folder); read_dump(a.dump)
        free_space(w, GAMES[tid])
    if not own_engine(GAMES[tid]): return engine_build(a, tid, w, e)
    if DUMP_NUP: sys.exit(f'{GAMES[tid]["build"]["name"]} builds from a dump folder (exefs/ and romfs/), not a .nup: choose another build of this game, or extract the .nup to a folder first')
    if DUMP_S1: sys.exit(f'{GAMES[tid]["build"]["name"]} builds Switch 2 games only: choose another build of this game')
    use_engine(GAMES[tid])
    global PROFILE
    untested = GAMES[tid]['build'].get('untested'); PROFILE = None
    upd = update_dirs(a.dump)   # an untested build takes the update when the dump has one; a tested one when its profile knows the update's main (Ocarina of Time v131072)
    if upd and not untested and title_and_build(upd[0])[1] not in profile_builds(GAMES[tid]['title_id']): upd = None
    exefs, romfs = upd or dump_dirs(a.dump)
    if untested:
        print(f'  UNTESTED: {GAMES[tid]["name"]} on Hermit\'s engine, with a profile guessed from the game\'s files. It may stop partway or not start.')
        ver = f'v{exefs.parent.name}' if upd and exefs.parent.name.isdigit() else 'v0'
        if (NX / f'dm/games/{tid}/game.tsv').is_file(): print(f'  the engine has a profile for this game: using it, not a guess')   # an experimental game's own engine
        else:
            PROFILE = guess_profile(w, tid, exefs, romfs, ver, GAMES[tid]['name'])
            e.update(DM_GAMES_DIR=str(PROFILE.parent), DM_GAMES_FIRST='1')   # every tool reads the guessed profile
    tid, bid = title_and_build(exefs); check_version(tid, bid)
    for d in (ex / 'ExeFS', b, sh): d.mkdir(parents=True, exist_ok=True)
    P.stage('game files', 'code modules and the RomFS image (a few minutes; reused when unchanged)')
    for f in exefs.iterdir():
        if f.is_file() and f.name not in SKIP: run(['cp', '-c', f, ex / 'ExeFS' / f.name])
    stage(romfs, w / 'input/romfs')
    run([py(), NX / 'dm/tools/romfs_image.py', '--reuse', w / 'input/romfs', ex / 'RomFS.img'], env=e)
    P.stage('code', 'the game modules rewritten for the Mac')
    mods = subprocess.run([py(), NX / 'dm/games/game.py', tid, 'modules'], capture_output=True, text=True, check=True, env=e).stdout.split()
    for m in mods: run([py(), NX / 'dm/tools/patch_nso.py', ex / 'ExeFS' / m, b / 'patched', m], env=e)
    lib = shaders(a, tid, w, sh, cache, e)
    host_and_app(a, tid, w, lib, e)


def refresh(a):
    e = env(); w, ex, b, sh, cache = paths(a)
    tid = built_game(w)
    if not own_engine(GAMES[tid]): sys.exit(f'{GAMES[tid]["name"]} is built with another engine: refresh is for the games on Hermit\'s engine (build again instead)')
    if not ex.is_dir(): sys.exit("the game's unpacked files were removed after its install, to save space: build it again first (HERMIT_KEEP_BUILD=1 keeps them)")
    use_engine(GAMES[tid])
    caps = w / 'captures'; caps.mkdir(exist_ok=True); new = []
    for saved in (Path.home() / f'Library/Application Support/nxnative/{tid}/shdump', w / 'run/shdump'):   # the installed app's captures, and run's
        got = [p for p in saved.glob('*') if p.is_file() and not (caps / p.name).exists()] if saved.is_dir() else []
        for p in got: shutil.copy2(p, caps / p.name)
        print(f'{len(got)} new files from {saved}'); new += got
    print(f'{sum(1 for _ in caps.glob("*.ctl"))} shaders captured in all')
    if not new and not a.force: sys.exit('nothing new to build in (play the game a while first, or --force)')
    P.json = getattr(a, 'progress', None) == 'json'; P.plan(4); P.history(w / 'stage_times.json'); P.order = ['shader split', 'Metal shaders', 'host', 'app']
    lib = shaders(a, tid, w, sh, cache, e)
    host_and_app(a, tid, w, lib, e)


def damaged_modules(d):   # code modules (NSO) of a dump whose segments reach past the end of the file: a copy cut short, as an FTP copy in text mode leaves them
    if read_dump(d): return []   # a .nup: its size and table of contents were checked when it was read, and every file is checked against its SHA-256 as the build reads it
    if DUMP_S1: return []   # Switch 1 files: the builder checks them (NCA hashes) as it opens them
    d = Path(d).expanduser().resolve(); bad = []
    for exefs in [d / 'exefs', d / 'base/exefs'] + sorted(d.glob('updates/*/exefs')) + sorted(d.glob('updates/exefs')):
        if not exefs.is_dir(): continue
        for f in sorted(exefs.iterdir()):
            if not f.is_file() or f.name in SKIP: continue
            with f.open('rb') as h: head = h.read(0x100)
            if len(head) < 0x100 or head[:4] != b'NSO0': continue
            size = f.stat().st_size
            for i in range(3):   # text, ro, data: file offset at 0x10 + 0x10 * i, size in the file at 0x60 + 4 * i
                off = struct.unpack_from('<I', head, 0x10 + 0x10 * i)[0]; n = struct.unpack_from('<I', head, 0x60 + 4 * i)[0]
                if off + n > size: bad.append(str(f.relative_to(d))); break
    return bad


def identify(a):   # for the app: which game a dump folder is, as one JSON line (nothing is copied or built)
    out = {'ok': False, 'folder': str(Path(a.dump).expanduser())}
    try:
        tid = dump_title(a.dump); out['title_id'] = tid
    except SystemExit as x:
        out['problem'] = ('The .nup could not be read: ' if str(x).endswith('extract it to a dump folder.') else '' if DUMP_S1 else 'This isn\'t a game dump: ') + str(x); print(json.dumps(out)); return
    bad = damaged_modules(a.dump)
    if bad:
        g = GAMES.get(tid); out.update(name=g['name'] if g else '', damaged=bad,
            problem=f'The dump is damaged: {", ".join(bad)} {"is" if len(bad) == 1 else "are"} cut short. Copy it off your Switch 2 again (over FTP, in binary mode).')
        print(json.dumps(out, ensure_ascii=False)); return
    g = GAMES.get(tid) or unknown_game(tid)   # a game Hermit has no folder for: offered with the untested builds only
    mac = this_mac(); ver = dump_version(a.dump); rec, why = recommend(g, mac, ver)
    s1_update = s1_base = None   # a Switch game's update file (its name tells players' version names: "v.1.2.0") and base file
    if DUMP_S1:
        try: s1_base, s1_update = s1_parts(DUMP_S1, tid)[:2]
        except SystemExit: pass
    upd_name = next((n for b in builds(g) if (n := update_name(b, ver, s1_update))), '')   # the update's version name, from its file or any build's list
    fw = Path(a.firmware).expanduser().resolve() if getattr(a, 'firmware', None) else find_firmware(getattr(a, 'keys', None)) if DUMP_S1 else None
    if not rec: out['problem'] = f'title {tid}: no engine is set up to try it'; print(json.dumps(out)); return
    eng = with_build(g, rec)['engine']
    out.update(ok=True, name=g['name'], version=g.get('version', ''), engine=eng.get('kind', 'switch2mac'), commit=eng.get('commit', '')[:12],
               disk_gb=g.get('disk_gb'), page=f'games/{g["dir"].name}/README.md' if g.get('dir') else '', untested=not builds(g),
               mac=mac, recommended=rec, why=why, reports=reports(g), dump_version=ver, dump_form='nup' if DUMP_NUP else 'switch1' if DUMP_S1 else 'folder',
               needs_keys=bool(DUMP_S1), files=[p.name for p in DUMP_S1], firmware=str(fw) if fw else '', base_ext=Path(s1_base).suffix.lower().lstrip('.') if s1_base else '',
               update_name=upd_name, custom_problem=CUSTOM_PROBLEM,
               builds=[{'id': b['id'], 'name': b['name'], 'engine': b['engine']['kind'], 'commit': b['engine']['commit'][:12], 'about': b.get('about', ''),
                        'fits': fits(b, None) and not fit_note(b, ver, s1_update, upd_name), 'note': fit_note(b, ver, s1_update, upd_name), 'plays': plays_text(b), 'firmware': b.get('firmware', ''), 'quick': quick_ok(dict(g, title_id=tid), b)} for b in builds(g)],
               experimental=[{'id': b['id'], 'name': b['name'], 'engine': b['engine']['kind'], 'commit': b['engine']['commit'][:12], 'about': b['about']} for b in untested_builds(g)])
    if DUMP_S1 and getattr(a, 'keys', None): out['keys_ok'], out['keys_note'] = check_keys(a.keys)
    if DUMP_S1:   # what goes to the builder: the base game, its update and DLC; and the games a cartridge holds, to pick from
        try:
            base, upd, dlc = s1_parts(DUMP_S1, tid)
            out['parts'] = {'base': base.name, 'base_path': str(base), 'update': upd.name if upd else '', 'dlc': [p.name for p in dlc]}
            inside = {int(n[:16], 16) for n in inner_names(base) if re.fullmatch(r'[0-9A-Fa-f]{32}\.tik', n)}   # titles whose tickets the base game's own file carries
            if not upd and int(tid, 16) | 0x800 in inside: out['parts']['update'] = f'Inside {base.name}'
            known = {int(t, 16) for t in s1_ids(base)} | {int(tid, 16)}   # the titles its name and tickets already name (a cartridge's other game and its update too)
            extra = packages_in(base) - len(known)   # more titles in it than those: an update or DLC without a ticket
            if extra > 0: out['parts']['note'] = f'{base.name} also holds {extra} more package{"s" if extra > 1 else ""} (an update or DLC). The builder uses {"them" if extra > 1 else "it"} with the game.'
        except SystemExit: pass
        apps = s1_apps(DUMP_S1)
        if len(apps) > 1: out['games_in_files'] = [{'title_id': t, 'name': GAMES[t]['name'] if t in GAMES else ''} for t in apps]
    elif DUMP_NUP:   # what the .nup holds, from its table of contents
        sys.path.insert(0, str(ROOT / 'tools')); import nup
        try:
            with nup.Nup(DUMP_NUP) as n:
                _, base, vers, dlc = nup.scan(n)
                newest = max(vers) if vers else 0
                out['parts'] = {'base': 'Base game' if base else '', 'update': f'Update {version_name(g, newest)}, inside {DUMP_NUP.name}' if newest else '',
                                'dlc': [f'DLC {t:016X}, inside {DUMP_NUP.name}' for t in sorted(dlc)]}
                if not base and newest: out['parts']['note'] = (f'No separate base game in {DUMP_NUP.name}: its update {version_name(g, newest)} holds the whole game. '
                                                                'Hermit unpacks it for builds that need a base game.')
        except nup.Error: pass
    else:   # a Switch 2 dump folder: its updates/<version> folders
        u = update_dirs(Path(a.dump).expanduser().resolve())
        if u: out['parts'] = {'base': 'base/', 'update': f'Update {version_name(g, int(u[0].parent.name))}, in updates/{u[0].parent.name}' if u[0].parent.name.isdigit() else '', 'dlc': []}
    print(json.dumps(out, ensure_ascii=False))


def builds_cmd(a):   # the builds a game has and which one this Mac gets, for people (identify gives the same to the app)
    tid = dump_title(a.dump) if Path(a.dump).expanduser().exists() else a.dump.upper()
    g = GAMES.get(tid) or next((g for g in GAMES.values() if g['dir'].name == a.dump), None) or (unknown_game(tid) if re.fullmatch(r'[0-9A-F]{16}', tid) else None)
    if not g: sys.exit(f'{a.dump}: not a Switch 2 game dump, a title ID or a games/ folder')
    ver = dump_version(a.dump) if Path(a.dump).expanduser().exists() else None
    mac = this_mac(); rec, why = recommend(g, mac, ver); rs = reports(g)
    print(f'{g["name"]}: this Mac is an {mac["chip"]} with {mac["memory_gb"]} GB, macOS {mac["macos"]}' + (f'; the dump is {ver}' if ver else ''))
    for b in builds(g):
        print(f'\n  {"*" if b["id"] == rec else " "} {b["id"]}: {b["name"]} ({b["engine"]["kind"]} {b["engine"]["commit"][:12]})' + (f'  <- this Mac: {why}' if b['id'] == rec and why else '')
              + (f'  [plays {", ".join(b["versions"])} only]' if b.get('versions') and not fits(b, ver) else ''))
        if b.get('about'): print(f'      {b["about"]}')
        for r in rs:
            if r['build'].split()[0] == b['id']:
                print(f'      {r["mac"]} {r["chip"]}' + (f', {r["memory_gb"]} GB' if r['memory_gb'] else '') + (f': {r["fps"]} fps' if r['fps'] else '') + (f', {r["peak_gb"]} GB peak' if r['peak_gb'] else '') + f' ({r["notes"]}; {r["source"]})')
    for b in untested_builds(g):
        print(f'\n  ! {b["id"]}: {b["name"]} ({b["engine"]["kind"]} {b["engine"]["commit"][:12]})\n      {b["about"]}')
    if len(builds(g)) + len(untested_builds(g)) > 1: print(f'\n./hermit.py build <dump> builds {rec}; --engine <id> builds another.')


def switched_build(g):
    """The game's data folder notes which build is installed (s2m_build.txt). Each build keeps its own record of the pipelines it built
    (pso_user.tsv), its pipeline archive (pso_archive/) and its shader list contribution: the engines name shaders differently, and one
    build cannot read the other's archive. When the build changes, the old build's are put aside under its name and the new build's,
    if it was installed before, come back, so switching back and forth never loses what a build learned. Saves are the game's own and stay."""
    data = Path.home() / f'Library/Application Support/nxnative/{g["title_id"]}'; note = data / 's2m_build.txt'; new = g['build']['id']
    old = note.read_text().strip() if note.exists() else (builds(g)[0]['id'] if (data / 'pso_user.tsv').exists() else '')
    def aside(f, b):   # pso_user.tsv → pso_user.<build>.tsv, pso_archive → pso_archive.<build>
        return data / (f'{f.removesuffix(".tsv").removesuffix(".txt")}.{b}{Path(f).suffix}' if Path(f).suffix in ('.tsv', '.txt', '.done') else f'{f}.{b}')
    if old and old != new:
        for f in ('pso_user.tsv', 'pso_archive', 'shader-list-contribution.txt', '.shader-list-contribution.txt.done'):
            p, keep = data / f, aside(f, old)
            if p.exists() and not keep.exists(): p.rename(keep)
            back = aside(f, new)
            if back.exists() and not p.exists(): back.rename(p)
        print(f'  {g["name"]} was on the {old} build: its pipeline record and archive are kept aside for it, and the {new} build\'s own come back (saves stay)')
    if data.is_dir(): note.write_text(new + '\n')


def install(a):
    w = paths(a)[0]; tid = built_game(w)
    g = GAMES[tid]; app = w / app_file(g); dst = Path(a.to).expanduser() / app.name
    if subprocess.run(['pgrep', '-f', f'{dst}/Contents/MacOS'], capture_output=True).returncode == 0: sys.exit(f'{g["name"]} is running: quit it first')
    if dst.exists(): shutil.rmtree(dst)
    old = dst.with_name(f'{g["name"]}.app')   # the same game installed under its name from before app_file (":" in it): replaced, not kept twice
    if old != dst and old.is_dir() and (old / 'Contents/Info.plist').exists():
        if subprocess.run(['pgrep', '-f', f'{old}/Contents/MacOS'], capture_output=True).returncode == 0: sys.exit(f'{g["name"]} is running: quit it first')
        shutil.rmtree(old)
    shutil.move(str(app), dst); Path(str(app) + '.key').unlink(missing_ok=True)
    switched_build(g); trim_build(w, tid, g)
    print(f'installed: {dst}\nThe first start after each install waits 1-3 minutes while macOS scans the app (no window, no Dock icon yet): wait, do not open it twice.')


def run_game(a):
    """The build straight from ./work, without packing an app: the way to try a new game or a fix. Output goes to the terminal and work/logs/run-<time>.log;
    VAR=value arguments add host switches (docs/porting.md lists the useful ones). work/run/ctl.txt is the host's control file (DM_CTL): write a command
    line into it while the game runs (shot, passdump, texraw, memdump, ...). Shaders the game meets that the build lacks are saved to work/run/shdump."""
    w = paths(a)[0]; tid = built_game(w); g = GAMES[tid]; r = w / 'run'
    if not own_engine(g): sys.exit(f'{g["name"]} is built with another engine: open the app instead (its own runner: {w / tid})')
    if not (w / 'extract').is_dir(): sys.exit("the game's unpacked files were removed after its install, to save space: build it again first (HERMIT_KEEP_BUILD=1 keeps them)")
    use_engine(g)
    for d in ('save', 'temp', 'shdump'): (r / d).mkdir(parents=True, exist_ok=True)
    (r / 'ctl.txt').write_text(''); (w / 'logs').mkdir(exist_ok=True)
    e = dict(os.environ, DM_ROOT=str(w), DM_ROMFS=str(w / 'extract/RomFS.img'), DM_SAVE=str(r / 'save'), DM_TEMP=str(r / 'temp'), DM_NVN_SHDUMP=str(r / 'shdump'),
             DM_MSL_DIR=str(w / 'cache/metal_shader_cache'), DM_FONT_DIR=str(w / 'build/font'), DM_NVN_SHMAP=str(w / 'profile' / tid / 'shader_map.tsv'),
             DM_GAMES_DIR=str(w / 'profile'), DM_GAMES_FIRST='1', DM_LANG='en-US', DM_WINDOW='1', DM_AUDIO='1', DM_CTL=str(r / 'ctl.txt'))
    envf = g['dir'] / 'env.txt' if g.get('dir') else Path('/nonexistent')
    for l in (envf.read_text().splitlines() if envf.exists() else []):
        if '=' in l and not l.startswith('#'): k, v = l.split('=', 1); e.setdefault(k.strip(), v.strip())
    for kv in a.vars:
        if '=' not in kv: sys.exit(f'{kv}: expected VAR=value')
        k, v = kv.split('=', 1); e[k] = v
    cmd = [str(NX / 'dm/host/dmhost'), str(w / 'build/patched')]
    log = w / 'logs' / f'run-{datetime.datetime.now():%Y%m%d-%H%M%S}.log'
    print(' '.join(f'{k}={e[k]}' for k in sorted(e) if k.startswith('DM_')) + ' ' + ' '.join(cmd))
    if a.print: return
    print(f'log: {log}', flush=True)
    with log.open('w') as f:
        p = subprocess.Popen(cmd, env=e, cwd=r, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
        for line in p.stdout: sys.stdout.write(line); f.write(line)
    sys.exit(p.wait())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--work', default=str(ROOT / 'work'), help='build folder (default ./work)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('setup'); bp = sub.add_parser('build'); bp.add_argument('dump')
    bp.add_argument('--engine', help='a game with several builds: build this one (see: builds <dump>) instead of the one chosen for this Mac')
    bp.add_argument('--quick', action='store_true', help='nxnative builds: only the shaders the game\'s playtests used (its shader_seen.tsv), for testing a change in minutes; a full build afterwards fills in the rest')
    sp = sub.add_parser('builds'); sp.add_argument('dump', help='a dump folder, a title ID or a games/ folder name')
    rp = sub.add_parser('refresh'); rp.add_argument('--force', action='store_true', help='rebuild even with no new shaders')
    for x in (bp, rp): x.add_argument('--progress', choices=('lines', 'json'), default='lines', help='json: one event per line, for the Hermit app')
    ip = sub.add_parser('install'); ip.add_argument('--to', default='/Applications', help='the folder the app goes to (default /Applications)')
    stp = sub.add_parser('storage'); stp.add_argument('--clean', action='store_true'); stp.add_argument('--json', action='store_true'); stp.add_argument('--builds', action='append', help='a folder of build folders (default: the app\'s)')
    dp = sub.add_parser('identify'); dp.add_argument('dump'); dp.add_argument('--firmware', help='your unpacked firmware dump (else the one beside your prod.keys is looked for)')
    bp.add_argument('--firmware', help='MacNativeGames builds from an .nsp (and Breath of the Wild): your unpacked firmware dump, for the system fonts')
    bp.add_argument('--shared-fonts', help='MacNativeGames: the six shared fonts an earlier Tears of the Kingdom build extracted, instead of --firmware')
    for x in (bp, dp): x.add_argument('--keys', help='a Switch 1 game (.nsp / .nsz / .xci / .xcz): your own prod.keys, passed to the builder only (never copied or kept)')
    for x in (bp, dp):
        x.add_argument('--title-id', help='a Switch cartridge with several games (or files of several games): the one to build, its title ID')
        x.add_argument('--add', action='append', default=[], metavar='FILE', help='a Switch game: an update or DLC file to build with it (again for more)')
        x.add_argument('--no-update', action='store_true', help='a Switch game: build it without the update found beside it')
        x.add_argument('--custom', metavar='URL[@BRANCH]', help='your own nxnative fork, offered as the build "custom" (untested): https://github.com/<you>/nxnative@<branch>')
    gp = sub.add_parser('run'); gp.add_argument('vars', nargs='*', help='host switches, VAR=value'); gp.add_argument('--print', action='store_true', help='show the command only')
    a = ap.parse_args()
    global S1_PICK, S1_EXTRA, S1_NO_UPDATE, KEYS, CUSTOM
    CUSTOM = getattr(a, 'custom', None) or None
    S1_PICK = getattr(a, 'title_id', None); S1_EXTRA = [Path(x).expanduser().resolve() for x in getattr(a, 'add', None) or []]; S1_NO_UPDATE = bool(getattr(a, 'no_update', False)); KEYS = getattr(a, "keys", None)
    if a.cmd not in ('setup', 'identify', 'builds', 'storage') and Path(sys.prefix).resolve() != VENV.resolve() and not has_packages():   # run inside .venv, unless this Python has the packages (the app's)
        os.execv(py(), [str(py()), __file__] + sys.argv[1:])
    try:
        {'setup': setup, 'build': build, 'refresh': refresh, 'install': install, 'run': run_game, 'identify': identify, 'builds': builds_cmd, 'storage': storage}[a.cmd](a)
        if a.cmd == 'build': prune_engines()
    except (KeyboardInterrupt, SystemExit): raise
    except Exception as x:   # the details go to the log, the last line says what to do
        import traceback; traceback.print_exc()
        if 'cut short or damaged' in str(x):   # a code file of the dump (nso.Error): the dump's problem, not Hermit's
            P.end(False, 'the dump is damaged')
            sys.exit(f'The dump is damaged: {x}. Copy it off your Switch 2 again (over FTP, in binary mode).')
        P.end(False, 'Hermit stopped on a problem of its own')
        sys.exit('Hermit stopped on a problem of its own (a bug, not your dump). Copy the diagnostics in Settings and open an issue: '
                 'https://github.com/azmasm/hermit/issues')


if __name__ == '__main__':
    main()
