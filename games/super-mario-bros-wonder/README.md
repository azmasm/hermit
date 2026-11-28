# Super Mario Bros. Wonder

Title ID `010015100B514000`. A **Switch** game: built from your own copy's `.xci` / `.nsp` files with your own `prod.keys` (see [LEGAL.md](../../LEGAL.md)). Versions 1.0.0, 1.0.1 (update v65536) and 1.2.1 (update v327680).

Built with [nxnative](https://github.com/seedds/nxnative)'s profile `dm/games/010015100B514000` at the commit `game.json` names, with Hermit's front end added (`tools/engine/patch.py`): the game starts at once, **key 1** is the performance overlay and **key 2** the settings. Plays at 60 fps on an M1 Max (1.0.0 with update 1.0.1).

| What | |
|---|---|
| Profile and notes | [nxnative `dm/games/010015100B514000`](https://github.com/seedds/nxnative/tree/39fdbff9693cd7c5ad513b845ba3a0ebeafa3581/dm/games/010015100B514000) |
| Input | the base game (.xci or .nsp) and, optionally, its update .nsp |

## Shared shader list

[`shader_list.tsv`](shader_list.tsv): this game's list of shaders and pipelines players have met. When you close the game, the app offers to send what it built.

## How it runs on players' Macs

[`reports.tsv`](reports.tsv): every report that names the Mac. Tell others how it ran with the [How it ran](https://github.com/azmasm/hermit/issues/new?template=how-it-ran.yml) form.

## Build

In the Hermit app: **+ Build game**, choose the game's file (or the folder with its base game and update), then your `prod.keys`. In Terminal:

```bash
./hermit.py build "<the game's .xci or .nsp, or its folder>" --keys <path of prod.keys>
```
