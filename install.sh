#!/usr/bin/env bash
# Instala o bridgectl, a unit template do systemd --user e um bridges.toml de exemplo.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin"
CFG="${XDG_CONFIG_HOME:-$HOME/.config}/mautrix-bridges"
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

mkdir -p "$BIN" "$CFG" "$UNITS" \
         "${XDG_DATA_HOME:-$HOME/.local/share}/mautrix-bridges/bin" \
         "${XDG_STATE_HOME:-$HOME/.local/state}/mautrix-bridges"

install -m 0755 "$SRC/bin/bridgectl" "$BIN/bridgectl"
install -m 0644 "$SRC/systemd/mautrix-bridge@.service" "$UNITS/mautrix-bridge@.service"
install -m 0644 "$SRC/systemd/mautrix-backup.service" "$UNITS/mautrix-backup.service"
install -m 0644 "$SRC/systemd/mautrix-backup.timer" "$UNITS/mautrix-backup.timer"

if [[ -e "$CFG/bridges.toml" ]]; then
    echo "==> $CFG/bridges.toml já existe, mantido como está"
else
    install -m 0600 "$SRC/config/bridges.toml.example" "$CFG/bridges.toml"
    echo "==> $CFG/bridges.toml criado"
fi

chmod 700 "$CFG" \
    "${XDG_DATA_HOME:-$HOME/.local/share}/mautrix-bridges" \
    "${XDG_STATE_HOME:-$HOME/.local/state}/mautrix-bridges"
systemctl --user daemon-reload
systemctl --user enable --now mautrix-backup.timer

echo
echo "Instalado. Próximos passos: ver README.md (seção 'Uso')."
echo
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "AVISO: $BIN não está no seu PATH — adicione no ~/.bashrc ou ~/.zshrc:"
       echo "  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
