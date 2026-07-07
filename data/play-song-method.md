# Playing Audio Files from WSL

## Default Method (Windows Media Player)
Use `cmd.exe` to open audio files with the default Windows media player:

```bash
winpath=$(wslpath -w "/path/to/file.mp3")
/mnt/c/Windows/System32/cmd.exe /c start "" "$winpath"
```

## Alternative (ffplay)
```bash
ffplay -nodisp -autoexit "/path/to/file.mp3"
```

## Searching for Files
- Search Downloads: `find /mnt/c/Users/ACER/Downloads -iname "*query*"`
- Search D: Musics: `find /mnt/d/Musics -iname "*query*"`
