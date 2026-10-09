# Environnement de développement CleanTrace (rien n'est installé sur la machine hôte).
# Contient un écran virtuel (Xvfb) pour lancer l'interface Tkinter sans affichage,
# et un accès noVNC pour la voir dans le navigateur : http://localhost:6080/vnc.html
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    DISPLAY=:99

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        tk xvfb x11vnc novnc websockify fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt /tmp/
RUN pip install -r /tmp/requirements-dev.txt

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /app
EXPOSE 6080
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["pytest", "-q"]
