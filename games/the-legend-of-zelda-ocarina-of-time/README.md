# The Legend of Zelda: Ocarina of Time

Title ID `0400486024DEC000`, update v131072. Added automatically when [nxnative](https://github.com/seedds/nxnative) added its profile: see [nxnative's notes on it](https://github.com/seedds/nxnative/tree/f644af4b6381ba1cfe57c2894d096d187b3ce37f/dm/games/0400486024DEC000) for how far it plays and on which Mac.

Built with nxnative's own builder at the commit `game.json` names (fetched once into `./engines`), with Hermit's front end added (`tools/engine/patch.py`): the game starts at once, **key 1** is the performance overlay and **key 2** the settings.

| What | |
|---|---|
| Profile and notes | [nxnative `dm/games/0400486024DEC000`](https://github.com/seedds/nxnative/tree/f644af4b6381ba1cfe57c2894d096d187b3ce37f/dm/games/0400486024DEC000) |
| Dump folder | `base/` and `updates/131072/` |

## Shared shader list

[`shader_list.tsv`](shader_list.tsv): this game's own list of shaders and pipelines players have met, for this engine version only. It starts empty: when you close the game, the app offers to send what it built.

## How it runs on players' Macs

[`reports.tsv`](reports.tsv): every report that names the Mac. Tell others how it ran with the [How it ran](https://github.com/azmasm/hermit/issues/new?template=how-it-ran.yml) form.

## Build

In the Hermit app: choose your dump folder on the **Builds** page and press **Build**. In Terminal:

```bash
./hermit.py build "<your dump folder>"
```

## azmasm's build

[hermit-builds' `ocarina` branch](https://github.com/azmasm/hermit-builds/tree/ocarina) (MIT) is nxnative with Ocarina of Time pull requests merged ahead of upstream, played on an M1 Max until it ran well there:

- **Faster foliage:** large mesh stage memory in a device slice (#2308) and compute work moved ahead of the scene pass (#1952), on top of bmjask's playability checkpoint (#1663).
- **Fewer stutters:** plant pipelines built in the background when the game sets its shaders (#2307), 171 more prepared before play (#2324), area loads that no longer freeze late in a session (#2344) or stay at 20 fps afterwards (#2367), and the next frame translated while the game is still finishing it (#2341).
- **A first start in seconds:** the pipelines the game would prepare at its first start are made while it builds (#2353, `--prebake`).
- **Picture fixes:** the mist's hard edge at the screen's sides (#1824), wind and leaves at the right speed (#1714), flower bushes without holes in Hyrule Castle's courtyard (#2226), and the four leaf shaders that made Apple's compiler crash on macOS 26.6 (white leaves in Hyrule Field) kept in their safe form.
- **Settings (key 2):** Frame generation (30 drawn, 60 shown, MetalFX's frame interpolator), Fast mode (720p + MetalFX), Render scale (#1903) and Full docked picture (the Switch 2's full 1920x1080 3D picture instead of 1536x864).

On an M1 Max (64 GB, macOS 27.2.1) it plays at about 50-55 fps through Kokiri Forest and Hyrule Field at 1536x864, or a steady 30 drawn / 60 shown with Frame generation at 1920x1080, with a 17-20 GB peak. The app recommends it on M1 and M2 Macs with 32 GB or more; it has not been played on other Macs yet, so reports are very welcome. Known: like every build of this game, it can still crash entering a new area after a long session ([nxnative#1445](https://github.com/seedds/nxnative/issues/1445)); the game has saved by then. Its shader list is [`shader_list-azmasm.tsv`](shader_list-azmasm.tsv).

## Second build: kid-with-sword-remake

[cheemu21/kid-with-sword-remake](https://github.com/cheemu21/kid-with-sword-remake) (MIT) is an nxnative fork made for this game, on iPhone and Mac: nxnative's Ocarina of Time branch with Ocarina pull requests merged ahead of upstream (foliage, the Hyrule Field crash, the freeze after the talk with Saria, terrain holes, faster GPU memory tables), fewer render-pass splits, a 30 / 60 fps frame step through the game's own frame-rate controller, MetalFX in place of the game's upscaler and a texture memory release. Its author reports a steady 60 fps at 720p on a MacBook Air M5 (16 GB) using about 9.5 GB; see [its notes](https://github.com/cheemu21/kid-with-sword-remake/blob/kid-with-sword-remake/docs/games/kid-with-sword-remake.md).

Hermit builds it as it builds nxnative (`--engine kid-with-sword`), with the same front end added, and bakes in the port's recommended Mac switches (`"switches"` in `game.json`: MetalFX upscaling, a fixed frame rate, its 8 GB alias region). Its shader list is [`shader_list-kid-with-sword.tsv`](shader_list-kid-with-sword.tsv). The port's fixed-resolution files (`scripts/oot_res_overlay.py`, 720p handheld / about 1080p docked) are not made by Hermit yet, so it renders at the game's own dynamic resolution. The app recommends it on a MacBook Air, where it was made and tested, and on Macs with 16 GB or less (it releases texture memory); other Macs get nxnative's build.
