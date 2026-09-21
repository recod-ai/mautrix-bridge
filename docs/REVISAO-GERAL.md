# Revisão geral das pontes e do gestor (bridgectl)

Estado observado em **2026-09-20**, por volta das 17h (horário local), na máquina
que roda as pontes e no servidor (`boule`). Esta revisão foi feita **só por
leitura** (código, arquivos de configuração, bancos SQLite abertos para
consulta, logs, `bridgectl status`, consultas ao Postgres do Synapse e ao
`bridge-pool.json` do metroon). Nenhum segredo está reproduzido aqui: tokens,
senhas e e-mails de terceiros foram omitidos de propósito.

O que é **fato lido** aparece sem marcação; o que é **inferência** vem dito
como tal.

---

## 1. Visão geral

```
 Discord / Slack / Signal / (WhatsApp)
        ▲   sessão pessoal do dono, saindo do IP residencial
        │
 ┌──────┴───────────────────────── notebook do dono ─────────────────────────┐
 │  mautrix-discord  :29334     mautrix-slack  :29335     mautrix-signal :29337│
 │  (binários Go)               (bridgev2)                (bridgev2)          │
 │        ▲  systemd --user  mautrix-bridge@<ponte>.service                   │
 │        │  ExecStartPre: bridgectl update   ExecStart: bridgectl run        │
 │  bridgectl ── chaveiro do Linux (segredos) ── config renderizada em tmpfs  │
 │        │                                                                    │
 │  NetworkManager: conexão WireGuard "bridgectl-vpn"  (10.10.0.2)            │
 └────────┼───────────────────────────────────────────────────────────────────┘
          │ ponte → Synapse: HTTPS público (saída comum)
          │ Synapse → ponte: POST de appservice, só pela VPN (10.10.0.2:porta)
 ┌────────┴───────────────────── servidor boule (10.10.0.1) ──────────────────┐
 │  Synapse (lê 400 registrations em /opt/external-bridges)                    │
 │  MAS (login), Element "stoa"                                                 │
 │  metroon: pool de pontes (bridge-pool.json), API /api/bridge-pool/<tipo>,    │
 │           peers WireGuard, wizard de conexão                                  │
 └──────────────────────────────────────────────────────────────────────────────┘
```

Três peças, com responsabilidades separadas:

| Peça | Onde | Faz |
|---|---|---|
| **Binários mautrix** | `~/.local/share/mautrix-bridges/bin` | Falam com Discord/Slack/Signal e com o Matrix. |
| **bridgectl** | `~/.local/bin/bridgectl` (fonte: este repositório) | Instala/atualiza os binários, guarda segredos no chaveiro, gera a config em RAM, aplica o "padrão da casa", conecta a VPN e busca o slot no pool. |
| **Pool + Synapse** | servidor (repositórios `metroon` e `agorae`) | Pré-registra 100 appservices por tipo de ponte; o Synapse os carrega na inicialização. |

---

## 2. O gestor: `bridgectl`

Um único script Python (1.866 linhas, só stdlib + `keyring`) e uma unit
template do systemd. Não há testes automatizados.

### 2.1 Comandos

| Comando | O que faz |
|---|---|
| `init` | Grava em `bridges.toml` `[server]`: domínio do Synapse, endereço HTTPS, seu IP na VPN, seu MXID (dono). |
| `vpn-init` | Grava `[wireguard]` (chave pública, endpoint e IP do servidor) e guarda no chaveiro o token de API do propylaia. |
| `vpn` | Gera (ou reaproveita) o par de chaves WireGuard, guarda a privada no chaveiro, mostra a pública, importa a conexão `bridgectl-vpn` no NetworkManager (autoconnect ligado). |
| `setup <ponte>` | Baixa o binário, gera `config.yaml`, preenche dados do servidor, aplica o padrão da casa e o backfill escolhido, busca o slot do pool (ou gera `registration.yaml`), move segredos para o chaveiro. |
| `update <ponte>` / `--all` | Checa e baixa binário novo (canal `release` no GitHub, ou `ci` no mau.dev). Cooldown de 900 s. |
| `run <ponte>` | Renderiza config/registration em tmpfs trocando `${keyring:...}` pelos valores, e faz `exec` do binário (o systemd passa a supervisioná-lo). |
| `harvest` | Move segredos de um YAML para o chaveiro, deixando placeholders (e guarda um `.orig` do original). |
| `set` | Grava um segredo à mão no chaveiro. |
| `reveal` | Imprime o `registration.yaml` com valores reais (para pontes fora do pool, que precisam ser entregues ao admin). |
| `bootstrap` | Gera o `config.yaml` de exemplo (`-e`, ou baixa o `example-config.yaml` em pontes legadas como o Discord). |
| `status` | Tabela: versão, canal, última checagem, se há config, se o segredo de teste está no chaveiro. |

### 2.2 Onde cada coisa mora (e o que é sensível)

| Caminho | Conteúdo | Sensível? |
|---|---|---|
| `~/.config/mautrix-bridges/bridges.toml` | servidor, VPN (chave **pública**), lista de pontes, canal, cooldown | não |
| `~/.config/mautrix-bridges/<ponte>/config.yaml` | config com placeholders `${keyring:...}` | quase não (ver 6.4) |
| `~/.config/mautrix-bridges/<ponte>/registration.yaml` | registration com placeholders | não |
| `~/.config/mautrix-bridges/<ponte>/<ponte>.db` (+ `-wal`, `-shm`) | **banco SQLite da ponte** | **sim**: sessão do Discord/Slack/Signal em texto puro, chaves Megolm |
| `~/.config/mautrix-bridges/<ponte>/*.orig`, `slack.db.bak-*` | cópias antigas | **sim** (ver 6.4) |
| `~/.local/share/mautrix-bridges/bin/` | binários das pontes | não |
| `~/.local/share/mautrix-bridges/<ponte>/logs/` | logs em JSON (rotação 100 MB × 10) | contém conteúdo (ver 6.3) |
| `~/.local/share/mautrix-bridges/<ponte>.bak-*` | restos de instalações antigas | **sim** |
| `~/.local/state/mautrix-bridges/<ponte>.json` | versão instalada, data da checagem | não |
| `/run/user/1000/mautrix-<ponte>/` | config e registration **com segredos reais**, só em RAM enquanto a ponte roda | sim, efêmero |
| Chaveiro (serviço `mautrix-<ponte>`) | `as_token`, `hs_token`, `uri` do banco, `pickle_key`, `shared_secret` de provisioning | sim |
| Chaveiro (`bridgectl-wireguard`, `bridgectl-propylaia`) | chave privada WireGuard, token de API do propylaia | sim |

Um ponto que **contradiz o README**: o README diz que o banco e os logs ficam
em `~/.local/share/mautrix-bridges/`. O banco, na prática, fica em
`~/.config/mautrix-bridges/<ponte>/<ponte>.db`, porque `patch_config` aponta a
URI para a pasta do `config.yaml`. Só os logs e os binários ficam em `share`.
Isso importa para backup e para quem sincroniza `~/.config` como dotfiles.

### 2.3 Como a ponte sobe

1. `mautrix-bridge@<ponte>.service` (unit `--user`, `WantedBy=graphical-session.target`).
2. `ExecStartPre=-bridgectl update <ponte> --quiet`: o `-` faz a falha de rede
   não impedir a subida. Se passou o cooldown, **baixa e substitui o binário**.
3. `ExecStart=bridgectl run <ponte>`: espera o chaveiro destrancar (até 120 s,
   testando a chave `as_token`), renderiza os arquivos em `RuntimeDirectory`
   (`0700`, tmpfs), faz `chdir` para `~/.local/share/mautrix-bridges/<ponte>` e `exec`.
4. `Restart=always`, `RestartSec=15s`, sem limite de reinícios.
5. Endurecimento leve: `NoNewPrivileges`, `ProtectSystem=strict` (escreve só em
   `share` e `state`), proteção de kernel, `PrivateTmp`.

### 2.4 O "padrão da casa" que o `setup` aplica

Aplicado **sem perguntar** em config nova, e **perguntando** (padrão "não") em
config já existente:

- Sufixo de plataforma no nome dos fantasmas: `(discord)`, `(slack)`, `(wapp)`, `(signal)`.
- Espaço "geral" desativado (`personal_filtering_spaces: false`) em WhatsApp, Slack e Signal. No Discord esse espaço é fixo no binário.
- **Criptografia** ligada em qualquer ponte que tenha seção `encryption:`: `allow`, `default`, `appservice`, `msc4190` = `true`, e `appservice.ephemeral_events: true`.
- `sync_direct_chat_list: true` (marca DMs em "Pessoas" no Element; só funciona com double puppeting).
- Backfill por preset (`none`, `limited`, `all`), com campos diferentes por ponte (tabela `BACKFILL_PRESETS`).

E, ao buscar o slot do pool: `appservice.id/address/hostname/port`, `bot.username`,
`username_template`, `as_token`, `hs_token` e a restrição de `bridge.permissions`
ao dono do slot em vez de todo o domínio.

### 2.5 Integração com o pool

`setup` chama `GET https://metroon.<domínio>/api/bridge-pool/<tipo>` com o token
de API pessoal. O metroon devolve o slot que corresponde ao **último octeto do
seu IP WireGuard** (`10.10.0.N` = slot `N`), junto com o `owner_mxid` resolvido
no Synapse. Se o slot local já bate (`id` da registration e da config) e as
permissões estão restritas, o `setup` considera "em sincronia" e **não reescreve
nada** (ver achado 6.1).

---

## 3. O lado do servidor

### 3.1 Pool (`metroon/src/bridge-pool.js`)

- 4 tipos: `discord` (29334), `slack` (29335), `whatsapp` (29336), `signal` (29337).
- 100 slots por tipo (sufixos 2..101), gerados uma vez e nunca regerados.
- Cada slot: `id`, `as_token`, `hs_token`, regex e template de usuário
  (`<tipo>_sNNN_`), bot `<tipo>bot_sNNN`, `url` fixa `http://10.10.0.N:porta`.
- Não há "reserva" separada: quem tem aquele IP WireGuard é o dono. O campo
  `claimedBy` só é gravado na primeira busca.
- Estado hoje: **1 slot reivindicado** por tipo em discord, slack e signal
  (todos o slot 002); whatsapp: 0. **2 peers** WireGuard cadastrados.
- Synapse: **400 registrations** montadas de `/opt/external-bridges/*.yaml` e
  listadas em `homeserver.yaml`; o Synapse só as lê na inicialização, então
  qualquer alteração exige reinício dele.
- Toda registration do pool traz `push_ephemeral`, `receive_ephemeral`,
  `io.element.msc4190` e, desde hoje, `org.matrix.msc3202` (ver 6.1).

### 3.2 Ligações com o resto

- Metroon também serve o assistente de conexão do perfil (comandos de login por ponte e proxy de QR), fora do escopo deste repositório.
- MAS (login) exige MSC4190 para as pontes terem dispositivo de criptografia.

---

## 4. Estado atual de cada ponte

### 4.1 Comparativo

| | Discord | Slack | Signal | WhatsApp |
|---|---|---|---|---|
| Serviço systemd | ativo | ativo | ativo | **habilitado, morto** desde 17/09 |
| Binário | `ci-c62165a46109` (instalado 17/09) | `ci-47e319dd6f02` (**instalado hoje 12:31**) | `ci-32b9e0ca6832` (**instalado hoje 12:30**) | `v0.2608.0` (04/09, release) |
| Framework | legado (`bridge.*`) | bridgev2 | bridgev2 | bridgev2 |
| Slot / porta | `discord-slot-002` / 29334 | `slack-slot-002` / 29335 | `signal-slot-002` / 29337 | não reivindicado |
| Escuta (`hostname`) | `*` (todas as interfaces) | `*` (todas) | `10.10.0.2` (só a VPN) | – |
| Banco | `discord.db` 0,4 MB + WAL 4 MB | `slack.db` 2,5 MB | `signal.db` 2,5 MB | antigo, em `share/whatsapp` |
| Contas ligadas | 1 usuário | 1 login (1 workspace) | 1 login | – |
| Portais no banco / com sala Matrix | 183 / 21 | 86 / 46 | 4 / 4 | – |
| Mensagens registradas | 272 | 1.807 | 60 | – |
| Fantasmas | 66 | 197 | 7 | – |
| Double puppeting | **nenhum** | configurado, **token expirado** | configurado (não validado) | – |
| `encryption.allow_key_sharing` | **false** | true | true | – |
| Backfill inicial | 20 mensagens (DM e canal) | 50 (limite `conversation_count: -1`) | 20 | – |
| Permissões | `"*": relay` + dono admin | idem | idem | – |
| Sufixo do nome | `(discord)` | `(slack)` | `(signal)` | – |
| Log | `debug` | `debug` | `debug` | (126 MB acumulados) |

### 4.2 Discord

- 3 guilds no banco; **só 1 está ligada** (`bridging_mode` 3, o mais amplo; **não confirmei o nome de cada modo**), as outras duas estão em 0.
- 183 portais no banco mas só 21 com sala. **Inferência**: os demais são DMs/canais descobertos que ainda não ganharam sala (limite `startup_private_channel_create_limit: 10` e backfill limitado).
- Criptografia de ponta a ponta até a ponte ligada por padrão; `verification_levels.share: cross-signed-tofu` (só compartilha chaves com dispositivos cross-signed).
- Provisioning habilitado em `/_matrix/provision` (segredo no chaveiro).
- `avatar_proxy_key: generate` e `direct_media.server_key: generate`: **regerados a cada início**, porque o `harvest` não os cobre (ver 6.6).
- `delete_guild_on_leave: true`, `forbid_dming_strangers: true`.
- Erros de 24 h: 14× `403 Missing Access` no backfill de canais sem permissão (Discord), 12× falha de DNS ao abrir o gateway (rede local), avisos de OTK (6.5).

### 4.3 Slack

- 1 workspace ligado. 86 portais: 29 sem tipo registrado (canais), 13 DMs, 3 DMs em grupo, 1 espaço.
- Criptografia igual à do Signal (com `allow_key_sharing: true`).
- Nota: `slack.db.bak-*` (4 arquivos) e `share/slack.bak-*` (69 MB) são restos de manutenção anterior.
- Erros de 24 h: falhas de DNS ao falar com o Synapse (11:40), e `M_UNKNOWN_TOKEN` ao configurar o double puppeting às 12:31 (token expirado, ver 6.7).

### 4.4 Signal

- Ligado como dispositivo secundário (`device_name: mautrix-signal`). 4 portais, todos com sala (3 DMs e 1 de outro tipo, provavelmente a conversa consigo mesmo).
- Único que escuta **só na VPN** (`10.10.0.2`).
- `public_media.signing_key` e `direct_media.server_key` estão **em texto puro** no `config.yaml` (gerados uma vez pelo binário e gravados de volta).
- Erros de 24 h: timeouts de ping no websocket do Signal (queda de rede), com retentativas a cada minuto.

### 4.5 WhatsApp

- `mautrix-bridge@whatsapp` está **habilitado** (`graphical-session.target.wants`) mas **não está em `bridges.toml`** (comentada). Falha na subida com status 1 desde 17/09 e não tenta de novo (o `bridgectl run` recusa uma ponte que não está no toml).
- Restam `share/whatsapp/mautrix-whatsapp.db` (sessão do WhatsApp) e 126 MB de logs.

---

## 5. Saúde observada (24 h)

- **VPN**: `bridgectl-vpn` ativa, servidor responde ao ping (~9 ms).
- **Rede local instável às 11:39–11:41** (falhas de DNS em Discord, Slack e Synapse) e ping do Signal expirando: o modelo "ponte no notebook" depende da rede do notebook.
- **Reinícios em 48 h**: Signal 5× (um deles foi o meu de hoje; **não investiguei** os outros quatro), Discord e Slack 1× (os meus de hoje).
- **Ruído**: 1.400+ avisos de "Dropping OTK counts targeted to someone else" no Discord em 24 h (6.5).
- **Journal do usuário**: 675 MB.
- **Entrega de chaves Megolm**: depois da correção de hoje, o Discord compartilhou sessões com **3 dispositivos** do dono (incluindo a sessão atual do Element), como esperado.

---

## 6. Achados e riscos

Severidade: **A** = pode causar perda de dados/segurança ou falha recorrente;
**M** = fragilidade ou inconsistência real; **B** = melhoria/documentação.

### 6.1 [A, corrigido hoje] Registrations sem `org.matrix.msc3202`
Sem essa flag, o Synapse não informa à ponte sobre dispositivos novos do usuário
(nem contagens de chaves de uso único). A ponte só compartilhava as chaves com o
dispositivo que viu na primeira vez, e as demais sessões do Element mostravam
"Unable to decrypt message". A flag global `msc3202_transaction_extensions` do
Synapse estava ligada, mas só vale para registrations que declaram a flag.

Feito: linha adicionada nos 400 arquivos do servidor + reinício do Synapse;
adicionada nas 3 registrations locais; `bridge-pool.js` e `bridgectl setup`
agora emitem a flag; cache de dispositivos e sessões de saída zerados nas 3
pontes (backup dos bancos antes).

**Ainda em aberto:**
- `~/.local/bin/bridgectl` **não é a versão do repositório** (a diferença é só essa mudança). Falta rodar `./install.sh`.
- `setup` considera "em sincronia" um slot que só difere por essa linha e **não atualiza** a registration local de quem já configurou; só quem gera registration nova a recebe. Os outros alunos precisam da linha à mão.
- Cada reset de criptografia cria um dispositivo novo do bot (MSC4190) e os antigos ficam no Synapse: hoje `discordbot_s002` tem 5, `slackbot_s002` 2 e `signalbot_s002` 2.

### 6.2 [A] Canal `ci` em todas as pontes + atualização automática a cada reinício
`[defaults] channel = "ci"`: o binário é o último build verde do `main` no
mau.dev, não uma release. Como o `ExecStartPre` atualiza a cada (re)início após
o cooldown, **qualquer reinício pode trocar o binário por código ainda não
lançado**. Hoje, ao reiniciar Signal e Slack, os dois foram atualizados (o
`installed_at` é de hoje). Não há como voltar sem baixar o anterior de novo
(só existe um `mautrix-discord.orig-official` avulso).

### 6.3 [A] Log em `debug` nas três pontes
`logging.min_level: debug` (padrão do exemplo). O journal do Discord gerou
6.380 linhas em 24 h e contém, entre outras coisas, o corpo cifrado de cada
mensagem e URLs completas com IDs. Além do journal (675 MB), cada ponte grava
`./logs/*.log` em JSON (até 10 × 100 MB). O README não menciona isso.

### 6.4 [A] Segredos em texto puro fora do chaveiro
- `config.yaml.orig` e `registration.yaml.orig` do **Discord e do Slack** contêm `as_token` e `hs_token` reais (o `harvest` avisa: "cópia original ainda com segredos"). Nada as apaga depois.
- `signal/config.yaml` tem `public_media.signing_key` e `direct_media.server_key` literais.
- Bancos: sessão do Discord (token) e do Slack em texto puro, como o README já admite; mas também há **cópias antigas** (`slack.db.bak-*`, `share/discord.bak-*`, `share/slack.bak-*`, `share/whatsapp/*.db`) com sessões, esquecidas.
- Mitigação existente: tudo dentro de diretórios `0700` do usuário. Não há criptografia de disco verificada por esta revisão.

### 6.5 [M] Bots com dispositivos antigos geram ruído
Os dispositivos antigos de cada bot continuam recebendo contagens de OTK que a
ponte descarta ("targeted to someone else"): ~1.400 avisos em 24 h só no Discord.
Inofensivo, mas polui o log e esconde erros reais.

### 6.6 [M] `generate` regenerado a cada início
O `harvest` só cobre `HARVEST_KEYS`. Valores como `avatar_proxy_key`,
`public_media.signing_key` e `direct_media.server_key`, quando ficam `generate`,
são recriados a cada subida (a config no disco não é reescrita), o que
invalida URLs assinadas anteriores. Impacto baixo hoje (mídia direta/pública
desligadas), mas é o mesmo mecanismo que já quebrou o `pickle_key` uma vez.

### 6.7 [M] Double puppeting inconsistente
- **Discord**: nenhum (0 puppets com login Matrix). Mensagens suas vindas do Discord aparecem como o fantasma, e `sync_direct_chat_list: true` não tem efeito.
- **Slack**: token guardado, mas o log de hoje (12:31) mostra `M_UNKNOWN_TOKEN: Token is not active`.
- **Signal**: token guardado; validade não verificada.
O método manual (`login-matrix`) exige repetir quando o token expira sob MAS,
e não avisa quando isso acontece (documentado em `SERVIDOR.md`).

### 6.8 [M] Inconsistência entre pontes
| Item | Discord | Slack | Signal |
|---|---|---|---|
| `appservice.hostname` | `0.0.0.0` | `0.0.0.0` | `10.10.0.2` |
| `encryption.allow_key_sharing` | false | true | true |
| Backfill | 20 msgs | 50 msgs | 20 msgs |

`apply_pool_config` força `0.0.0.0`. O Signal escuta só na VPN; **não sei por qual
caminho** ele foi configurado assim (provavelmente antes de o pool existir para ele). Escutar em `0.0.0.0` expõe a porta do appservice também na
Wi-Fi/LAN, protegida apenas pelo `hs_token`. Trocar por `10.10.0.2` fecha isso
(custo: a ponte falha ao subir com a VPN caída até ela voltar; o
`Restart=always` cobre).
`allow_key_sharing` é `false` no Discord por ser o padrão do framework legado
(nas outras é `true`); com `true`, dispositivos **cross-signed** conseguem
pedir chaves antigas à ponte (`verification_levels.share: cross-signed-tofu`).

### 6.9 [M] WhatsApp: unit habilitada, quebrada e com dados velhos
Ver 4.5. Nada a ver com o pool (0 slots reivindicados).

### 6.10 [M] Disponibilidade depende do notebook e da sessão gráfica
O chaveiro só destranca no login gráfico (`WantedBy=graphical-session.target`).
Notebook dormindo, rede caindo ou sessão encerrada = ponte parada e mensagens
atrasadas até reconectar (as quedas de 19/09 no Discord e de hoje no Signal e
no DNS são exemplos). Isso é decisão de projeto (IP residencial para o
Discord/Slack), com o custo declarado.

### 6.11 [B] Fragilidade do próprio `bridgectl`
- Edições de config por **regex, sem parser YAML** (assumido no código como escolha). Um exemplo que já quebrou: o `set_in_section` que não achava `username_template` no bloco certo.
- `setup` só reaplica o pool se o `id` ou a permissão divergem; mudanças novas em registration não se propagam (6.1).
- Sem testes, sem comando de diagnóstico (`doctor`), sem comando de backup nem de reset de criptografia, sem controle de nível de log.
- Sem opção de fixar versão (só `update_cooldown` gigante).

### 6.12 [B] Documentação desatualizada
- README: banco em `share` (na prática está em `config`), e não cita `debug`/logs.
- `docs/ADICIONAR-PONTE.md` (repo agorae) ainda diz "Discord/Slack/WhatsApp" em trechos; o pool já tem 4 tipos com Signal.
- Comentários do `bridgectl` falam em "três tipos do pool" onde já são quatro.

---

## 7. O que foi mexido hoje (transparência)

Antes desta revisão, nesta mesma sessão de trabalho:

1. Servidor: `org.matrix.msc3202: true` acrescentado a 400 arquivos em `/opt/external-bridges/` + reinício do Synapse.
2. Local: mesma linha nas 3 `registration.yaml` (Discord, Signal, Slack).
3. Local: parei cada uma das 3 pontes, copiei os bancos para a pasta temporária da sessão, apaguei `crypto_device`, `crypto_tracked_user` e `crypto_megolm_outbound_session*` e reiniciei.
4. **Efeito colateral não anunciado na hora**: esses reinícios dispararam a atualização automática do Signal e do Slack (6.2).
5. Repositório: `bridgectl` (gera registration com a flag) commitado (`8d1ce37`), sem push. `metroon`: `bridge-pool.js` commitado e no ar.

---

## 8. Recomendações (nenhuma aplicada)

Por ordem de custo-benefício:

1. Rodar `./install.sh` para o `bridgectl` instalado igualar o repositório.
2. Trocar `[defaults] channel` para `release` (ou fixar por ponte) e/ou aumentar `update_cooldown`, para que reiniciar não troque de versão sem você decidir.
3. Subir `logging.min_level` para `info` (ou `warn`) nas três pontes e limpar `logs/` antigos (whatsapp 126 MB, slack.bak 63 MB).
4. Apagar `.orig`, `slack.db.bak-*`, `share/*.bak-*` e `share/whatsapp` depois de confirmar que nada mais precisa deles.
5. Refazer o double puppeting do Slack e configurar o do Discord (`login-matrix`), validar o do Signal.
6. Desabilitar `mautrix-bridge@whatsapp` (`systemctl --user disable`) ou configurá-la de verdade.
7. Mudar `appservice.hostname` do Discord e do Slack para `10.10.0.2`, alinhando com o Signal.
8. Decidir `allow_key_sharing` de forma uniforme (recomendo `true` nas três, dado `cross-signed-tofu`).
9. Passar a fazer backup periódico dos bancos (`*.db` + `-wal`); eles concentram as chaves Megolm.
10. Limpar dispositivos antigos dos bots no Synapse (API de admin) para reduzir o ruído de OTK.
11. Melhorias no `bridgectl`: comando `doctor` (checa registration × flags esperadas × config), propagação de mudanças de registration no `setup`, cobertura do `harvest` para `*_key` gerados, e testes para as funções de regex.

---

## 9. Como reproduzir esta leitura

```bash
bridgectl status
systemctl --user list-units 'mautrix-bridge@*'
journalctl --user -u mautrix-bridge@<ponte> --since '24 hours ago' | grep -E ' (WRN|ERR) '
sqlite3 ~/.config/mautrix-bridges/<ponte>/<ponte>.db '.tables'   # leitura; feche a ponte antes de escrever
ss -ltnH | grep -E ':2933[4-7]'                                   # em que interface cada ponte escuta
```
