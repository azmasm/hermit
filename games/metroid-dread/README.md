# Metroid Dread

Title ID `010093801237C000`. A **Switch** game: built from your own copy's `.xci` / `.nsp` files with your own `prod.keys` (see [LEGAL.md](../../LEGAL.md)). Version 1.0.0.

Built with [MacNativeGames](https://github.com/ly05010419/MacNativeGames) by ly05010419 (MIT): its [`games/dread`](https://github.com/ly05010419/MacNativeGames/tree/5b3b359ab3884919cab3aec68d54e61d46e99b06/games/dread) port, at the commit `game.json` names, run through that port's own builder as its README describes. Community port, early. Base game 1.0.0 (.xci or .nsp); updates are not supported yet. It has its own runtime, so Hermit's overlay and key-2 settings are not added: the port has its own. Needs Homebrew's `python@3.14`, `opus` and `libvpx`.

## Build

In the Hermit app: **+ Build game**, choose the game's file (or the folder with its base game), then your `prod.keys`. In Terminal:

```bash
./hermit.py build "<the game's .xci or .nsp, or its folder>" --keys <path of prod.keys>
```

Add `--firmware <your unpacked firmware dump>` (or `--shared-fonts <a Tears of the Kingdom build's fonts>`) when the port needs the Switch's system fonts (an `.nsp` carries none).

## How it runs on players' Macs

[`reports.tsv`](reports.tsv): every report that names the Mac. Tell others how it ran with the [How it ran](https://github.com/azmasm/hermit/issues/new?template=how-it-ran.yml) form.
