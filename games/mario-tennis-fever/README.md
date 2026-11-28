# Mario Tennis Fever

Title ID `0400D4201C6EA000`, update v327680 (1.1.1). **nxnative reports it plays at 60 fps on an M4 Pro**: the title movie, practice, the main menu, Adventure's opening story and Free Play singles with real rallies.

Built with [upstream nxnative](https://github.com/seedds/nxnative)'s own builder at the commit `game.json` names (fetched once into `./engines`), with Hermit's front end added (`tools/engine/patch.py`), so it plays like the Mario Kart World port:

- the game starts at once: no settings window first
- **key 1**: the performance overlay in the top right (compact FPS and resolution → detailed graph, GPU, frame time, CPU, memory → off)
- **key 2**: the settings nxnative's own launch window offers for this game, in the Mario Kart style; most apply at the next launch

| What | |
|---|---|
| Profile and notes | [nxnative `dm/games/0400D4201C6EA000`](https://github.com/seedds/nxnative/tree/39fdbff9693cd7c5ad513b845ba3a0ebeafa3581/dm/games/0400D4201C6EA000) |
| Dump folder | `base/` and `updates/327680/` (the RomFS is 7.6 GB) |
| Shaders | about 35,000 (nxnative ships 1,351 of them as a seed list); all translate |
| Verified by nxnative | on an M4 Pro: Free Play singles on Stadium Court (Grass) with real rallies at 60 fps |
| Known | Adventure exploration ran at 30-45 fps with black outdoor textures on an M3 Pro (open, seedds/nxnative#1246); matches stay at 60 |

## Shared shader list

[`shader_list.tsv`](shader_list.tsv): this game's own list of shaders and pipelines players have met, for this engine version only (its first line says which). Its build ships nxnative's own seed list for the game (1,351 rows) followed by this list's rows. It starts empty: when you close the game, the app offers to send what it built (every 100 new rows), as described in the main README's Contributing section.

## How it runs on players' Macs

[`reports.tsv`](reports.tsv): every report that names the Mac (nxnative's own playtests and GitHub issues), with the fps and memory where given, and whether it was fixed. Hermit has not test-built this game: what is known comes from these reports.

## Build

In the Hermit app: choose your dump folder on the **Builds** page and press **Build**. In Terminal:

```bash
./hermit.py build "<your dump folder>"
```

Then `./hermit.py install`. `refresh` and `run` are for Mario Kart World only.
