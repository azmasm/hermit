# Star Fox

Title ID `0400E88025B1A000`, update v131072. **nxnative reports it plays on an M4 Pro Mac (48 GB)**: the title, the prologue cinematic and the tutorial flight, with sound, at 56 to 60 fps.

Built with [upstream nxnative](https://github.com/seedds/nxnative)'s own builder at the commit `game.json` names (fetched once into `./engines`), with Hermit's front end added (`tools/engine/patch.py`), so it plays like the Mario Kart World port:

- the game starts at once: no settings window first
- **key 1**: the performance overlay in the top right (compact FPS and resolution → detailed graph, GPU, frame time, CPU, memory → off)
- **key 2**: the settings nxnative's own launch window offers for this game, in the Mario Kart style; most apply at the next launch

| What | |
|---|---|
| Profile and notes | [nxnative `dm/games/0400E88025B1A000`](https://github.com/seedds/nxnative/tree/d379ceda33b26c29897d022f5bcbf9660bbd732f/dm/games/0400E88025B1A000) |
| Dump folder | `base/` and `updates/131072/` (the game files are one 14.5 GB archive, `data.zip`) |
| Shaders | about 2,900, so a short shader build |
| Verified by nxnative | on an M4 Pro with 48 GB: the title, the prologue cinematic and the tutorial flight, with sound; the 3D is drawn at a low resolution and upscaled, as on the Switch 2 |

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
