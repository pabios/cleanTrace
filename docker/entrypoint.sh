#!/bin/sh
# Démarre un écran virtuel, puis exécute la commande demandée.
set -e
Xvfb :99 -screen 0 1600x960x24 -nolisten tcp >/dev/null 2>&1 &
for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ -e /tmp/.X11-unix/X99 ] && break
    sleep 0.2
done

if [ "$1" = "gui" ]; then
    x11vnc -display :99 -forever -shared -nopw -quiet -rfbport 5900 >/dev/null 2>&1 &
    websockify --web /usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 &
    echo "Interface CleanTrace : http://localhost:6080/vnc.html?autoconnect=1&resize=scale"
    exec python main.py
fi
exec "$@"
