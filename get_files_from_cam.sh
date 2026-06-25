#!/bin/sh
# simple rsync wrapper, mainly for storing rsync args+config

src="$1"
dst="$2"

if [ -z "$src" ] || [ ! -d "$src" ]; then
    echo "Given source location '$src' does not exist or is empty! Giving up."
    echo "Usage: $0 <source path> <destination path>"
    exit 1
fi

if [ -z "$dst" ] || [ ! -d "$(dirname "$dst")" ]; then
    echo "Given destination location '$dst' is empty or its parent does not exist! Giving up."
    echo "Usage: $0 <source path> <destination path>"
    exit 1
fi

rsync -av --info=progress2 --no-perms --no-owner --no-group "$src" "$dst"
