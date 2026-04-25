fileencoding,UTF-8

m3uUrl := "https://pcrock99.github.io/playlist.m3u"
cacheFile := ".\date\playlist.m3u"

if !FileExist(".\date") {
    FileCreateDir, .\date
}

if !FileExist(cacheFile) {
    UrlDownloadToFile, % m3uUrl, % cacheFile
}

FileRead, m3uContent, % cacheFile

; 解析 M3U
songList := []
currentName := ""

Loop, Parse, m3uContent, `n, `r
{
    line := Trim(A_LoopField)
    if (line = "")
        continue
    
    if (SubStr(line, 1, 7) = "#EXTINF") {
        commaPos := InStr(line, ",")
        if (commaPos > 0) {
            currentName := SubStr(line, commaPos + 1)
            currentName := Trim(currentName)
        }
        continue
    }
    
    if (SubStr(line, 1, 1) = "#")
        continue
    
    if (currentName != "" && (SubStr(line, 1, 4) = "http" || SubStr(line, 1, 2) = "//")) {
        songList.Push([currentName, line])
        currentName := ""
    }
}

if (songList.Length() = 0) {
    MsgBox, 解析失败
    ExitApp
}

Menu, Tray, Icon, Shell32.dll, 138

play:
    Random, randIndex, 1, songList.Length()
    song := songList[randIndex]
    songName := song[1]
    songUrl := song[2]
    
    CoordMode, ToolTip, Screen
    ToolTip, % songName, A_ScreenWidth, A_ScreenHeight - 72
    
    SoundPlay, % songUrl, Wait
    GoSub, play

^!Up::Run, notepad %cacheFile%

^!Left::ExitApp

^!Right::SoundPlay,kill

^!Down::
    if !FileExist(".\mp3")
        FileCreateDir, .\mp3
    UrlDownloadToFile, % song[2], % ".\mp3\" . song[1] . ".mp3"
    ToolTip, 下载完成: %fileName%, A_ScreenWidth, A_ScreenHeight - 72
    Sleep, 1500
    ToolTip, % songName, A_ScreenWidth, A_ScreenHeight - 72
return
