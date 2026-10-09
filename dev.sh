#!/bin/sh
# Outils de développement — tout s'exécute dans Docker, rien n'est installé sur la machine.
#
#   ./dev.sh build      construit l'image de dev (à faire une fois, ou après modif des requirements)
#   ./dev.sh test       lance les tests automatiques
#   ./dev.sh gui        lance l'application, visible sur http://localhost:6080/vnc.html
#   ./dev.sh smoke      test de bout en bout de l'interface + capture d'écran dans .dev-out/
#   ./dev.sh examples   régénère les fichiers d'exemple
#   ./dev.sh shell      ouvre un terminal dans le conteneur
#   ./dev.sh clean      supprime l'image de dev
set -e
IMAGE=cleantrace-dev
cd "$(dirname "$0")"
RUN="docker run --rm -v $(pwd):/app -w /app"

case "${1:-test}" in
    build)    docker build -f docker/Dockerfile -t "$IMAGE" . ;;
    test)     [ $# -gt 0 ] && shift
              # deux fois : texte pandas en pur Python, puis avec pyarrow (comme sous Anaconda)
              for storage in python pyarrow; do
                  echo "== pandas texte : $storage"
                  $RUN -e CLEANTRACE_STRING_STORAGE=$storage "$IMAGE" pytest -q -p no:cacheprovider "$@" || exit 1
              done ;;
    gui)      $RUN -it -p 6080:6080 "$IMAGE" gui ;;
    smoke)    mkdir -p .dev-out; $RUN "$IMAGE" python tools/smoke_gui.py /app/.dev-out ;;
    examples) $RUN "$IMAGE" python exemples/generer_exemples.py ;;
    shell)    $RUN -it "$IMAGE" bash ;;
    clean)    docker rmi "$IMAGE" ;;
    *)        sed -n '2,11p' "$0"; exit 1 ;;
esac
