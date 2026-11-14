# PRAGMATA

Title ID `0400C76024710000`, update v196608. Added automatically when [nxnative](https://github.com/seedds/nxnative) added its profile: see [nxnative's notes on it](https://github.com/seedds/nxnative/tree/e0cf2ac7a7b468a70f10243587b960d300bb4f5e/dm/games/0400C76024710000) for how far it plays and on which Mac.

Built with nxnative's own builder at the commit `game.json` names (fetched once into `./engines`), with Hermit's front end added (`tools/engine/patch.py`): the game starts at once, **key 1** is the performance overlay and **key 2** the settings.

| What | |
|---|---|
| Profile and notes | [nxnative `dm/games/0400C76024710000`](https://github.com/seedds/nxnative/tree/e0cf2ac7a7b468a70f10243587b960d300bb4f5e/dm/games/0400C76024710000) |
| Dump folder | `base/` and `updates/196608/` |

## Shared shader list

[`shader_list.tsv`](shader_list.tsv): this game's own list of shaders and pipelines players have met, for this engine version only. It starts empty: when you close the game, the app offers to send what it built.

## How it runs on players' Macs

[`reports.tsv`](reports.tsv): every report that names the Mac. Tell others how it ran with the [How it ran](https://github.com/azmasm/hermit/issues/new?template=how-it-ran.yml) form.

## Build

In the Hermit app: choose your dump folder on the **Builds** page and press **Build**. In Terminal:

```bash
./hermit.py build "<your dump folder>"
```
