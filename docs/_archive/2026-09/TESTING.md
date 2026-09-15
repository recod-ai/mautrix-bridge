# Guia de teste

Este roteiro valida cada peça do `bridgectl` **antes** de você apontar para o
seu Synapse de verdade: download real de um binário, geração de config,
gravação no chaveiro, renderização em tmpfs e o systemd. Cada comando abaixo
foi rodado de verdade ao escrever este guia (mautrix-slack v0.2608.0, Arch
Linux) — não é só teoria.

Vamos usar a ponte `slack` como cobaia porque ela é bridgev2 (tem a flag `-e`
de auto-config). Se quiser testar `discord` (arquitetura legada), o passo 4
muda — ver nota no fim.

## 0. Pré-requisitos

```bash
sudo pacman -S python-keyring gnome-keyring     # Arch
# outras distros: pip install --user keyring, e garanta um provedor de
# SecretService rodando (gnome-keyring-daemon ou kwalletd)
python3 -c "import keyring; print(keyring.get_keyring())"
```

A última linha deve imprimir algo como
`keyring.backends.SecretService.Keyring (priority: 5)`. Se imprimir
`keyring.backends.fail.Keyring`, não há um chaveiro D-Bus rodando na sua
sessão — em GNOME/KDE normal isso já vem de fábrica; em WM minimalista
(i3, sway, etc.) pode precisar iniciar o `gnome-keyring-daemon` manualmente no
autostart.

## 1. Instalar

```bash
cd mautrix-bridge
./install.sh
```

Confira que apareceu:

```bash
ls ~/.local/bin/bridgectl
ls ~/.config/systemd/user/mautrix-bridge@.service
cat ~/.config/mautrix-bridges/bridges.toml
```

## 2. Baixar um binário de verdade

```bash
bridgectl status
```

Deve listar `slack` e `discord` como "não instalado". Agora baixe:

```bash
bridgectl update slack --force
```

Esperado: uma linha `baixando vX.Y.Z (amd64, canal release)` seguida de
`instalado vX.Y.Z em .../bin/mautrix-slack`. Rode `bridgectl status` de novo —
a versão deve aparecer, e "checado" deve mostrar "0 min".

Rode `bridgectl update slack` (sem `--force`) de novo: deve dizer
`checado há Ns, pulando (cooldown 900s)` — é o cooldown funcionando,
importante para não martelar o GitHub quando o systemd reinicia a ponte em
loop.

**Se der erro de rede/DNS aqui**, sem binário instalado `bridgectl status`
mostra "não instalado" para sempre — é esperado, o comando não finge sucesso.

## 3. Configurar o servidor

```bash
bridgectl init
```

Responda com valores de teste (não precisam ser reais ainda, só o domínio não
pode ficar em branco):

```
Domínio do seu Synapse: meu-servidor.exemplo
Endereço público do Synapse (HTTPS, o mesmo que seu Element usa) [https://matrix.meu-servidor.exemplo]: http://localhost:8008
Seu IP nesta VPN WireGuard (o administrador te deu, ex: 10.10.0.2): 10.10.0.2
Seu Matrix ID (dono das suas pontes — ganha o nível de permissão 'admin' *dentro*
de cada ponte, sem relação com ser admin do Synapse; ...): @dono:meu-servidor.exemplo

Confira antes de gravar:
  domínio do Synapse:      meu-servidor.exemplo
  endereço do Synapse:     http://localhost:8008
  seu IP na VPN:           10.10.0.2
  dono das pontes:         @dono:meu-servidor.exemplo
Gravar em bridges.toml? [S/n]: 
```

O endereço do Synapse já vem com o padrão `https://matrix.<domínio>` sugerido
entre colchetes — pra este teste local, sem servidor de verdade, sobrescreva
com `http://localhost:8008` como no exemplo acima. O IP da VPN não tem
default (é único por pessoa); para este teste local sem VPN de verdade, use
qualquer IP válido (ex: `10.10.0.2`) — só não pode ficar em branco.
Apertar Enter sem digitar nada aceita o valor sugerido, quando existe um.

O `init` valida o Matrix ID do dono da ponte (formato `@usuario:domínio`) e avisa se o
domínio dele for diferente do que você configurou como servidor — pensado
pra pegar o erro de digitar sem querer o Matrix ID de outra pessoa em vez do
seu. Isso só pega domínio diferente; se você e outra pessoa estiverem no
*mesmo* Synapse, o único jeito de pegar o erro é conferir com atenção a tela
de confirmação antes de apertar Enter.

Confira que gravou em `~/.config/mautrix-bridges/bridges.toml`:

```bash
grep -A4 "\[server\]" ~/.config/mautrix-bridges/bridges.toml
```

## 4. Configurar a ponte com um comando só

```bash
bridgectl setup slack
```

Isso faz tudo de uma vez: gera `config.yaml` (via `mautrix-slack -e`),
substitui `homeserver.address`/`domain`, `appservice.address`/`hostname` e
`bridge.permissions` pelos valores do passo 3, roda `-g` pra gerar
`registration.yaml`, e move os segredos pro chaveiro. Esperado, nessa ordem:

```
[bridgectl] config de exemplo em .../slack/config.yaml
[bridgectl] config.yaml: homeserver.address/domain, appservice.address/hostname e bridge.permissions preenchidos
[bridgectl] slack: registration.yaml gerado
[bridgectl] movidos para o chaveiro: mautrix-slack/uri, mautrix-slack/as_token, ...
[bridgectl] movidos para o chaveiro: mautrix-slack/as_token, mautrix-slack/hs_token
[bridgectl] slack: pronto. Falta: ...
```

Confira que os placeholders realmente foram trocados — `homeserver.address`
deve ser a URL pública, `appservice.address`/`hostname` devem ser o IP da VPN
(passo 3), e só deve sobrar `${keyring:...}` nos segredos:

```bash
grep -E "address: http|^\s*domain:|^\s*hostname:|as_token:|hs_token:" ~/.config/mautrix-bridges/slack/config.yaml
```

E que o valor real está mesmo no chaveiro:

```bash
python3 -c "import keyring; print(keyring.get_password('mautrix-slack', 'as_token'))"
```

Apague os backups depois de conferir (senão eles derrotam o propósito todo —
ainda têm o valor em texto puro):

```bash
rm ~/.config/mautrix-bridges/slack/*.orig
```

**Por que isso é seguro fazer automático:** os campos `pickle_key` e
`shared_secret` vêm com o valor literal `generate` no template, e o binário os
substitui por um valor aleatório *reescrevendo o arquivo* na primeira vez que
roda com `-g`. O `setup` roda isso contra o arquivo persistente em
`~/.config` (nunca via `bridgectl run`, que sempre escreve num tmpfs
descartável) — por isso o valor fica estável entre reinícios em vez de ser
regenerado (e as sessões de criptografia perdidas) a cada restart do serviço.

**SQLite em vez de Postgres** (não precisa de banco nenhum rodando, testei —
ver README): o `setup` não mexe no bloco `database`, então ajuste à mão depois:

```bash
sed -i 's/type: postgres/type: sqlite3-fk-wal/; s|uri: "\${keyring:uri}"|uri: "file:mautrix-slack.db?_txlock=immediate"|' \
    ~/.config/mautrix-bridges/slack/config.yaml
```

(Se você rodar isso depois do `harvest`, o `uri` original em texto puro já
tinha ido pro chaveiro sem necessidade — inofensivo, mas se quiser evitar,
rode o `sed` antes do `bridgectl setup`, contra o `config.yaml` recém-gerado
pelo bootstrap.)

## 5. Rodar via bridgectl (sem systemd ainda)

```bash
bridgectl run slack
```

Esperado: uma linha `exec mautrix-slack (vX.Y.Z) — config em
/run/user/<seu UID>/mautrix-slack/config.yaml` (ou `/dev/shm/...` se seu
sistema não tiver `XDG_RUNTIME_DIR`), seguida da própria ponte iniciando. Em
outro terminal, enquanto ainda está rodando:

```bash
grep -E "as_token|hs_token" /run/user/$(id -u)/mautrix-slack/config.yaml
```

Deve mostrar o **valor real**, não o placeholder — é o render acontecendo. Com
SQLite (passo 4), a ponte deve criar o arquivo `.db`/`.db-shm`/`.db-wal` no
diretório de trabalho (`~/.local/share/mautrix-bridges/slack/`) e ficar
esperando conexão do Synapse, sem imprimir mais nada — `Ctrl+C` para parar. Se
configurou Postgres sem ele estar rodando, vai falhar com erro de conexão —
normal, não é o que este passo está testando.

Pare a ponte e confira que o arquivo em tmpfs sumiu:

```bash
ls /run/user/$(id -u)/mautrix-slack/    # "No such file or directory" é o esperado
```

(Isso só é garantido quando `bridgectl run` roda **dentro do systemd**, que
cria/apaga o `RuntimeDirectory=` sozinho. Rodando à mão fora do systemd, como
acabamos de fazer, o diretório em `/run/user/UID` pode ficar para trás — sem
problema, ele não tem segredo nenhum persistente, é recriado do zero no
próximo `run`.)

## 6. Subir via systemd

```bash
systemctl --user daemon-reload
systemctl --user enable --now mautrix-bridge@slack
journalctl --user -u mautrix-bridge@slack -f
```

O que checar no log:

- Uma linha do `bridgectl update` (o `ExecStartPre`) antes da ponte começar —
  é o auto-update rodando no boot do serviço.
- Se você reiniciar o serviço (`systemctl --user restart mautrix-bridge@slack`)
  dentro dos 900s do cooldown, a linha deve virar
  `checado há Ns, pulando` em vez de baixar de novo.
- `systemctl --user status mautrix-bridge@slack` deve mostrar `active (running)`
  com o PID do binário `mautrix-slack` (não do `bridgectl` — o `os.execv`
  substitui o processo, então quem o systemd supervisiona é a ponte mesma).

Para testar a resiliência a rede fora do ar, derrube a rede (ou bloqueie
`api.github.com` no `/etc/hosts` temporariamente) e reinicie o serviço: a
ponte deve subir normalmente com o binário já instalado, só logando que não
conseguiu checar atualização.

## 7. (Opcional) Testar com GITHUB_TOKEN

Sem token, a API do GitHub limita a 60 requisições/hora por IP — fácil de
estourar com várias pontes reiniciando. Para testar o aumento de limite:

```bash
echo "GITHUB_TOKEN=ghp_xxx" > ~/.config/mautrix-bridges/environment
chmod 600 ~/.config/mautrix-bridges/environment
systemctl --user restart mautrix-bridge@slack
```

A unit já tem `EnvironmentFile=-%h/.config/mautrix-bridges/environment` (o
`-` faz ela ser ignorada se você não criar o arquivo).

## 8. Testar com o Synapse de verdade

Só depois dos passos acima. Siga [docs/SERVIDOR.md](SERVIDOR.md) do começo ao
fim: WireGuard entre as duas máquinas e o registro do `registration.yaml` no
`homeserver.yaml`. Sem isso, tudo o resto funciona e a ponte simplesmente
nunca recebe eventos — o Synapse não tem como alcançá-la.

Pra pegar o `registration.yaml` com os valores reais (o que fica em
`~/.config/mautrix-bridges/slack/` só tem placeholder do chaveiro, o Synapse
não entende isso), use `bridgectl reveal slack --out arquivo.yaml` — não
precisa do `.orig`, ele lê do chaveiro direto.

Depois que o Synapse carregar o appservice sem erro, convide o bot da ponte
(`@slackbot:seu-dominio`) numa sala e siga o fluxo de login descrito na doc
oficial da ponte.

## Nota: pontes legadas (mautrix-discord, por exemplo)

`mautrix-discord` não tem a flag `-e`. `bridgectl setup discord` vai baixar o
binário, tentar o `-e` e avisar que não achou — te aponta para o
`example-config.yaml` do repo no GitHub. Baixe manualmente, salve como
`~/.config/mautrix-bridges/discord/config.yaml`, edite à mão (o `setup` não
sabe achar os placeholders num arquivo com formato diferente):

- `homeserver.address`/`domain` e `bridge.permissions`, como sempre;
- **`appservice.address`/`hostname`: coloque seu IP da VPN, não `localhost`**
  — esse é o passo que mais gente esquece numa ponte legada, e o sintoma é a
  ponte subir normalmente mas nunca receber nada do Synapse.

Depois rode `bridgectl setup discord` de novo — ele percebe que o config já
existe, pula o bootstrap e completa `-g` + harvest. Fora esse detalhe, o
resto do fluxo (run, systemd, auto-update) é idêntico.
