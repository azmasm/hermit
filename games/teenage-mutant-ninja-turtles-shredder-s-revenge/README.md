# Teenage Mutant Ninja Turtles: Shredder's Revenge

Title ID `0100FE701475A000`. A **Switch** game: built from your own copy's `.xci` / `.nsp` files with your own `prod.keys` (see [LEGAL.md](../../LEGAL.md)). Versions: 1.0.9.

Added automatically from [nxnative](https://github.com/seedds/nxnative)'s profile: see [its notes](https://github.com/seedds/nxnative/tree/b020ebe5ed1a1adef38b9f9f6ec77dbb902e77de/dm/games/0100FE701475A000) for how far it plays and on which Mac. Built with nxnative's builder at the commit `game.json` names, with Hermit's front end: the game starts at once, **key 1** is the performance overlay and **key 2** the settings.

## Shared shader list

[`shader_list.tsv`](shader_list.tsv): shaders and pipelines players have met. When you close the game, the app offers to send what it built.

## How it runs on players' Macs

[`reports.tsv`](reports.tsv): every report that names the Mac. Tell others how it ran with the [How it ran](https://github.com/azmasm/hermit/issues/new?template=how-it-ran.yml) form.

## Build

In the Hermit app: **+ Build game**, choose the game's file (or the folder with its base game, update and DLC), then your `prod.keys`. In Terminal:

```bash
./hermit.py build "<the game's .xci or .nsp, or its folder>" --keys <path of prod.keys>
```
