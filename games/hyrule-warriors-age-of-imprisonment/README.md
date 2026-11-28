# Hyrule Warriors: Age of Imprisonment

Title ID `04003F40232DE000`, update v196608. **nxnative reports it plays on a 16 GB M6 Mac** from a new save into the first field (frame median 16.6 ms, with long frames every few frames); battles not reached.

Built with [upstream nxnative](https://github.com/seedds/nxnative)'s own builder at the commit `game.json` names (fetched once into `./engines`), with Hermit's front end added (`tools/engine/patch.py`), so it plays like the Mario Kart World port:

- the game starts at once: no settings window first
- **key 1**: the performance overlay in the top right (compact FPS and resolution → detailed graph, GPU, frame time, CPU, memory → off)
- **key 2**: the settings nxnative's own launch window offers for this game, in the Mario Kart style; most apply at the next launch

| What | |
|---|---|
| Profile and notes | [nxnative `dm/games/04003F40232DE000`](https://github.com/seedds/nxnative/tree/39fdbff9693cd7c5ad513b845ba3a0ebeafa3581/dm/games/04003F40232DE000) |
| Dump folder | `base/` and `updates/196608/` (the update RomFS is whole: 46 GB). nxnative tested a NUP of the same files; Hermit builds from a dump folder |
| Shaders | about 102,000: a full build can take many hours |
| Verified by nxnative | on an M6 Mac with 16 GB: the first-run settings, the opening movies and cutscenes, the first field; frame p50 16.6 ms, p95 about 18 ms, p99 100-114 ms (Metal's submission queue, open) |
| Known | A Mac Studio M5 Max froze the whole display (WindowServer and GPU timeouts) while playing (open, seedds/nxnative#1223). The language list is missing in an app built from a dump |

## Shared shader list

[`shader_list.tsv`](shader_list.tsv): this game's own list of shaders and pipelines players have met, for this engine version only (its first line says which). It starts empty: when you close the game, the app offers to send what it built (every 100 new rows), as described in the main README's Contributing section.

## How it runs on players' Macs

[`reports.tsv`](reports.tsv): every report that names the Mac (nxnative's own playtests and GitHub issues), with the fps and memory where given, and whether it was fixed. Hermit has not test-built this game: what is known comes from these reports.

## Build

In the Hermit app: choose your dump folder on the **Builds** page and press **Build**. In Terminal:

```bash
./hermit.py build "<your dump folder>"
```

Then `./hermit.py install`. `refresh` and `run` are for Mario Kart World only.
