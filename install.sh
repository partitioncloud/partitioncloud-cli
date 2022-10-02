#!/bin/bash

mkdir -p "$HOME/.local/bin"
cp partitioncloud-cli.py $HOME/.local/bin/partitioncloud-cli
echo "Script copied to $HOME/.local/bin/partitioncloud-cli"

if [[ *"$HOME/.local/bin"* != "$PATH" ]]; then
    printf "\x1b[31mWARNING !\x1b[0m $HOME/.local/bin is not in PATH, make sure to add it to have a quick access to the script\n";
fi;