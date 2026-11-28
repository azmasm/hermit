# Fire Emblem Fortune's Weave

Title ID `04007EF01F8AE000`, v131072. **nxnative reports it plays on the Mac**: the opening movie, the dialogue, the first battle map and its battle scenes, at 60 fps (120 offered).

Built with [upstream nxnative](https://github.com/seedds/nxnative)'s own builder at the commit `game.json` names (fetched once into `./engines`), with Hermit's front end added (`tools/engine/patch.py`), so it plays like the Mario Kart World port:

- the game starts at once: no settings window first
- **key 1**: the performance overlay in the top right (compact FPS and resolution → detailed graph, GPU, frame time, CPU, memory → off)
- **key 2**: the settings nxnative's own launch window offers for this game, in the Mario Kart style; most apply at the next launch

| What | |
|---|---|
| Profile and notes | [nxnative `dm/games/04007EF01F8AE000`](https://github.com/seedds/nxnative/tree/e68ccb49af996be42a47a0f73b61a6da4b326b33/dm/games/04007EF01F8AE000) |
| Dump folder | `exefs/` and `romfs/` (no `base/` layout; the RomFS is 28 GB) |
| Shaders | about 17,000 (nxnative ships 1,811 of them as a seed list) |
| Frame rate | the game runs gameplay at 30 as shipped; nxnative sets 60, and **Frame rate** in the settings offers 120 |
| Verified by nxnative | the first battle map, whose first turn matches published footage, and its battle scenes in a player's playtest; GPU about 12 ms a frame. Its movies are AV1: Macs before M3 decode them in software |

## Shared shader list

[`shader_list.tsv`](shader_list.tsv): this game's own list of shaders and pipelines players have met, for this engine version only (its first line says which). Its build ships nxnative's own seed list for the game (1,811 rows) followed by this list's rows. It starts empty: when you close the game, the app offers to send what it built (every 100 new rows), as described in the main README's Contributing section.

## How it runs on players' Macs

[`reports.tsv`](reports.tsv): every report that names the Mac (nxnative's own playtests and GitHub issues), with the fps and memory where given, and whether it was fixed. Hermit has not test-built this game: what is known comes from these reports.

## Build

In the Hermit app: choose your dump folder on the **Builds** page and press **Build**. In Terminal:

```bash
./hermit.py build "<your dump folder>"
```

Then `./hermit.py install`. `refresh` and `run` are for Mario Kart World only.
