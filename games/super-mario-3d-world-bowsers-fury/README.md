# Super Mario 3D World + Bowser's Fury

Title ID `010028600EBDA000`. A **Switch** game: built from your own copy's `.xci` / `.nsp` files with your own `prod.keys` (see [LEGAL.md](../../LEGAL.md)). Version 1.2.2: the base game and its update 1.2.2 (v262144).

Built with [nxnative](https://github.com/seedds/nxnative)'s profile `dm/games/010028600EBDA000` at the commit `game.json` names, with Hermit's front end added: the game starts at once, **key 1** is the performance overlay and **key 2** the settings.

| What | |
|---|---|
| Profile and notes | [nxnative `dm/games/010028600EBDA000`](https://github.com/seedds/nxnative/tree/7bc66e5a3d2dc18d6223a252fb898261be6df20a/dm/games/010028600EBDA000) |
| Input | the base game (.xci or .nsp) and its update 1.2.2 (.nsp) |

## Shared shader list

[`shader_list.tsv`](shader_list.tsv): shaders and pipelines players have met. When you close the game, the app offers to send what it built.

## How it runs on players' Macs

[`reports.tsv`](reports.tsv): every report that names the Mac. Tell others how it ran with the [How it ran](https://github.com/azmasm/hermit/issues/new?template=how-it-ran.yml) form.

## Build

In the Hermit app: **+ Build game**, choose the game's file (or the folder with its base game and update), then your `prod.keys`. In Terminal:

```bash
./hermit.py build "<the game's .xci or .nsp, or its folder>" --keys <path of prod.keys>
```
