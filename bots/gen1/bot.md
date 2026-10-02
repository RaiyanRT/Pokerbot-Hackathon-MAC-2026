# MAC poker bot scaffold

Everything you need to start building.

## Setup

```
pip install https://poker.monashcoding.com/dl/macpoker-0.1.0-py3-none-any.whl
```

Python 3.10 or newer. The tournament sandbox runs Python 3.12 with the SDK
and numpy preinstalled. Nothing else is available at runtime.

## Develop

Edit `main.py`. Split logic into extra modules in this folder if you like;
`main.py` can import them.

Test against the house bots (`house:call`, `house:checkfold`, `house:allin`, `house:random`). Every argument after `play` is one seat at the table, so you can mix several of your own files and house bots:

```
macpoker play main.py house:call house:random --deals 50
macpoker play main.py house:call --deals 100 --subprocess --history out.json
```

## Submit

Zip this folder with `main.py` at the root and upload it at
https://poker.monashcoding.com/app. Every upload plays a validation game
against the house; pick a passing upload as your **main** before the
deadline. That is your tournament entry.

## Rules that matter here

No network calls, no AI/LLM calls at runtime, standard library plus numpy
only. The sandbox has no internet and submissions are audited.

Questions: https://discord.gg/kkv2hJyzGp
Docs: https://docs.poker.monashcoding.com
