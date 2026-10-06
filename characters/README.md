# Characters

One folder per character: `characters/<name>/manifest.json` + transparent PNGs.
Copy `_example/` to `characters/<name>/`, drop in your PNGs, then set `character: <name>` in the channel profile.
Scenes opt in from n8n with `"character": true`, `"character": "happy"` or
`{"pose": "shocked", "side": "right", "action": "enter"}`  (actions: bounce | enter | none).
A missing character/pose is skipped with a warning; the render never fails because of it.
