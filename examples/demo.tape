# Generate the README GIF:  vhs examples/demo.tape  ->  docs/demo.gif
# Requires: brew install vhs   (ffmpeg backend; no manual screen recording)

Output docs/demo.gif

Set Shell zsh
Set Theme "Catppuccin Mocha"
Set FontSize 15
Set Width 1180
Set Height 920
Set Padding 20
Set Margin 10
Set BorderRadius 8
Set PlaybackSpeed 1.0
Set TypingSpeed 1ms

# Near-instant command (tight front), then let the live walkthrough play out.
Sleep 400ms
Type "TICKFEED_LOG_LEVEL=ERROR uv run examples/demo.py BTC/USDT 4h"
Sleep 300ms
Enter

# cold->warm wait + the six sections. Bump if your network warms slowly.
Sleep 24s
