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
sudo pacman -S python-keyring gnome-keyring wireguard-tools networkmanager   # Arch; noutras distros: pip install --user keyring
./install.sh
```

## Uso

```bash
bridgectl vpn-init         # uma vez: peer WireGuard do servidor + seu token de API do propylaia
bridgectl vpn              # gera sua chave, importa a VPN no NetworkManager — ver "Conectividade"
bridgectl init             # uma vez: domínio do Synapse, endereço, seu IP na VPN, seu Matrix ID
bridgectl setup slack      # baixa o binário, gera config, busca o registration e harvesta sozinho
```

Rodar `init`, `vpn-init` ou `setup <ponte>` de novo depois de já configurado não
te faz digitar tudo de novo — cada um mostra o que já está gravado e só volta
a perguntar se você confirmar que quer editar (com os valores atuais já
preenchidos como default).

Numa config nova, `setup` também pergunta quanto histórico carregar quando
uma conversa for descoberta pela primeira vez (nada / um pouco / tudo que
der) — vale para Discord, Slack, WhatsApp e Signal, cada um com seu próprio
jeito de guardar isso no `config.yaml` (o Discord vem desligado por padrão
nesse ponto; Slack/WhatsApp/Signal já vêm sem limite). Pra mudar depois,
edite `config.yaml` à mão (`backfill:`/`history_sync:`, dependendo da ponte).

Para essas mesmas quatro pontes, `setup` também aplica sem perguntar (padrão
do projeto): um sufixo de plataforma no nome dos fantasmas (`Nome Sobrenome
(discord)`/`(slack)`/`(wapp)`/`(signal)`) e o space "geral" desativado no
Slack/WhatsApp/Signal (o do Discord não tem essa opção — é fixo no próprio
binário da ponte). **End-to-end encryption** (`encryption.allow`/`default`,
mais MSC4190 — exigido por este servidor usar MAS, ver docs/SERVIDOR.md) é
ligada automaticamente pra **qualquer** ponte que tenha seção `encryption:`,
não só essas quatro — sem isso o bot não consegue entrar em salas que o
Element já cria criptografadas por padrão, nem completar o próprio login do
appservice neste servidor. Numa config já existente, `setup` pergunta antes
de aplicar qualquer um desses ajustes.

Para **Discord, Slack, WhatsApp e Signal**, `setup` já busca um registro
pré-feito no servidor (usando o token de API de `vpn-init`) — não precisa
mandar nada pro administrador, é só ligar o serviço:

```bash
systemctl --user enable --now mautrix-bridge@slack
journalctl --user -u mautrix-bridge@slack -f
```

Para qualquer outra ponte (Telegram, Teams, ...), `setup` gera um
registro novo do zero, e você ainda precisa mandar pro administrador:

```bash
bridgectl reveal telegram --out registration-para-o-admin.yaml   # com os valores reais
```

Mande esse `registration-para-o-admin.yaml` para o administrador do servidor
e apague sua cópia depois — siga [docs/SERVIDOR.md](docs/SERVIDOR.md) para
essa parte.

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
exemplo) não têm a flag `-e` — nesse caso o `setup` baixa o
`example-config.yaml` do repositório da ponte sozinho antes de continuar; ver
a nota em [docs/TESTING.md](docs/TESTING.md).

`bridgectl status` mostra, por ponte, a versão instalada e se o segredo já
está no chaveiro (coluna `segredos`) — é como saber quais pontes já estão
prontas pra `systemctl enable`.

## Conectividade

Tráfego de appservice tem duas direções, e só uma delas é o problema:

- **Ponte → Synapse** (ler/enviar eventos): saída normal, HTTPS público — sem
  segredo nenhum, é como qualquer cliente Matrix.
- **Synapse → ponte** (o POST que entrega eventos, é *push*): o Synapse
  precisa alcançar a URL do `registration.yaml`. Como a ponte roda no seu
  computador atrás de NAT (é assim que o tráfego do Discord/Slack/WhatsApp/Signal
  sai com IP residencial, não IP de datacenter), essa direção não funciona
  sem ajuda — a solução é uma **VPN WireGuard** entre as duas máquinas, só
  pra essa chamada de volta.

Do lado do servidor: [docs/SERVIDOR.md](docs/SERVIDOR.md). Do seu lado, dois
comandos cuidam de tudo — sem editar `/etc/wireguard` nem mexer em systemd à
mão, e a chave privada nunca fica num arquivo em texto puro (vai direto pro
chaveiro):

```bash
bridgectl vpn-init   # uma vez: chave pública, endereço (host:porta) e IP do
                      # servidor nesta VPN — o administrador te dá esses três
bridgectl vpn        # gera seu par de chaves (ou reaproveita, se já existir),
                      # mostra a chave pública pra você registrar no servidor,
                      # e importa a conexão no NetworkManager
```

`vpn` para na hora de mostrar a chave pública e pergunta se você já registrou
ela no servidor antes de continuar — registre (ex.: na página `/propylaia` da
agorae, se for esse o seu caso) e responda "s". Ele então monta a conexão,
renomeia pra `bridgectl-vpn` e move a chave privada pro chaveiro do sistema
(`nmcli ... wireguard.private-key-flags 1`) — a conexão passa a aparecer no
painel de rede do seu ambiente gráfico, igual uma VPN comum, sem precisar de
`wg-quick` nem de um serviço systemd separado.

**Prefere pela interface gráfica em vez de rodar o comando?** Dá pra fazer
igual: GNOME (Configurações → Rede → "+" → "Importar de arquivo…") ou KDE
(Configurações do Sistema → Conexões de Rede → Adicionar → WireGuard →
Importar) sabem abrir um arquivo `.conf` no formato `wg-quick` direto — é
esse mesmo arquivo que `bridgectl vpn` monta e descarta depois de importar.
Depois de importado, tanto GNOME quanto KDE mostram um campo de senha/chave
com uma opção "salvar só para este usuário" — é a versão gráfica do
`wireguard.private-key-flags 1`.

Se preferir configurar à mão (sem `nmcli` nem `bridgectl vpn`), o arquivo é
um `.conf` padrão de `wg-quick`:

```ini
[Interface]
PrivateKey = <sua chave privada>
Address = 10.10.0.2/24

[Peer]
PublicKey = <chave pública do servidor>
Endpoint = <endereço do servidor>:51820
AllowedIPs = 10.10.0.1/32
PersistentKeepalive = 25
```

Em `bridgectl init` (Synapse) e `bridgectl vpn-init` (WireGuard), o "endereço"
e o "IP na VPN" viram dois campos diferentes, não um só:

- **"Endereço público do Synapse"**: a URL HTTPS normal (ex:
  `https://matrix.exemplo.com`) — vira `homeserver.address` no config da
  ponte. Não tem nada a ver com a VPN.
- **"Seu IP nesta VPN"** (ex: `10.10.0.2`, o que o administrador te deu):
  vira `appservice.address`/`appservice.hostname` — é o endereço que o
  Synapse usa pra chamar sua ponte de volta, e só existe alcançável pela VPN.

Sem manutenção depois disso: as chaves não expiram, e como é sempre o seu
computador que inicia a conexão, trocar de rede/Wi-Fi não derruba o túnel.

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

## Double puppeting: manual nas pontes do pool, de propósito

Escolhemos o método manual (`login-matrix`, ver
[docs/SERVIDOR.md](docs/SERVIDOR.md) seção 3) para Slack, Discord, WhatsApp
e Signal — não o automático (que exigiria o administrador registrar um
segundo appservice pra sua conta, ou pior, uma chave-mestra do servidor
inteiro nas pontes legadas). É a mesma troca de segurança de sempre,
generalizada pras quatro: menos automação em troca de nenhum segredo com
poder sobre a conta de outra pessoa em texto claro no seu notebook.

**Efeito colateral aceito**: sem o appservice automático, um Synapse comum
não anuncia a capability `BeeperAutoJoinInvites` (exclusiva do Beeper), e a
ponte não tenta entrar sozinha nas salas que te convida — é preciso aceitar
manualmente. Isso não é um bug: é a consequência direta de não ter mais um
appservice de double puppeting administrado centralmente pelo servidor, como
tinha a instalação anterior (`matrix_appservice_double_puppet_enabled` no
`matrix-docker-ansible-deploy`).

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
