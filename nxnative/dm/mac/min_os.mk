# The minimum macOS of the Mac host, on its compile lines (dm/host/Makefile; the NSP script runs the same line, make -n). pack_app.py reads it back out of the finished host into
# LSMinimumSystemVersion, so this is also the oldest macOS the app opens on (README, "Building for an older macOS 26.x"). Without it clang takes the SDK's
# version (27.0 with Xcode 27.1), and pack_app.py, which reads the host's minos into LSMinimumSystemVersion, made a Mac app that macOS 26.x does not open (GitHub issue #673)
# A default, not a hard assignment: a build for an older macOS 26.x overrides it (MACOS_MIN=26.5 ./switch2mac.py build ..., or make ... MACOS_MIN=26.5), which reaches the
# compile lines through the environment as well as the make command line.
MACOS_MIN ?= 26.6
