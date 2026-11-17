#!/bin/sh
# Builds the prebuilt launcher stubs the packager copies into each game:
#   bin/viper-launcher-linux        (native g++)
#   bin/viper-launcher-windows.exe  (MinGW-w64 cross compiler)
# Run again after editing launcher.cpp. Neither stub links GTK or WebView2 at
# build time, so no extra SDKs are needed.
set -e
cd "$(dirname "$0")"
mkdir -p bin

CXX_LINUX=${CXX_LINUX:-g++}
CXX_WINDOWS=${CXX_WINDOWS:-x86_64-w64-mingw32-g++}

"$CXX_LINUX" -std=c++17 -O2 -Wall -Wextra -s -static-libstdc++ -static-libgcc -pthread \
    launcher.cpp -o bin/viper-launcher-linux -ldl
echo "built bin/viper-launcher-linux"

if command -v "$CXX_WINDOWS" >/dev/null 2>&1; then
    "$CXX_WINDOWS" -std=c++17 -O2 -Wall -Wextra -s -static -municode -mwindows \
        launcher.cpp -o bin/viper-launcher-windows.exe -lws2_32 -lshell32 -ladvapi32 -lole32 -luser32 -lgdi32
    echo "built bin/viper-launcher-windows.exe"
else
    echo "skipped Windows launcher: $CXX_WINDOWS not found" >&2
fi
