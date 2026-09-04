# mautrix-bridge

Roda pontes [mautrix](https://docs.mau.fi/bridges/) (Slack, Discord, WhatsApp,
Telegram, ...) no seu computador, com os segredos no chaveiro do Linux (GNOME
Keyring / KWallet) em vez de arquivo em texto puro, e checagem de atualização
a cada início/reinício do serviço.

Este repositório é só o lado do **cliente** (a máquina que roda as pontes). O
que precisa ser feito do lado do Synapse está em
[docs/SERVIDOR.md](docs/SERVIDOR.md).

## Instalação

```bash
sudo pacman -S python-keyring gnome-keyring wireguard-tools   # Arch; noutras distros: pip install --user keyring
./install.sh
```

## Uso

```bash
bridgectl init            # uma vez: domínio do Synapse, endereço, seu Matrix ID
bridgectl setup slack     # baixa o binário, gera config+registration, harvesta os segredos
```

O `setup` imprime, no final, um `registration.yaml` para copiar para o
servidor — siga [docs/SERVIDOR.md](docs/SERVIDOR.md) para essa parte. Depois:

```bash
systemctl --user enable --now mautrix-bridge@slack
journalctl --user -u mautrix-bridge@slack -f
```

**Antes de ir com tudo pro Synapse real, veja [docs/TESTING.md](docs/TESTING.md)**
— um passo a passo verificado na prática pra validar cada peça isoladamente.

## Como funciona

```
bridgectl setup   -> baixa o binário, gera config.yaml/registration.yaml,
                      move os segredos pro chaveiro do Linux
bridgectl run     -> lê o config.yaml (só com placeholders ${keyring:...}),
                      troca cada placeholder pelo valor real do chaveiro,
                      escreve isso num arquivo em tmpfs (RAM) e executa a ponte
```

O `config.yaml` que fica em disco nunca tem segredo em texto puro. O arquivo
com os valores reais só existe em RAM, só enquanto a ponte está rodando, e some
quando ela para.

## Adicionando uma ponte

```bash
# declare em ~/.config/mautrix-bridges/bridges.toml (slack e discord já vêm
# prontos no bridges.toml.example; para outras, só repo + binary):
#   [bridges.whatsapp]
#   repo = "whatsapp"
#   binary = "mautrix-whatsapp"

bridgectl setup whatsapp
```

`setup` é idempotente — se algo já existe (config, registration) ele mantém e
só completa o que falta, então rodar de novo depois de corrigir um erro é
seguro. Pontes legadas sem o template automático (mautrix-discord, por
exemplo) avisam isso e pedem pra você buscar o `example-config.yaml` manual
antes de completar — ver a nota em [docs/TESTING.md](docs/TESTING.md).

`bridgectl status` mostra, por ponte, a versão instalada e se o segredo já
está no chaveiro (coluna `segredos`) — é como saber quais pontes já estão
prontas pra `systemctl enable`.

## Conectividade

Appservice é *push*: o Synapse faz POST na URL do `registration.yaml`. Como a
ponte roda no seu computador atrás de NAT (é assim que o tráfego do
Discord/Slack/WhatsApp sai com IP residencial, não IP de datacenter), o
Synapse não alcança essa URL sozinho — a solução é uma **VPN WireGuard** entre
as duas máquinas.

Do lado do servidor: [docs/SERVIDOR.md](docs/SERVIDOR.md). Do seu lado:

```bash
wg genkey | tee privatekey | wg pubkey > publickey
```

`/etc/wireguard/wg0.conf`:

```ini
[Interface]
PrivateKey = <conteúdo de privatekey>
Address = 10.10.0.2/24

[Peer]
PublicKey = <chave pública do servidor>
Endpoint = <ip-publico-do-servidor>:51820
AllowedIPs = 10.10.0.1/32
PersistentKeepalive = 25
```

```bash
sudo systemctl enable --now wg-quick@wg0
```

Em `bridgectl init`, o "endereço do Synapse" passa a ser `http://10.10.0.1:8008`
(o IP do servidor na VPN). Sem manutenção depois disso: as chaves não expiram,
e como é sempre o seu computador que inicia a conexão, trocar de rede/Wi-Fi
não derruba o túnel.

## Auto-update

A unit do systemd roda `bridgectl update <ponte>` a cada início e reinício:

- **`channel = "release"`** (padrão): última tag no GitHub, asset da sua
  arquitetura.
- **`channel = "ci"`**: último build do branch `main` no
  [mau.dev](https://mau.dev) — útil pra ponte sem release pro seu arch.
- Cooldown de 900s entre checagens (evita martelar o GitHub num crash loop);
  `--force` ignora.
- Rede fora do ar não impede a ponte de subir com o binário já instalado.
- Download é validado (magic ELF + tamanho) antes de substituir o binário.
- Sem `GITHUB_TOKEN`, a API do GitHub limita a 60 req/h. Coloque um token
  (sem escopo nenhum já serve) em `~/.config/mautrix-bridges/environment`
  como `GITHUB_TOKEN=...` pra subir pra 5000/h.

Para congelar uma ponte, ponha `update_cooldown = 31536000` nela no
`bridges.toml`.

## Segurança e limitações

- **O chaveiro só destranca no login gráfico.** A unit é
  `WantedBy=graphical-session.target`; `loginctl enable-linger` não resolve
  isso sozinho. Pra rodar 24/7 sem sessão gráfica, as pontes precisariam
  voltar a rodar no servidor, ou os segredos iriam para
  `systemd-creds`/`pass` — o que devolve parte do que o chaveiro protegia.
- **tmpfs não é cofre contra root** — protege contra backup/sync acidental do
  config, não contra alguém que já tem acesso à sua sessão.
- **O banco guarda a sessão do Slack/Discord em texto puro, sem criptografia.**
  O login feito por comando na sala de gerenciamento fica salvo assim no banco
  da ponte — o chaveiro só protege `as_token`/`hs_token`/connection string do
  banco/segredo de double puppeting, que são config estático; a sessão é dado
  operacional, escrito pela própria ponte, e não passa por esse mecanismo.
  Isso não é uma fragilidade nova deste projeto: é o mesmo modelo do cookie de
  sessão no seu navegador hoje — Firefox guarda cookies em SQLite sem
  criptografia nenhuma, e o app desktop do Discord guarda o token em
  `localStorage` do mesmo jeito. Nos dois casos, a proteção é só "estar
  logado como o usuário certo no sistema". A diferença real aqui é a
  concentração: Slack, Discord e WhatsApp ficam todos expostos pelo mesmo
  mecanismo, em vez de isolados em perfis/apps separados. Mitigar isso de
  verdade exige criptografia de disco (LUKS) — fora do escopo deste
  `bridgectl`.
- **Não precisa de Postgres nem Docker**: as pontes aceitam
  `database.type: sqlite3-fk-wal` — testado, funciona sem nenhum servidor de
  banco. Só use Postgres se a ponte específica não suportar SQLite ou se o
  uso for pesado; nesse caso, instale nativo (`pacman -S postgresql`), não em
  container.

## Estrutura do repositório

```
bin/bridgectl                    o script (Python, só stdlib + python-keyring)
systemd/mautrix-bridge@.service  unit template do systemd --user
config/bridges.toml.example      exemplo de configuração das pontes
install.sh                       copia os três acima para os lugares certos
docs/TESTING.md                  passo a passo pra validar tudo, testado na prática
docs/SERVIDOR.md                 o que pedir ao administrador do servidor (peer WireGuard, registro da ponte)
```
